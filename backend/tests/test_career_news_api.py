"""커리어 브리핑 뉴스 조회·스크랩 API를 DB 없이 확인한다 (Issue #74).

응답 변환(화면 필드·한국 날짜·링크 표시), 입력 검증(422), 인증(401), 404 규칙을 검사한다.
실제 SQL·제약조건은 tests/integration/test_postgres_career_news_api.py에서 일회용 DB로 확인한다.
"""
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app.core.auth import get_current_member_id
from app.main import app
from app.schemas.career_news import CareerNewsItem, CareerNewsListResponse, CareerNewsMyScrapListResponse
from app.services import career_news_service as service


GOOGLE = "https://news.google.com/rss/articles/CBMiTOKEN"
NOW = datetime(2026, 10, 30, 3, 0, tzinfo=timezone.utc)


def news_row(news_id=1, published=datetime(2026, 10, 28, 16, 0), fields=("security", "data_ai"), scrapped=False):
    return {
        "news_id": news_id,
        "title": "생성형 AI 보안 위협 증가",
        "source_name": "예시신문",
        "link_url": GOOGLE,
        "link_type": "GOOGLE_NEWS_RSS",
        "published_at": published,
        "field_codes": list(fields),
        "scrapped_by_me": scrapped,
    }


class FakeCursor:
    """repository 함수를 대신해 결과를 돌려주고 호출을 기록한다."""

    def __init__(self):
        self.calls = []


def fake_db(monkeypatch, commits):
    @contextmanager
    def db_cursor(**kwargs):
        commits.append(kwargs)
        yield FakeCursor()

    monkeypatch.setattr(service, "db_cursor", db_cursor)


# ---------------------------------------------------------------------------
# 응답 변환
# ---------------------------------------------------------------------------
def test_item_matches_react_fields_without_fake_summary():
    item = service._to_item(news_row(), None)
    CareerNewsItem.model_validate(item)
    assert item["id"] == item["news_id"] == 1
    assert item["published_at"] == "2026-10-29"  # UTC 16:00 → 한국 날짜
    assert item["published_datetime"] == datetime(2026, 10, 28, 16, 0, tzinfo=timezone.utc)
    assert item["field_codes"] == ["data_ai", "security"]  # 분야 표시 순서
    assert item["categories"] == ["데이터·AI", "정보보안"] and item["category"] == "데이터·AI"
    assert item["publisher"] == "예시신문"
    # Google News 링크는 언론사 원문(original_url)으로 표시하지 않는다
    assert item["link_url"] == GOOGLE and item["link_type"] == "GOOGLE_NEWS_RSS" and item["original_url"] is None
    # 요약·분류는 만들지 않는다. keywords는 화면이 .slice를 호출하므로 빈 배열
    assert item["summary"] is None and item["news_type"] is None and item["why_it_matters"] is None
    assert item["keywords"] == [] and item["study_keywords"] == []


def test_item_uses_requested_field_and_handles_missing_values():
    row = news_row(published=None)
    row["source_name"] = None
    item = service._to_item(row, "security")
    assert item["category"] == "정보보안" and item["field_code"] == "security"
    assert item["published_at"] is None and item["published_datetime"] is None
    assert item["publisher"] == ""


def test_list_news_passes_utc_since_and_returns_empty_list(monkeypatch):
    commits, seen = [], {}
    fake_db(monkeypatch, commits)

    def list_news(cursor, member_id, since, limit, field_code):
        seen.update(member_id=member_id, since=since, limit=limit, field_code=field_code)
        return []

    monkeypatch.setattr(service.career_news_repository, "list_news", list_news)
    result = service.list_news(7, "backend", 30, 50, now=NOW)
    assert result == {"items": [], "count": 0, "field_code": "backend", "days": 30, "limit": 50}
    assert seen == {"member_id": 7, "since": datetime(2026, 9, 30, 3, 0), "limit": 50, "field_code": "backend"}
    assert commits == [{"read_only": True}]


def test_list_news_skips_rows_without_field(monkeypatch):
    fake_db(monkeypatch, [])
    monkeypatch.setattr(service.career_news_repository, "list_news",
                        lambda *args: [news_row(1), news_row(2, fields=())])
    result = service.list_news(1, None, 30, 100, now=NOW)
    assert [item["id"] for item in result["items"]] == [1] and result["count"] == 1
    CareerNewsListResponse.model_validate(result)


# ---------------------------------------------------------------------------
# 스크랩 404 규칙
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("state", [None, {"news_id": 3, "is_hidden": True}])
def test_scrap_missing_or_hidden_news_is_404(monkeypatch, state):
    fake_db(monkeypatch, [])
    monkeypatch.setattr(service.career_news_repository, "get_news_state", lambda cursor, news_id: state)
    monkeypatch.setattr(service.career_news_repository, "scrap_news",
                        lambda *args: pytest.fail("없는·숨긴 뉴스는 저장하지 않음"))
    with pytest.raises(HTTPException) as error:
        service.scrap_news(3, 1)
    assert error.value.status_code == 404


def test_unscrap_hidden_news_is_allowed_but_missing_is_404(monkeypatch):
    commits = []
    fake_db(monkeypatch, commits)
    deleted = []
    monkeypatch.setattr(service.career_news_repository, "unscrap_news", lambda cursor, n, m: deleted.append((n, m)))
    monkeypatch.setattr(service.career_news_repository, "get_news_scrap",
                        lambda cursor, n, m: {"news_id": n, "scrapped_by_me": False})

    monkeypatch.setattr(service.career_news_repository, "get_news_state",
                        lambda cursor, news_id: {"news_id": news_id, "is_hidden": True})
    assert service.unscrap_news(3, 1) == {"news_id": 3, "scrapped_by_me": False}
    assert deleted == [(3, 1)] and commits == [{"commit": True}]

    monkeypatch.setattr(service.career_news_repository, "get_news_state", lambda cursor, news_id: None)
    with pytest.raises(HTTPException) as error:
        service.unscrap_news(4, 1)
    assert error.value.status_code == 404


# ---------------------------------------------------------------------------
# HTTP: 인증·입력 검증·응답 형식
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.mark.parametrize("method,path", [
    ("get", "/api/career/news"),
    ("put", "/api/career/news/1/scrap"),
    ("delete", "/api/career/news/1/scrap"),
])
def test_login_required(monkeypatch, client, method, path):
    monkeypatch.setenv("APP_ENV", "production")  # 세션 없음 → DB 조회 전에 401
    assert getattr(client, method)(path).status_code == 401


@pytest.mark.parametrize("query", [
    "field_code=AI", "field_code=", "days=0", "days=91", "limit=0", "limit=301", "days=abc",
])
def test_invalid_list_query_is_422(client, query):
    app.dependency_overrides[get_current_member_id] = lambda: 1
    assert client.get(f"/api/career/news?{query}").status_code == 422


def test_invalid_news_id_is_422(client):
    app.dependency_overrides[get_current_member_id] = lambda: 1
    assert client.put("/api/career/news/abc/scrap").status_code == 422


def test_http_list_and_scrap_forward_to_service(monkeypatch, client):
    app.dependency_overrides[get_current_member_id] = lambda: 5
    seen = {}

    def list_news(member_id, field_code, days, limit):
        seen["list"] = (member_id, field_code, days, limit)
        item = service._to_item(news_row(scrapped=True), field_code)
        return {"items": [item], "count": 1, "field_code": field_code, "days": days, "limit": limit}

    monkeypatch.setattr(service, "list_news", list_news)
    monkeypatch.setattr(service, "scrap_news", lambda n, m: {"news_id": n, "scrapped_by_me": True})
    monkeypatch.setattr(service, "unscrap_news", lambda n, m: {"news_id": n, "scrapped_by_me": False})

    response = client.get("/api/career/news?field_code=security&days=7&limit=20")
    assert response.status_code == 200 and seen["list"] == (5, "security", 7, 20)
    body = response.json()
    item = body["items"][0]
    assert body["count"] == 1 and item["category"] == "정보보안" and item["scrapped_by_me"] is True
    for key in ("summary", "keywords", "published_at", "original_url", "link_url", "link_type", "publisher"):
        assert key in item
    assert item["keywords"] == [] and item["original_url"] is None

    assert client.get("/api/career/news").status_code == 200
    assert seen["list"] == (5, None, 30, 100)  # 기본값: 전체 분야, 30일, 100건
    assert client.put("/api/career/news/9/scrap").json() == {"news_id": 9, "scrapped_by_me": True}
    assert client.delete("/api/career/news/9/scrap").json() == {"news_id": 9, "scrapped_by_me": False}


def test_existing_career_scrap_routes_are_unchanged():
    paths = app.openapi()["paths"]
    assert {"put", "delete"} <= set(paths["/api/career/posts/{post_id}/scrap"])  # 기존 게시글 스크랩 그대로
    assert {"put", "delete"} <= set(paths["/api/career/news/{news_id}/scrap"])
    assert "get" in paths["/api/career/news"]


# ---------------------------------------------------------------------------
# 뉴스 상세·마이페이지 뉴스 스크랩 (마이페이지 통합)
# ---------------------------------------------------------------------------
def detail_row(hidden=False, scrapped=False, fields=("security",)):
    return {**news_row(fields=fields, scrapped=scrapped), "is_hidden": hidden}


@pytest.mark.parametrize("row", [
    None,                                    # 없는 뉴스
    detail_row(hidden=True, scrapped=False),  # 숨긴 뉴스를 스크랩하지 않은 회원
    detail_row(fields=()),                   # 분야 없는 뉴스 (목록과 같이 제외)
])
def test_detail_404_rules(monkeypatch, row):
    fake_db(monkeypatch, [])
    monkeypatch.setattr(service.career_news_repository, "get_news", lambda cursor, n, m: row)
    with pytest.raises(HTTPException) as error:
        service.get_news(1, 1)
    assert error.value.status_code == 404


def test_detail_shows_hidden_news_only_to_scrapper(monkeypatch):
    commits, seen = [], []
    fake_db(monkeypatch, commits)

    def get_news(cursor, news_id, member_id):
        seen.append((news_id, member_id))
        return detail_row(hidden=True, scrapped=True)

    monkeypatch.setattr(service.career_news_repository, "get_news", get_news)
    item = service.get_news(1, 7)
    assert seen == [(1, 7)] and commits == [{"read_only": True}]
    assert item["is_hidden"] is True and item["scrapped_by_me"] is True
    assert item["original_url"] is None and item["link_type"] == "GOOGLE_NEWS_RSS"


def test_my_scraps_items_keep_scrapped_at_and_mark_hidden(monkeypatch):
    commits, seen = [], {}
    fake_db(monkeypatch, commits)
    scrapped = datetime(2026, 11, 1, 21, 5, 30, 123456)  # DB 기본값 그대로 (시간대 없음)

    def list_member_scraps(cursor, member_id, limit):
        seen.update(member_id=member_id, limit=limit)
        return [
            {"news_id": 4, "title": "숨긴 뉴스", "source_name": None, "published_at": None, "is_hidden": True,
             "field_codes": [], "scrapped_at": scrapped},
            {"news_id": 3, "title": "보안 뉴스", "source_name": "예시신문", "published_at": datetime(2026, 10, 28, 16, 0),
             "is_hidden": False, "field_codes": ["security", "data_ai"], "scrapped_at": datetime(2026, 11, 1, 9, 0)},
        ]

    monkeypatch.setattr(service.career_news_repository, "list_member_scraps", list_member_scraps)
    result = service.list_my_scraps(7, 20)
    CareerNewsMyScrapListResponse.model_validate(result)
    assert seen == {"member_id": 7, "limit": 20} and commits == [{"read_only": True}]
    hidden, normal = result["items"]
    assert hidden == {"item_type": "NEWS", "news_id": 4, "title": "숨긴 뉴스", "publisher": "", "category": "",
                      "field_code": None, "published_at": None, "scrapped_at": scrapped, "is_hidden": True}
    assert normal["category"] == "데이터·AI" and normal["published_at"] == "2026-10-29"
    assert result["count"] == 2 and result["limit"] == 20


def test_http_scraps_route_is_not_a_news_id(monkeypatch, client):
    app.dependency_overrides[get_current_member_id] = lambda: 5
    seen = {}

    def list_my_scraps(member_id, limit):
        seen["scraps"] = (member_id, limit)
        return {"items": [{"item_type": "NEWS", "news_id": 3, "title": "t", "publisher": "", "category": "정보보안",
                           "field_code": "security", "published_at": None,
                           "scrapped_at": datetime(2026, 11, 1, 21, 5, 30, 123456), "is_hidden": False}],
                "count": 1, "limit": limit}

    def get_news(news_id, member_id):
        seen["detail"] = (news_id, member_id)
        return {**service._to_item(news_row(news_id), None), "is_hidden": False}

    monkeypatch.setattr(service, "list_my_scraps", list_my_scraps)
    monkeypatch.setattr(service, "get_news", get_news)

    response = client.get("/api/career/news/scraps")
    assert response.status_code == 200 and seen["scraps"] == (5, 20) and "detail" not in seen
    # 게시글 스크랩(MyScrapResponse)과 같은 직렬화: 시간대 없는 ISO 문자열
    assert response.json()["items"][0]["scrapped_at"] == "2026-11-01T21:05:30.123456"

    assert client.get("/api/career/news/12").json()["news_id"] == 12 and seen["detail"] == (12, 5)
    assert client.get("/api/career/news/abc").status_code == 422
    for query in ("limit=0", "limit=51"):
        assert client.get(f"/api/career/news/scraps?{query}").status_code == 422


@pytest.mark.parametrize("path", ["/api/career/news/scraps", "/api/career/news/1"])
def test_new_routes_require_login(monkeypatch, client, path):
    monkeypatch.setenv("APP_ENV", "production")
    assert client.get(path).status_code == 401


def test_mypage_scraps_contract_is_unchanged():
    """기존 GET /api/mypage/scraps와 MyScrapResponse는 그대로다 (뉴스는 별도 API)."""
    from app.schemas.mypage import MyScrapResponse

    assert set(MyScrapResponse.model_fields) == {
        "post_id", "board_id", "post_type", "title", "scrapped_at", "career_category", "recruit_id",
    }
    operation = app.openapi()["paths"]["/api/mypage/scraps"]["get"]
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["type"] == "array" and schema["items"]["$ref"].endswith("/MyScrapResponse")
    assert [p["name"] for p in operation.get("parameters", []) if p["in"] != "header"] == []
