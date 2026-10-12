import os
import uuid

import pytest

from app.core.db_connect import db_cursor


pytestmark = pytest.mark.skipif(os.getenv("RUN_POSTGRES_INTEGRATION") != "1", reason="격리된 PostgreSQL 테스트 DB에서만 실행")


def test_required_tables_and_safe_round_trip():
    """Requires DB_NAME to point to a disposable, isolated test database."""
    marker = f"pytest-{uuid.uuid4()}"
    with db_cursor(commit=True) as cursor:
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name=ANY(%s)", (["members", "posts", "recruits", "boards", "comments"],))
        existing = {row["table_name"] for row in cursor.fetchall()}
        assert {"members", "posts", "boards", "comments"} <= existing
        cursor.execute("INSERT INTO members(public_anonymous_id) VALUES(%s) RETURNING member_id", (marker,)); member_id = cursor.fetchone()["member_id"]
        cursor.execute("INSERT INTO boards(board_name,category,created_by) VALUES(%s,'자유',%s) RETURNING board_id", (marker, member_id)); board_id = cursor.fetchone()["board_id"]
        cursor.execute("INSERT INTO posts(board_id,author_member_id,post_type,title,body) VALUES(%s,%s,'BOARD',%s,'body') RETURNING post_id", (board_id, member_id, marker)); post_id = cursor.fetchone()["post_id"]
        cursor.execute("INSERT INTO comments(post_id,author_member_id,body) VALUES(%s,%s,'comment')", (post_id, member_id))
        cursor.execute("SELECT COUNT(*) AS count FROM posts WHERE post_id=%s", (post_id,))
        assert cursor.fetchone()["count"] == 1
        cursor.execute("DELETE FROM comments WHERE post_id=%s", (post_id,))
        cursor.execute("DELETE FROM posts WHERE post_id=%s", (post_id,))
        cursor.execute("DELETE FROM boards WHERE board_id=%s", (board_id,))
        cursor.execute("DELETE FROM members WHERE member_id=%s", (member_id,))
