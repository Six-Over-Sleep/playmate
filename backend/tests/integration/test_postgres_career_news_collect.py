"""커리어 브리핑 뉴스 수집 스크립트(collect_career_news.py)의 저장을 실제 PostgreSQL에서 검증한다.

한 분야 수집이 실패해도 그 분야의 기존 뉴스·스크랩·숨김이 남는지, 저장 중 오류가 나면 전부 되돌리는지 확인한다.
일회용 DB 주소를 PLAYMATE_CAREER_NEWS_TEST_DB_URL로 줄 때만 실행한다. (공용 DB 사용 금지)
전용 스키마 career_news_collect_test를 만들고 테스트가 끝나면 삭제한다.
"""
import importlib.util
import os
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import psycopg2
from psycopg2.extras import RealDictCursor
import pytest


DB_URL = os.getenv("PLAYMATE_CAREER_NEWS_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="일회용 PostgreSQL에서만 실행")

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "database" / "sql" / "017_career_news.sql"
SPEC = importlib.util.spec_from_file_location(
    "collect_career_news", ROOT / "database" / "scripts" / "collect_career_news.py"
)
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)

SCHEMA = "career_news_collect_test"
CATEGORIES = {
    name: {"code": code, "queries": [f"{code}-q"], "title_keywords": [name]}
    for name, code in collector.FIELD_CODES.items()
}


@pytest.fixture
def connection():
    if urlsplit(DB_URL).hostname not in ("127.0.0.1", "localhost"):
        pytest.skip("로컬 일회용 DB(127.0.0.1/localhost)에서만 실행")
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    with conn.cursor() as cursor:
        cursor.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        cursor.execute(f"CREATE SCHEMA {SCHEMA}")
        cursor.execute(f"SET search_path = {SCHEMA}")
        cursor.execute("CREATE TABLE members (member_id BIGINT PRIMARY KEY, nickname VARCHAR(50))")
        cursor.execute("INSERT INTO members VALUES (1, '민혁')")
        cursor.execute(MIGRATION.read_text(encoding="utf-8"))
    conn.autocommit = False
    yield conn
    conn.rollback()
    conn.autocommit = True
    with conn.cursor() as cursor:
        cursor.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    conn.close()


def cursor_factory(conn):
    """db_cursor(commit=True)처럼 성공하면 커밋, 오류가 나면 되돌린다."""
    @contextmanager
    def factory():
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
    return factory


def collect_with(articles_by_code, failing=()):
    """분야 코드별 (토큰, 제목) 목록을 돌려주는 수집기. failing 분야는 네트워크 오류를 낸다."""
    def collect(query, title_keywords, days, session=None):
        code = query.removesuffix("-q")
        if code in failing:
            raise ConnectionError("RSS 연결 실패")
        return [
            {"title": title, "source": "테스트신문", "published": "2026-10-30T00:00:00+00:00",
             "link": f"https://news.google.com/rss/articles/{token}?oc=5"}
            for token, title in articles_by_code.get(code, [])
        ]
    return collect


def run(conn, collect, logs=None):
    return collector.main(["--apply", "--pause", "0"], collector=(CATEGORIES, collect),
                          cursor_factory=cursor_factory(conn), log=(logs.append if logs is not None else lambda _: None))


def snapshot(conn):
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(
            """SELECT n.news_id, n.title, n.hidden_at, n.last_seen_at,
                      ARRAY(SELECT field_code FROM career_news_fields f WHERE f.news_id = n.news_id ORDER BY 1) AS fields
               FROM career_news n ORDER BY n.news_id"""
        )
        news = {row["title"]: row for row in cursor.fetchall()}
        cursor.execute("SELECT news_id, member_id FROM career_news_scraps ORDER BY 1")
        scraps = [tuple(row.values()) for row in cursor.fetchall()]
    conn.commit()
    return news, scraps


FIRST = {
    "data_ai": [("AI1", "AI 반도체 투자 확대")],
    "security": [("SEC1", "랜섬웨어 피해 급증"), ("SEC2", "제로트러스트 도입 확산")],
    "cloud_infra": [("CLD1", "데이터센터 전력 수요")],
}


def test_failed_field_keeps_news_scraps_and_hidden(connection):
    assert run(connection, collect_with(FIRST)) == collector.EXIT_OK
    news, _ = snapshot(connection)
    with connection.cursor() as cursor:
        cursor.execute("INSERT INTO career_news_scraps (news_id, member_id) VALUES (%s, 1)",
                       (news["랜섬웨어 피해 급증"]["news_id"],))
        cursor.execute("UPDATE career_news SET hidden_at = now() WHERE news_id = %s",
                       (news["제로트러스트 도입 확산"]["news_id"],))
    connection.commit()
    before, scraps_before = snapshot(connection)

    second = {"data_ai": [("AI1", "AI 반도체 투자 확대"), ("AI2", "LLM 서비스 경쟁")], "cloud_infra": []}
    logs = []
    assert run(connection, collect_with(second, failing={"security"}), logs) == collector.EXIT_PARTIAL
    after, scraps_after = snapshot(connection)

    for title in ("랜섬웨어 피해 급증", "제로트러스트 도입 확산", "데이터센터 전력 수요"):
        assert after[title]["news_id"] == before[title]["news_id"]
        assert after[title]["fields"] == before[title]["fields"]
        assert after[title]["last_seen_at"] == before[title]["last_seen_at"]  # 이번에 수집되지 않음
    assert after["제로트러스트 도입 확산"]["hidden_at"] is not None
    assert scraps_after == scraps_before
    assert after["AI 반도체 투자 확대"]["news_id"] == before["AI 반도체 투자 확대"]["news_id"]
    assert after["AI 반도체 투자 확대"]["last_seen_at"] > before["AI 반도체 투자 확대"]["last_seen_at"]
    assert after["LLM 서비스 경쟁"]["fields"] == ["data_ai"]
    assert len(after) == 5
    assert any("security: 뉴스 2건" in line for line in logs)
    assert any("수집 실패 분야(기존 뉴스 유지): 정보보안" in line for line in logs)


def test_all_fields_failing_changes_nothing(connection):
    run(connection, collect_with(FIRST))
    before = snapshot(connection)
    assert run(connection, collect_with({}, failing=set(collector.FIELD_CODES.values()))) == collector.EXIT_NOTHING_SAVED
    assert snapshot(connection) == before


def test_error_while_saving_rolls_back_whole_run(connection, monkeypatch):
    run(connection, collect_with(FIRST))
    before = snapshot(connection)

    def broken(cursor):
        raise RuntimeError("저장 중 오류")

    monkeypatch.setattr(collector, "field_freshness", broken)  # import_articles 다음에 실패
    with pytest.raises(RuntimeError):
        run(connection, collect_with({"data_ai": [("AI9", "새 AI 기사")], "security": [("SEC1", "랜섬웨어 피해 급증")]}))
    assert snapshot(connection) == before


def test_same_article_in_two_fields_and_changed_link(connection):
    run(connection, collect_with({"data_ai": [("X1", "AI 보안 위협")], "security": [("X1", "AI 보안 위협")]}))
    news, _ = snapshot(connection)
    assert news["AI 보안 위협"]["fields"] == ["data_ai", "security"]

    # 다음 수집에서 Google 링크 토큰이 바뀌어도 언론사 + 제목이 같으면 같은 뉴스로 본다
    run(connection, collect_with({"backend": [("X2", "AI 보안 위협")]}))
    after, _ = snapshot(connection)
    assert len(after) == 1
    assert after["AI 보안 위협"]["news_id"] == news["AI 보안 위협"]["news_id"]
    # 제목으로 찾은 기존 뉴스에도 새 분야를 추가한다
    assert after["AI 보안 위협"]["fields"] == ["backend", "data_ai", "security"]
