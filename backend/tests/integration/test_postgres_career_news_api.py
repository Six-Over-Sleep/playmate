"""커리어 브리핑 뉴스 조회·스크랩 API를 실제 PostgreSQL과 HTTP 경로로 검증한다 (Issue #74).

일회용 DB 주소를 PLAYMATE_CAREER_NEWS_TEST_DB_URL로 줄 때만 실행한다. (공용 DB 사용 금지, localhost만 허용)
예) PLAYMATE_CAREER_NEWS_TEST_DB_URL=postgresql://postgres:test@127.0.0.1:55437/pm
DB_* 환경변수를 이 주소로 바꾸고 PGOPTIONS로 전용 스키마(career_news_api_test)만 보게 한 뒤,
실제 인증(X-Dev-Member-ID → members 확인)·db_cursor·SQL을 거쳐 API를 호출한다. 끝나면 스키마를 지운다.
뉴스 데이터는 1차 가져오기 스크립트(import_articles)로 넣어 수집 → API 흐름을 그대로 확인한다.
"""
import importlib.util
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
import psycopg2
from psycopg2.extras import RealDictCursor
import pytest


DB_URL = os.getenv("PLAYMATE_CAREER_NEWS_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="일회용 PostgreSQL에서만 실행")

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "database" / "sql" / "017_career_news.sql"
SCHEMA = "career_news_api_test"
SPEC = importlib.util.spec_from_file_location(
    "import_career_news", ROOT / "database" / "scripts" / "import_career_news.py"
)
importer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(importer)

NOW = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def article(token, title, fields, published, source="예시신문"):
    url = importer.normalize_link(f"https://news.google.com/rss/articles/{token}?oc=5")
    return importer.NewsArticle(
        link_key=importer.link_key_of(url), link_url=url, link_type=importer.link_type_of(url),
        title=title, source_name=source, published_at=published, field_codes=set(fields),
    )


ARTICLES = [
    article("AI1", "생성형 AI 투자 확대", {"data_ai", "cloud_infra"}, NOW - timedelta(hours=1)),
    article("SEC1", "랜섬웨어 대응 강화", {"security"}, NOW - timedelta(days=2)),
    article("BE1", "스프링 부트 업데이트", {"backend"}, NOW - timedelta(days=5)),
    article("OLD1", "오래된 프론트엔드 기사", {"frontend"}, NOW - timedelta(days=40)),
    article("NODATE", "발행일 없는 QA 기사", {"qa_test"}, None),  # first_seen_at(가져온 시각)으로 정렬
    article("HIDE1", "숨긴 모바일 기사", {"mobile"}, NOW - timedelta(hours=2)),
]


def admin_connection():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    return conn


@pytest.fixture
def api(monkeypatch):
    target = urlsplit(DB_URL)
    if target.hostname not in ("127.0.0.1", "localhost"):
        pytest.skip("로컬 일회용 DB(127.0.0.1/localhost)에서만 실행")

    with admin_connection() as conn, conn.cursor() as cursor:
        cursor.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        cursor.execute(f"CREATE SCHEMA {SCHEMA}")
        cursor.execute(f"SET search_path = {SCHEMA}")
        cursor.execute("CREATE TABLE members (member_id BIGINT PRIMARY KEY, discord_id VARCHAR(30), nickname VARCHAR(50))")
        cursor.execute("INSERT INTO members VALUES (1, '1001', '민혁'), (2, '1002', '효원')")
        cursor.execute(MIGRATION.read_text(encoding="utf-8"))
        with conn.cursor(cursor_factory=RealDictCursor) as dict_cursor:
            dict_cursor.execute(f"SET search_path = {SCHEMA}")
            importer.import_articles(dict_cursor, ARTICLES, NOW)
            dict_cursor.execute("UPDATE career_news SET hidden_at = %s WHERE title = '숨긴 모바일 기사'", (NOW,))

    from app.core import db_connect

    db_connect.close_pool()
    for key, value in {
        "DB_HOST": target.hostname, "DB_PORT": str(target.port or 5432),
        "DB_USER": target.username or "postgres", "DB_PASSWORD": target.password or "unused",
        "DB_NAME": target.path.lstrip("/"), "DB_SSLMODE": "disable", "APP_ENV": "test",
        "PGOPTIONS": f"-c search_path={SCHEMA}",
    }.items():
        monkeypatch.setenv(key, value)

    from app.main import app

    with TestClient(app) as client:
        yield client
    db_connect.close_pool()
    with admin_connection() as conn, conn.cursor() as cursor:
        cursor.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")


def call(client, method, path, member=1):
    return getattr(client, method)(path, headers={"X-Dev-Member-ID": str(member)})


def titles(response):
    assert response.status_code == 200, response.text
    return [item["title"] for item in response.json()["items"]]


def db_rows(sql, params=()):
    with admin_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(f"SET search_path = {SCHEMA}")
        cursor.execute(sql, params)
        return cursor.fetchall()


def test_list_recent_sorted_filtered_and_hidden_excluded(api):
    # 기본 30일: 40일 전 기사·숨긴 기사 제외, 최신순 (발행일 없는 기사는 가져온 시각 = 지금)
    assert titles(call(api, "get", "/api/career/news")) == [
        "발행일 없는 QA 기사", "생성형 AI 투자 확대", "랜섬웨어 대응 강화", "스프링 부트 업데이트",
    ]
    assert titles(call(api, "get", "/api/career/news?days=90")).count("오래된 프론트엔드 기사") == 1
    assert titles(call(api, "get", "/api/career/news?days=3")) == [
        "발행일 없는 QA 기사", "생성형 AI 투자 확대", "랜섬웨어 대응 강화",
    ]
    assert titles(call(api, "get", "/api/career/news?limit=2")) == ["발행일 없는 QA 기사", "생성형 AI 투자 확대"]

    # 분야 필터: 여러 분야 뉴스는 어느 분야에서도 조회되고, category는 요청 분야
    body = call(api, "get", "/api/career/news?field_code=cloud_infra").json()
    assert body["count"] == 1 and body["field_code"] == "cloud_infra"
    item = body["items"][0]
    assert item["title"] == "생성형 AI 투자 확대" and item["category"] == "클라우드·인프라"
    assert item["field_codes"] == ["data_ai", "cloud_infra"] and item["categories"] == ["데이터·AI", "클라우드·인프라"]
    assert titles(call(api, "get", "/api/career/news?field_code=data_ai")) == ["생성형 AI 투자 확대"]

    # 화면 필드: Google 링크는 원문 URL로 표시하지 않음, 요약·키워드는 비어 있음
    assert item["link_url"] == "https://news.google.com/rss/articles/AI1" and item["link_type"] == "GOOGLE_NEWS_RSS"
    assert item["original_url"] is None and item["summary"] is None and item["keywords"] == []
    assert item["publisher"] == "예시신문" and len(item["published_at"]) == 10

    # 데이터가 없으면 빈 목록
    assert call(api, "get", "/api/career/news?field_code=mobile").json() == {
        "items": [], "count": 0, "field_code": "mobile", "days": 30, "limit": 100,
    }


def test_scrap_lifecycle_per_member(api):
    ai = db_rows("SELECT news_id FROM career_news WHERE title = '생성형 AI 투자 확대'")[0]["news_id"]

    assert call(api, "put", f"/api/career/news/{ai}/scrap").json() == {"news_id": ai, "scrapped_by_me": True}
    assert call(api, "put", f"/api/career/news/{ai}/scrap").json() == {"news_id": ai, "scrapped_by_me": True}  # 중복
    assert db_rows("SELECT member_id FROM career_news_scraps") == [{"member_id": 1}]

    def scrapped(member):
        items = call(api, "get", "/api/career/news", member).json()["items"]
        return {item["title"]: item["scrapped_by_me"] for item in items}

    assert scrapped(1)["생성형 AI 투자 확대"] is True and scrapped(1)["랜섬웨어 대응 강화"] is False
    assert scrapped(2)["생성형 AI 투자 확대"] is False  # 회원별

    assert call(api, "delete", f"/api/career/news/{ai}/scrap").json() == {"news_id": ai, "scrapped_by_me": False}
    assert call(api, "delete", f"/api/career/news/{ai}/scrap").json() == {"news_id": ai, "scrapped_by_me": False}  # 중복 해제
    assert db_rows("SELECT * FROM career_news_scraps") == []


def test_scrap_404_and_hidden_rules(api):
    assert call(api, "put", "/api/career/news/999999/scrap").status_code == 404
    assert call(api, "delete", "/api/career/news/999999/scrap").status_code == 404

    hidden = db_rows("SELECT news_id FROM career_news WHERE hidden_at IS NOT NULL")[0]["news_id"]
    assert call(api, "put", f"/api/career/news/{hidden}/scrap").status_code == 404  # 숨긴 뉴스는 새로 스크랩 불가
    # 숨기기 전에 스크랩한 회원은 해제할 수 있다
    with admin_connection() as conn, conn.cursor() as cursor:
        cursor.execute(f"SET search_path = {SCHEMA}")
        cursor.execute("INSERT INTO career_news_scraps (news_id, member_id) VALUES (%s, 2)", (hidden,))
    response = call(api, "delete", f"/api/career/news/{hidden}/scrap", member=2)
    assert response.status_code == 200 and response.json()["scrapped_by_me"] is False


def test_auth_required(api):
    assert api.get("/api/career/news").status_code == 401  # 헤더 없음
    assert call(api, "get", "/api/career/news", member=999).status_code == 401  # 없는 회원
    assert call(api, "put", "/api/career/news/1/scrap", member=999).status_code == 401


def test_scrap_survives_reimport(api):
    ai = db_rows("SELECT news_id FROM career_news WHERE title = '생성형 AI 투자 확대'")[0]["news_id"]
    assert call(api, "put", f"/api/career/news/{ai}/scrap").status_code == 200

    # 재수집: 같은 링크·바뀐 제목·분야 추가, 다른 기사는 수집 결과에서 빠짐
    recollected = [article("AI1", "생성형 AI 투자 확대 (종합)", {"data_ai", "security"}, NOW - timedelta(hours=1))]
    with admin_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(f"SET search_path = {SCHEMA}")
        importer.import_articles(cursor, recollected, NOW + timedelta(hours=3))

    items = {item["title"]: item for item in call(api, "get", "/api/career/news").json()["items"]}
    assert items["생성형 AI 투자 확대 (종합)"]["id"] == ai and items["생성형 AI 투자 확대 (종합)"]["scrapped_by_me"] is True
    assert items["생성형 AI 투자 확대 (종합)"]["field_codes"] == ["data_ai", "cloud_infra", "security"]
    assert "랜섬웨어 대응 강화" in items  # 이번 수집에 없어도 남음
    assert db_rows("SELECT news_id, member_id FROM career_news_scraps") == [{"news_id": ai, "member_id": 1}]


def test_my_news_scraps_and_detail_for_mypage(api):
    """마이페이지 내 스크랩용 뉴스 목록·상세: 스크랩 최신순, 회원 격리, 숨긴 뉴스 표시·해제, 기간 제한 없는 상세."""
    ids = {row["title"]: row["news_id"] for row in db_rows("SELECT news_id, title FROM career_news")}
    hidden, old = ids["숨긴 모바일 기사"], ids["오래된 프론트엔드 기사"]
    ai, sec = ids["생성형 AI 투자 확대"], ids["랜섬웨어 대응 강화"]
    with admin_connection() as conn, conn.cursor() as cursor:
        cursor.execute(f"SET search_path = {SCHEMA}")
        cursor.execute(
            """INSERT INTO career_news_scraps (news_id, member_id, created_at) VALUES
               (%s, 1, '2026-11-01 09:00:00'), (%s, 1, '2026-11-01 10:30:00.123456'),
               (%s, 1, '2026-10-31 23:59:59'), (%s, 2, '2026-11-01 12:00:00')""",
            (ai, hidden, old, sec),
        )

    # 스크랩 최신순, 숨긴 뉴스 포함 (is_hidden), 다른 회원 스크랩 제외
    body = call(api, "get", "/api/career/news/scraps").json()
    assert [item["news_id"] for item in body["items"]] == [hidden, ai, old]
    assert body["count"] == 3 and body["limit"] == 20
    first = body["items"][0]
    assert first["item_type"] == "NEWS" and first["is_hidden"] is True and first["category"] == "모바일 개발"
    assert first["scrapped_at"] == "2026-11-01T10:30:00.123456"  # DB 값 그대로, 시간대 없는 ISO
    assert body["items"][1]["scrapped_at"] == "2026-11-01T09:00:00"
    assert [item["news_id"] for item in call(api, "get", "/api/career/news/scraps", member=2).json()["items"]] == [sec]
    assert [item["news_id"] for item in call(api, "get", "/api/career/news/scraps?limit=1").json()["items"]] == [hidden]

    # 상세: 30일 지난 뉴스도 열림, 숨긴 뉴스는 스크랩한 회원에게만 (is_hidden)
    detail = call(api, "get", f"/api/career/news/{old}").json()
    assert detail["title"] == "오래된 프론트엔드 기사" and detail["is_hidden"] is False and detail["scrapped_by_me"] is True
    hidden_detail = call(api, "get", f"/api/career/news/{hidden}")
    assert hidden_detail.status_code == 200 and hidden_detail.json()["is_hidden"] is True
    assert call(api, "get", f"/api/career/news/{hidden}", member=2).status_code == 404
    assert call(api, "get", "/api/career/news/999999").status_code == 404
    assert call(api, "get", f"/api/career/news/{sec}", member=1).json()["scrapped_by_me"] is False

    # 숨긴 뉴스 스크랩 해제 → 목록·상세에서 사라짐, 다시 스크랩은 불가
    assert call(api, "delete", f"/api/career/news/{hidden}/scrap").json()["scrapped_by_me"] is False
    assert [item["news_id"] for item in call(api, "get", "/api/career/news/scraps").json()["items"]] == [ai, old]
    assert call(api, "get", f"/api/career/news/{hidden}").status_code == 404
    assert call(api, "put", f"/api/career/news/{hidden}/scrap").status_code == 404
    # 일반 브리핑 목록에는 계속 숨긴 뉴스가 없음
    assert "숨긴 모바일 기사" not in titles(call(api, "get", "/api/career/news?days=90"))
    assert call(api, "get", "/api/career/news/scraps", member=999).status_code == 401
