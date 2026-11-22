"""회원별 게시판 방문 횟수를 방문 기록(member_board_visit_events.board_id)에서 집계한다 (#159, 044).

044 이전에는 member_board_visits에 횟수를 따로 누적했다. 이제 방문 1건 = 기록 1행이고,
게시판 목록의 개인 정렬은 기록을 집계한다. DB에 접속하지 않는다.
"""

from uuid import uuid4

import pytest
from psycopg2.errors import UndefinedColumn, UndefinedTable

from app.repositories import activity_repository, board_repository


class Cursor:
    def __init__(self, results=(), error=None):
        self.queries = []
        self.results = list(results)
        self.error = error

    def execute(self, sql, params=None):
        self.queries.append((" ".join(sql.split()), params))
        if self.error is not None:
            error, self.error = self.error, None
            raise error

    def fetchone(self):
        return self.results.pop(0) if self.results else None

    def fetchall(self):
        return self.results.pop(0) if self.results else []


def test_tracked_visit_writes_one_event_with_board_and_no_counter_table():
    cursor = Cursor([{"board_found": True, "recorded": True}])
    visit_id = uuid4()
    result = activity_repository.record_tracked_board_view(cursor, 7, visit_id, "12", 12)

    assert result == {"board_found": True, "recorded": True}
    sql, params = cursor.queries[0]
    assert "INSERT INTO member_board_visit_events (member_id, visit_id, board_id)" in sql
    assert "member_board_visits" not in sql.replace("member_board_visit_events", "")
    assert "board_daily_visits" in sql  # 일일 방문 수는 그대로 누적
    assert params["visit_id"] == str(visit_id) and params["board_id"] == 12
    # 공지사항 등 고정 게시판은 개인 정렬에서 빼므로 board_id 없이(중복 방지용으로만) 기록한다.
    assert params["excluded"] == ["공지사항", "명예의 전당", "HOT 게시판", "자유게시판"]
    assert "board_name <> ALL(%(excluded)s)" in sql


def test_personal_board_order_counts_visit_events():
    cursor = Cursor([[{"id": 3, "name": "스터디"}]])
    rows = board_repository.list_boards(cursor, 7)

    assert rows == [{"id": 3, "name": "스터디"}]
    sql, params = cursor.queries[0]
    assert "FROM member_board_visit_events WHERE member_id = %s AND board_id IS NOT NULL" in sql
    assert "GROUP BY board_id" in sql and "member_board_visits " not in sql
    assert "COALESCE(v.visit_count, 0) DESC" in sql
    assert params == (7,)


class _Diag:
    def __init__(self, message):
        self.message_primary = message


@pytest.mark.parametrize("error_cls,message", [
    (UndefinedTable, 'relation "member_board_visit_events" does not exist'),
    (UndefinedColumn, 'column "board_id" does not exist'),
])
def test_board_list_falls_back_to_default_order_without_024_or_044(monkeypatch, error_cls, message):
    """024(테이블) 또는 044(board_id)가 없는 개발 DB에서도 목록은 기본 정렬로 응답한다."""

    class Error(error_cls):
        @property
        def diag(self):  # psycopg2 diag 대역
            return _Diag(message)

    cursor = Cursor([[{"id": 1, "name": "자유게시판"}]], error=Error())
    rows = board_repository.list_boards(cursor, 7)

    assert rows == [{"id": 1, "name": "자유게시판"}]
    assert len(cursor.queries) == 2
    assert "member_board_visit_events" not in cursor.queries[1][0]
    assert cursor.queries[1][1] == ()
