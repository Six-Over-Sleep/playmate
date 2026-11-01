"""커리어 브리핑 뉴스 테이블(017_career_news.sql)과 가져오기 UPSERT를 실제 PostgreSQL에서 검증한다.

일회용 DB 주소를 PLAYMATE_CAREER_NEWS_TEST_DB_URL로 줄 때만 실행한다. (공용 DB 사용 금지)
예) PLAYMATE_CAREER_NEWS_TEST_DB_URL=postgresql://postgres:test@127.0.0.1:55437/pm
전용 스키마 career_news_test를 만들고 테스트가 끝나면 삭제한다. 다른 스키마의 테이블은 건드리지 않는다.
"""
import importlib.util
import os
import sqlite3
from datetime import datetime
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
    "import_career_news", ROOT / "database" / "scripts" / "import_career_news.py"
)
importer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(importer)

SCHEMA = "career_news_test"
T1 = datetime(2026, 10, 29, 3, 0)
T2 = datetime(2026, 10, 29, 6, 0)
T3 = datetime(2026, 10, 29, 9, 0)


def link(token):
    return f"https://news.google.com/rss/articles/{token}?oc=5"


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
        cursor.execute("INSERT INTO members VALUES (1, '민혁'), (2, '효원')")
        cursor.execute(MIGRATION.read_text(encoding="utf-8"))
    conn.autocommit = False
    yield conn
    conn.rollback()
    conn.autocommit = True
    with conn.cursor() as cursor:
        cursor.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    conn.close()


def make_sqlite(path: Path, rows) -> Path:
    """크롤러 한 번의 수집 결과. 새 파일이라 SQLite news_id는 매번 1부터 다시 매겨진다."""
    sqlite = sqlite3.connect(path)
    sqlite.execute(
        """CREATE TABLE news (
               news_id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL, title TEXT NOT NULL,
               source TEXT NOT NULL DEFAULT '', link TEXT NOT NULL, published TEXT,
               collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE (category, title, source))"""
    )
    sqlite.executemany("INSERT INTO news (category, title, source, link, published) VALUES (?, ?, ?, ?, ?)", rows)
    sqlite.commit()
    sqlite.close()
    return path


def run_import(conn, path, seen_at):
    articles, _ = importer.read_sqlite(path)
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        report = importer.import_articles(cursor, articles, seen_at)
    conn.commit()
    return report


def rows(conn, sql, params=()):
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def news_by_title(conn):
    return {row["title"]: row for row in rows(conn, "SELECT * FROM career_news")}


def fields_of(conn, news_id):
    return {r["field_code"] for r in rows(conn, "SELECT field_code FROM career_news_fields WHERE news_id = %s", (news_id,))}


def expect_error(conn, sql, params, error):
    with pytest.raises(error):
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
    conn.rollback()


def test_constraints(connection):
    constraints = {
        (r["table_name"], r["constraint_type"])
        for r in rows(connection, """
            SELECT table_name, constraint_type FROM information_schema.table_constraints
            WHERE table_schema = %s""", (SCHEMA,))
    }
    assert ("career_news", "PRIMARY KEY") in constraints and ("career_news", "UNIQUE") in constraints
    assert ("career_news_fields", "PRIMARY KEY") in constraints and ("career_news_fields", "FOREIGN KEY") in constraints
    assert ("career_news_scraps", "PRIMARY KEY") in constraints and ("career_news_scraps", "FOREIGN KEY") in constraints

    key = "a" * 64
    insert_news = """INSERT INTO career_news (link_key, link_url, link_type, title)
                     VALUES (%s, %s, %s, %s) RETURNING news_id"""
    with connection.cursor() as cursor:
        cursor.execute(insert_news, (key, link("A"), "GOOGLE_NEWS_RSS", "기사"))
        news_id = cursor.fetchone()[0]
    connection.commit()

    expect_error(connection, insert_news, (key, link("B"), "GOOGLE_NEWS_RSS", "다른 기사"), psycopg2.errors.UniqueViolation)
    expect_error(connection, insert_news, ("b" * 64, "javascript:alert(1)", "UNVERIFIED", "x"), psycopg2.errors.CheckViolation)
    expect_error(connection, insert_news, ("c" * 64, link("C"), "PUBLISHER", "x"), psycopg2.errors.CheckViolation)
    expect_error(connection, insert_news, ("d" * 64, link("D"), "GOOGLE_NEWS_RSS", "  "), psycopg2.errors.CheckViolation)
    expect_error(connection, insert_news, ("NOT-A-HASH", link("E"), "GOOGLE_NEWS_RSS", "x"), psycopg2.errors.CheckViolation)

    fields = "INSERT INTO career_news_fields (news_id, field_code) VALUES (%s, %s)"
    expect_error(connection, fields, (news_id, "AI"), psycopg2.errors.CheckViolation)
    expect_error(connection, fields, (999, "data_ai"), psycopg2.errors.ForeignKeyViolation)
    with connection.cursor() as cursor:
        cursor.execute(fields, (news_id, "data_ai"))
    connection.commit()
    expect_error(connection, fields, (news_id, "data_ai"), psycopg2.errors.UniqueViolation)

    scraps = "INSERT INTO career_news_scraps (news_id, member_id) VALUES (%s, %s)"
    expect_error(connection, scraps, (999, 1), psycopg2.errors.ForeignKeyViolation)
    expect_error(connection, scraps, (news_id, 999), psycopg2.errors.ForeignKeyViolation)
    with connection.cursor() as cursor:
        cursor.execute(scraps, (news_id, 1))
    connection.commit()
    expect_error(connection, scraps, (news_id, 1), psycopg2.errors.UniqueViolation)
    # 스크랩된 뉴스는 지울 수 없다 (hidden_at으로만 숨김)
    expect_error(connection, "DELETE FROM career_news WHERE news_id = %s", (news_id,), psycopg2.errors.ForeignKeyViolation)


def test_reimport_keeps_news_id_merges_fields_and_preserves_scraps(connection, tmp_path):
    first = make_sqlite(tmp_path / "run1.db", [
        ("데이터·AI", "생성형 AI 투자 확대", "예시신문", link("AI1"), "2026-10-29T00:00:00+00:00"),
        ("클라우드·인프라", "생성형 AI 투자 확대", "예시신문", link("AI1"), "2026-10-29T00:00:00+00:00"),
        ("정보보안", "랜섬웨어 대응 강화", "보안일보", link("SEC1"), "2026-10-28T12:00:00+00:00"),
        ("백엔드·서버", "스프링 부트 업데이트", "개발신문", link("BE1"), None),
    ])
    report = run_import(connection, first, T1)
    assert (report.inserted, report.updated, report.field_links_added) == (3, 0, 4)

    news = news_by_title(connection)
    ai, sec, be = news["생성형 AI 투자 확대"], news["랜섬웨어 대응 강화"], news["스프링 부트 업데이트"]
    assert fields_of(connection, ai["news_id"]) == {"data_ai", "cloud_infra"}  # 한 뉴스, 여러 분야
    assert ai["link_url"] == "https://news.google.com/rss/articles/AI1" and ai["link_type"] == "GOOGLE_NEWS_RSS"
    assert ai["published_at"] == datetime(2026, 10, 29) and be["published_at"] is None
    assert ai["first_seen_at"] == ai["last_seen_at"] == T1

    with connection.cursor() as cursor:
        cursor.execute("INSERT INTO career_news_scraps (news_id, member_id) VALUES (%s, 1), (%s, 2)",
                       (sec["news_id"], ai["news_id"]))
        cursor.execute("UPDATE career_news SET hidden_at = %s WHERE news_id = %s", (T1, be["news_id"]))
    connection.commit()

    # 재수집: SQLite news_id가 새로 매겨지고, 제목이 바뀌고, 분야가 추가되고, 보안 기사는 사라짐
    second = make_sqlite(tmp_path / "run2.db", [
        ("모바일 개발", "새 모바일 기사", "앱신문", link("MOB1"), None),
        ("데이터·AI", "생성형 AI 투자 확대 (종합)", "예시신문", link("AI1"), None),
        ("QA·테스트", "생성형 AI 투자 확대 (종합)", "예시신문", link("AI1"), None),
        ("백엔드·서버", "스프링 부트 업데이트", "개발신문", link("BE1"), "2026-10-29T05:00:00+00:00"),
    ])
    report = run_import(connection, second, T2)
    assert (report.inserted, report.updated) == (1, 2)

    news = news_by_title(connection)
    ai2 = news["생성형 AI 투자 확대 (종합)"]
    assert ai2["news_id"] == ai["news_id"]  # 같은 링크 → news_id 유지
    assert ai2["published_at"] == datetime(2026, 10, 29)  # 새 값이 없으면 기존 발행일 유지
    assert (ai2["first_seen_at"], ai2["last_seen_at"]) == (T1, T2)
    assert fields_of(connection, ai["news_id"]) == {"data_ai", "cloud_infra", "qa_test"}  # 기존 분야 유지 + 추가
    assert news["랜섬웨어 대응 강화"]["last_seen_at"] == T1  # 이번 수집에 없는 뉴스도 남음
    assert news["스프링 부트 업데이트"]["hidden_at"] == T1  # 운영자 숨김은 가져오기가 풀지 않음
    assert news["스프링 부트 업데이트"]["published_at"] == datetime(2026, 10, 29, 5)
    assert rows(connection, "SELECT news_id, member_id FROM career_news_scraps ORDER BY member_id") == [
        {"news_id": sec["news_id"], "member_id": 1}, {"news_id": ai["news_id"], "member_id": 2},
    ]
    assert len(news) == 4

    # 같은 파일을 다시 가져와도 행이 늘지 않는다
    report = run_import(connection, second, T3)
    assert (report.inserted, report.updated, report.field_links_added) == (0, 3, 0)
    assert rows(connection, "SELECT COUNT(*) AS n FROM career_news")[0]["n"] == 4


def test_changed_link_with_same_source_and_title_keeps_news(connection, tmp_path):
    run_import(connection, make_sqlite(tmp_path / "run1.db", [
        ("데이터·AI", "AI 반도체 수요 증가", "예시신문", link("OLDTOKEN"), None),
        ("데이터·AI", "AI 반도체 수요 증가", "다른신문", link("OTHER"), None),
    ]), T1)
    assert len(rows(connection, "SELECT * FROM career_news")) == 2  # 같은 제목이라도 언론사가 다르면 다른 뉴스

    original = rows(connection, "SELECT * FROM career_news WHERE source_name = '예시신문'")[0]
    report = run_import(connection, make_sqlite(tmp_path / "run2.db", [
        ("정보보안", "AI 반도체 수요 증가", "예시신문", link("NEWTOKEN"), "2026-10-29T01:00:00+00:00"),
    ]), T2)
    assert (report.inserted, report.matched_by_title) == (0, 1)
    after = rows(connection, "SELECT * FROM career_news WHERE source_name = '예시신문'")
    assert len(after) == 1 and after[0]["news_id"] == original["news_id"]
    assert after[0]["link_url"] == original["link_url"]  # 기존 링크·link_key 유지
    assert after[0]["last_seen_at"] == T2 and after[0]["published_at"] == datetime(2026, 10, 29, 1)
    assert fields_of(connection, original["news_id"]) == {"data_ai", "security"}


def test_old_it_news_crawler_format(connection, tmp_path):
    """it_news_crawler(RFC822 발행일, 옛 분류)는 직무 분야가 없는 행을 가져오지 않는다."""
    path = make_sqlite(tmp_path / "it.db", [
        ("AI", "옛 분류 기사", "예시신문", link("IT1"), "Tue, 06 Oct 2026 05:19:18 GMT"),
        ("정보보안", "직무 분야 기사", "예시신문", link("IT2"), "Tue, 06 Oct 2026 05:19:18 GMT"),
    ])
    articles, skipped = importer.read_sqlite(path)
    assert skipped == {"unknown_category": 1}
    run_import(connection, path, T1)
    news = news_by_title(connection)
    assert set(news) == {"직무 분야 기사"} and news["직무 분야 기사"]["published_at"] == datetime(2026, 10, 6, 5, 19, 18)


def test_import_never_deletes(connection, tmp_path):
    run_import(connection, make_sqlite(tmp_path / "run1.db", [
        ("데이터·AI", "기사 1", "예시신문", link("K1"), None),
        ("데이터·AI", "기사 2", "예시신문", link("K2"), None),
    ]), T1)
    report = run_import(connection, make_sqlite(tmp_path / "empty.db", []), T2)
    assert (report.inserted, report.updated) == (0, 0)
    assert rows(connection, "SELECT COUNT(*) AS n FROM career_news")[0]["n"] == 2
    assert rows(connection, "SELECT COUNT(*) AS n FROM career_news_fields")[0]["n"] == 2
