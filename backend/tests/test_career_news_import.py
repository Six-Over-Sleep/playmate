"""커리어 브리핑 뉴스 가져오기(database/scripts/import_career_news.py)를 DB 없이 확인한다.

링크 정규화·발행일 변환·SQLite 읽기(분야 병합, 건너뛰기)를 검사한다.
PostgreSQL UPSERT는 tests/integration/test_postgres_career_news.py에서 일회용 DB로 확인한다.
"""
import hashlib
import importlib.util
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "import_career_news", ROOT / "database" / "scripts" / "import_career_news.py"
)
importer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(importer)

GOOGLE = "https://news.google.com/rss/articles/CBMiTOKEN123?oc=5"


def make_sqlite(path: Path, rows) -> Path:
    """career_news_crawler src/database.py와 같은 news 테이블을 만든다."""
    connection = sqlite3.connect(path)
    connection.execute(
        """CREATE TABLE news (
               news_id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL, title TEXT NOT NULL,
               source TEXT NOT NULL DEFAULT '', link TEXT NOT NULL, published TEXT,
               collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE (category, title, source))"""
    )
    connection.executemany(
        "INSERT INTO news (category, title, source, link, published) VALUES (?, ?, ?, ?, ?)", rows
    )
    connection.commit()
    connection.close()
    return path


def test_normalize_google_news_link_drops_tracking_query():
    normalized = importer.normalize_link("  HTTPS://News.Google.com/rss/articles/CBMiTOKEN123?oc=5#top ")
    assert normalized == "https://news.google.com/rss/articles/CBMiTOKEN123"
    assert importer.normalize_link(GOOGLE) == normalized
    assert importer.link_type_of(normalized) == "GOOGLE_NEWS_RSS"
    assert importer.link_key_of(normalized) == hashlib.sha256(normalized.encode()).hexdigest()


def test_normalize_keeps_article_path_and_meaningful_query():
    normalized = importer.normalize_link("https://Example.com/News/View?id=7&utm_source=x&oc=5")
    assert normalized == "https://example.com/News/View?id=7&oc=5"  # 경로 대소문자 유지, oc는 Google만 제거
    assert importer.link_type_of(normalized) == "UNVERIFIED"  # 언론사 주소로 검증하지 않음
    assert importer.link_type_of("https://news.google.com/topics/abc") == "UNVERIFIED"


@pytest.mark.parametrize("value", [None, "", "ftp://example.com/a", "javascript:alert(1)", "news.google.com/rss", "https://"])
def test_invalid_links_are_rejected(value):
    assert importer.normalize_link(value) is None


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-10-29T00:30:00+00:00", datetime(2026, 10, 29, 0, 30)),         # career_news_crawler (UTC ISO)
        ("2026-10-29T09:30:00+09:00", datetime(2026, 10, 29, 0, 30)),         # 시간대가 다르면 UTC로
        ("Tue, 06 Oct 2026 05:19:18 GMT", datetime(2026, 10, 6, 5, 19, 18)),  # it_news_crawler (RFC822)
        ("2026-10-29 01:02:03", datetime(2026, 10, 29, 1, 2, 3)),             # 시간대 없음 → UTC로 간주
        ("", None),
        (None, None),
        ("not a date", None),
    ],
)
def test_parse_published(value, expected):
    assert importer.parse_published(value) == expected


def test_field_codes_accept_crawler_names_and_codes():
    assert importer.field_code_of("데이터·AI") == "data_ai"
    assert importer.field_code_of("security") == "security"
    assert importer.field_code_of("AI") is None  # it_news_crawler 옛 분류는 직무 분야가 아님
    assert set(importer.FIELD_CODES.values()) == {
        "data_ai", "backend", "frontend", "mobile", "cloud_infra", "security", "qa_test", "it_product"
    }


def test_read_sqlite_merges_fields_by_link_and_skips_bad_rows(tmp_path):
    path = make_sqlite(tmp_path / "career_news.db", [
        ("데이터·AI", "생성형 AI 투자 확대", "예시신문", GOOGLE, "2026-10-29T00:00:00+00:00"),
        ("클라우드·인프라", "생성형 AI 투자 확대", "예시신문", GOOGLE.replace("?oc=5", ""), "2026-10-29T00:00:00+00:00"),
        ("정보보안", "  랜섬웨어   대응  ", "보안일보", "https://news.google.com/rss/articles/SEC1?oc=5", None),
        ("AI", "옛 분류 기사", "예시신문", "https://news.google.com/rss/articles/OLD1", None),
        ("백엔드·서버", "링크 오류", "예시신문", "javascript:alert(1)", None),
        ("모바일 개발", "   ", "예시신문", "https://news.google.com/rss/articles/BLANK", None),
    ])
    before = path.read_bytes()

    articles, skipped = importer.read_sqlite(path)

    by_title = {article.title: article for article in articles}
    assert set(by_title) == {"생성형 AI 투자 확대", "랜섬웨어 대응"}
    assert by_title["생성형 AI 투자 확대"].field_codes == {"data_ai", "cloud_infra"}  # 같은 링크 → 한 뉴스, 두 분야
    assert by_title["생성형 AI 투자 확대"].published_at == datetime(2026, 10, 29)
    assert by_title["랜섬웨어 대응"].published_at is None
    assert all(article.link_type == "GOOGLE_NEWS_RSS" for article in articles)
    assert not any(hasattr(article, "news_id") for article in articles)  # SQLite news_id는 쓰지 않음
    assert skipped == {"unknown_category": 1, "invalid_link": 1, "empty_title": 1}
    assert path.read_bytes() == before  # 읽기 전용


def test_read_sqlite_requires_news_table_columns(tmp_path):
    path = tmp_path / "other.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE news (news_id INTEGER PRIMARY KEY, title TEXT)")
    connection.close()
    with pytest.raises(ValueError):
        importer.read_sqlite(path)
    with pytest.raises(FileNotFoundError):
        importer.read_sqlite(tmp_path / "missing.db")


def test_dry_run_does_not_connect_to_database(tmp_path, monkeypatch, capsys):
    path = make_sqlite(tmp_path / "career_news.db", [
        ("데이터·AI", "AI 기사", "예시신문", GOOGLE, None),
    ])
    monkeypatch.setattr("sys.argv", ["import_career_news.py", "--sqlite", str(path)])
    importer.main()
    output = capsys.readouterr().out
    assert "읽은 뉴스 1건" in output and "확인 모드" in output


def test_migration_does_not_alter_existing_tables():
    sql = (ROOT / "database" / "sql" / "017_career_news.sql").read_text(encoding="utf-8").upper()
    for table in ("POSTS", "CAREER_POSTS", "POST_SCRAPS"):
        assert f"ALTER TABLE {table}" not in sql
        assert f"DROP TABLE IF EXISTS {table}" not in sql
    assert "DELETE FROM" not in sql and "UPDATE " not in sql
