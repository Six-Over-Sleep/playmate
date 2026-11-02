"""마이페이지 요약 scraps_count(게시글+뉴스 스크랩)를 실제 PostgreSQL과 HTTP 경로로 검증한다 (Issue #74, #58 협의).

일회용 DB 주소를 PLAYMATE_CAREER_NEWS_TEST_DB_URL로 줄 때만 실행한다. (공용 DB 사용 금지, localhost만 허용)
전용 스키마 두 개를 만든다: 뉴스 테이블이 있는 스키마(017 적용)와 없는 스키마(017 적용 전 DB).
요약 SQL이 쓰는 기존 테이블은 필요한 컬럼만 만든다. 끝나면 두 스키마를 지운다.
"""
import os
from pathlib import Path
from urllib.parse import urlsplit

import psycopg2
from fastapi.testclient import TestClient
import pytest


DB_URL = os.getenv("PLAYMATE_CAREER_NEWS_TEST_DB_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="일회용 PostgreSQL에서만 실행")

ROOT = Path(__file__).resolve().parents[3]
MIGRATION = ROOT / "database" / "sql" / "017_career_news.sql"
WITH_NEWS, WITHOUT_NEWS = "mypage_summary_news_test", "mypage_summary_nonews_test"

BASE_TABLES = """
CREATE TABLE members (member_id BIGINT PRIMARY KEY, discord_id VARCHAR(30), nickname VARCHAR(50));
CREATE TABLE member_levels (member_id BIGINT PRIMARY KEY REFERENCES members, total_xp INTEGER);
CREATE TABLE posts (post_id BIGINT PRIMARY KEY, author_member_id BIGINT REFERENCES members, title VARCHAR(100),
                    deleted_at TIMESTAMP);
CREATE TABLE comments (comment_id BIGINT PRIMARY KEY, post_id BIGINT REFERENCES posts,
                       author_member_id BIGINT REFERENCES members, deleted_at TIMESTAMP);
CREATE TABLE post_likes (post_id BIGINT REFERENCES posts, member_id BIGINT REFERENCES members);
CREATE TABLE post_scraps (post_id BIGINT REFERENCES posts, member_id BIGINT REFERENCES members,
                          created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (post_id, member_id));
CREATE TABLE recruits (recruit_id BIGINT PRIMARY KEY, post_id BIGINT REFERENCES posts);
CREATE TABLE recruit_members (recruit_id BIGINT REFERENCES recruits, member_id BIGINT REFERENCES members,
                              status VARCHAR(20));
-- 회원 1: 게시글 3·댓글 2·받은 좋아요 1·모임 1·XP 50, 회원 2: 다른 회원, 회원 3: 아무 활동 없음
INSERT INTO members VALUES (1, '1001', 'a'), (2, '1002', 'b'), (3, '1003', 'c');
INSERT INTO member_levels VALUES (1, 50);
INSERT INTO posts VALUES (10, 1, 'p10', NULL), (11, 1, 'p11', NULL), (12, 1, 'p12', NULL),
                         (13, 2, 'p13', NULL), (14, 2, 'deleted', now());
INSERT INTO comments VALUES (1, 13, 1, NULL), (2, 13, 1, NULL), (3, 14, 1, NULL);
INSERT INTO post_likes VALUES (10, 2);
INSERT INTO recruits VALUES (1, 13);
INSERT INTO recruit_members VALUES (1, 1, 'JOINED');
"""


def admin():
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    return conn


def run(schema, sql, params=None):
    with admin() as conn, conn.cursor() as cursor:
        cursor.execute(f"SET search_path = {schema}")
        cursor.execute(sql, params)


@pytest.fixture
def api(monkeypatch):
    target = urlsplit(DB_URL)
    if target.hostname not in ("127.0.0.1", "localhost"):
        pytest.skip("로컬 일회용 DB(127.0.0.1/localhost)에서만 실행")
    for schema in (WITH_NEWS, WITHOUT_NEWS):
        with admin() as conn, conn.cursor() as cursor:
            cursor.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            cursor.execute(f"CREATE SCHEMA {schema}")
            cursor.execute(f"SET search_path = {schema}")
            cursor.execute(BASE_TABLES)
            if schema == WITH_NEWS:
                cursor.execute(MIGRATION.read_text(encoding="utf-8"))
                cursor.execute(
                    """INSERT INTO career_news (link_key, link_url, link_type, title)
                       SELECT lpad(to_hex(n), 64, '0'), 'https://news.google.com/rss/articles/' || n,
                              'GOOGLE_NEWS_RSS', 'news ' || n
                       FROM generate_series(1, 60) AS n""")

    from app.core import db_connect

    for key, value in {
        "DB_HOST": target.hostname, "DB_PORT": str(target.port or 5432),
        "DB_USER": target.username or "postgres", "DB_PASSWORD": target.password or "unused",
        "DB_NAME": target.path.lstrip("/"), "DB_SSLMODE": "disable", "APP_ENV": "test",
    }.items():
        monkeypatch.setenv(key, value)

    from app.main import app

    def client_for(schema):
        db_connect.close_pool()
        monkeypatch.setenv("PGOPTIONS", f"-c search_path={schema}")
        return TestClient(app)

    yield client_for
    db_connect.close_pool()
    with admin() as conn, conn.cursor() as cursor:
        for schema in (WITH_NEWS, WITHOUT_NEWS):
            cursor.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


def summary(client, member):
    response = client.get("/api/mypage/summary", headers={"X-Dev-Member-ID": str(member)})
    assert response.status_code == 200, response.text
    return response.json()


def scrap_posts(schema, member, post_ids):
    for post_id in post_ids:
        run(schema, "INSERT INTO post_scraps (post_id, member_id) VALUES (%s, %s)", (post_id, member))


def scrap_news(member, news_ids):
    for news_id in news_ids:
        run(WITH_NEWS, "INSERT INTO career_news_scraps (news_id, member_id) VALUES (%s, %s)", (news_id, member))


OTHER_FIELDS = {"posts_count": 3, "comments_count": 2, "received_likes_count": 1, "meetups_count": 1, "total_xp": 50}


def test_posts_plus_news_and_other_fields_unchanged(api):
    scrap_posts(WITH_NEWS, 1, [10, 11, 13])
    scrap_news(1, [1])
    with api(WITH_NEWS) as client:
        body = summary(client, 1)
    assert body == {**OTHER_FIELDS, "scraps_count": 4}  # 게시글 3 + 뉴스 1, 다른 필드는 기존 집계 그대로
    assert isinstance(body["scraps_count"], int)


@pytest.mark.parametrize("posts,news,expected", [
    ([], [1, 2], 2),           # 게시글 0 + 뉴스 2
    ([10, 11, 12], [], 3),     # 게시글 3 + 뉴스 0
    ([10, 14], [3], 2),        # 삭제된 게시글 스크랩은 기존처럼 제외
])
def test_counts(api, posts, news, expected):
    scrap_posts(WITH_NEWS, 1, posts)
    scrap_news(1, news)
    with api(WITH_NEWS) as client:
        assert summary(client, 1)["scraps_count"] == expected


def test_more_than_50_news_scraps_are_counted_exactly(api):
    scrap_posts(WITH_NEWS, 1, [10])
    scrap_news(1, range(1, 56))  # 55건 (뉴스 스크랩 목록 API 최대 50건과 무관)
    with api(WITH_NEWS) as client:
        assert summary(client, 1)["scraps_count"] == 56
        assert client.get("/api/career/news/scraps?limit=50",
                          headers={"X-Dev-Member-ID": "1"}).json()["count"] == 50  # 목록은 여전히 최대 50건


def test_other_members_scraps_are_not_counted(api):
    scrap_posts(WITH_NEWS, 1, [10])
    scrap_news(1, [1])
    scrap_posts(WITH_NEWS, 2, [10, 11, 12])
    scrap_news(2, [1, 2, 3, 4])
    with api(WITH_NEWS) as client:
        assert summary(client, 1)["scraps_count"] == 2
        assert summary(client, 2)["scraps_count"] == 7
        assert summary(client, 3)["scraps_count"] == 0
        assert client.get("/api/mypage/summary").status_code == 401  # 인증 정책 그대로


def test_hidden_news_scrap_is_counted_like_the_list(api):
    scrap_news(1, [1, 2])
    run(WITH_NEWS, "UPDATE career_news SET hidden_at = now() WHERE news_id = 2")
    with api(WITH_NEWS) as client:
        assert summary(client, 1)["scraps_count"] == 2  # 마이페이지 목록도 숨긴 뉴스 스크랩을 표시함


def test_without_news_tables_summary_still_works(api):
    scrap_posts(WITHOUT_NEWS, 1, [10, 11, 13])
    with api(WITHOUT_NEWS) as client:
        assert summary(client, 1) == {**OTHER_FIELDS, "scraps_count": 3}
