"""게시판 핵심 테이블의 저장·삭제 왕복을 실제 PostgreSQL에서 확인한다.

일회용 DB 주소를 PLAYMATE_BOARD_TEST_DB_URL로 줄 때만 실행한다(공용 DB 사용 금지).
접속 대상이 localhost·127.0.0.1이고 DB 이름에 test가 들어간 경우에만 앱의 db_cursor를 그 DB로 향하게 한다.
조건에 맞지 않으면 DB에 접속하기 전에 건너뛴다.
"""
import os
import uuid
from urllib.parse import urlsplit

import pytest

from app.core import db_connect
from app.core.db_connect import db_cursor


DB_URL = os.getenv("PLAYMATE_BOARD_TEST_DB_URL")
pytestmark = pytest.mark.skipif(
    not DB_URL, reason="일회용 PostgreSQL 주소(PLAYMATE_BOARD_TEST_DB_URL)가 있을 때만 실행"
)

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


@pytest.fixture
def board_db(monkeypatch):
    """로컬 일회용 테스트 DB인지 먼저 확인한 뒤, 이 테스트 동안만 db_cursor 접속 대상을 바꾼다."""
    target = urlsplit(DB_URL)
    db_name = target.path.lstrip("/")
    if target.hostname not in LOCAL_HOSTS:
        pytest.skip("로컬 일회용 DB(127.0.0.1/localhost)에서만 실행")
    if "test" not in db_name.lower():
        pytest.skip("DB 이름에 test가 포함된 일회용 DB에서만 실행")

    db_connect.close_pool()
    for key, value in {
        "DB_HOST": target.hostname,
        "DB_PORT": str(target.port or 5432),
        "DB_USER": target.username or "postgres",
        "DB_PASSWORD": target.password or "unused",
        "DB_NAME": db_name,
        "DB_SSLMODE": "disable",
        "APP_ENV": "test",
    }.items():
        monkeypatch.setenv(key, value)
    yield
    # 테스트 DB로 만든 연결 풀을 버려 이후 테스트가 같은 접속 대상을 쓰지 않게 한다.
    db_connect.close_pool()


def test_required_tables_and_safe_round_trip(board_db):
    """필수 테이블 존재와 회원→게시판→게시글→댓글 저장·삭제 왕복을 확인한다."""
    marker = f"pytest-{uuid.uuid4()}"
    with db_cursor(commit=True) as cursor:
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name=ANY(%s)", (["members", "posts", "recruits", "boards", "comments"],))
        existing = {row["table_name"] for row in cursor.fetchall()}
        assert {"members", "posts", "boards", "comments"} <= existing
        cursor.execute("INSERT INTO members(public_anonymous_id) VALUES(%s) RETURNING member_id", (marker,)); member_id = cursor.fetchone()["member_id"]
        cursor.execute("INSERT INTO boards(board_name,created_by) VALUES(%s,%s) RETURNING board_id", (marker, member_id)); board_id = cursor.fetchone()["board_id"]
        cursor.execute("INSERT INTO posts(board_id,author_member_id,post_type,title,body) VALUES(%s,%s,'BOARD',%s,'body') RETURNING post_id", (board_id, member_id, marker)); post_id = cursor.fetchone()["post_id"]
        cursor.execute("INSERT INTO comments(post_id,author_member_id,body) VALUES(%s,%s,'comment')", (post_id, member_id))
        cursor.execute("SELECT COUNT(*) AS count FROM posts WHERE post_id=%s", (post_id,))
        assert cursor.fetchone()["count"] == 1
        cursor.execute("DELETE FROM comments WHERE post_id=%s", (post_id,))
        cursor.execute("DELETE FROM posts WHERE post_id=%s", (post_id,))
        cursor.execute("DELETE FROM boards WHERE board_id=%s", (board_id,))
        cursor.execute("DELETE FROM members WHERE member_id=%s", (member_id,))
