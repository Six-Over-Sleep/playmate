"""게시판 전국/기관/과정/기수 접근 권한 회귀 테스트.

공유 PostgreSQL에 접속하지 않는 단위 테스트입니다.
"""
from contextlib import contextmanager

from fastapi import HTTPException
import pytest

from app.services import board_service as service
from backend.app.repositories import board_repository as repository


MEMBER = {"role_code": "USER", "course": "family-ai", "cohort": 36}
ADMIN = {"role_code": "ADMIN", "course": None, "cohort": None}
VERIFIED = [{"institution_id": 1, "program_id": 2, "cohort_id": 3}]
OTHER = [{"institution_id": 10, "program_id": 20, "cohort_id": 30}]


@pytest.mark.parametrize(
    ("board", "enrollments", "write", "expected"),
    [
        ({"scope_type": "LEGACY", "course_code": "family-ai", "cohort": 36}, [], True, True),
        ({"scope_type": "LEGACY", "course_code": "multi-agent", "cohort": 1}, [], True, False),
        ({"scope_type": "NATIONAL", "read_policy": "SCOPE_ONLY"}, VERIFIED, False, True),
        ({"scope_type": "NATIONAL", "read_policy": "SCOPE_ONLY"}, [], False, False),
        ({"scope_type": "NATIONAL", "write_policy": "SCOPE_ONLY"}, VERIFIED, True, True),
        ({"scope_type": "INSTITUTION", "institution_id": 1, "read_policy": "SCOPE_ONLY"}, VERIFIED, False, True),
        ({"scope_type": "INSTITUTION", "institution_id": 2, "read_policy": "SCOPE_ONLY"}, VERIFIED, False, False),
        ({"scope_type": "PROGRAM", "program_id": 2, "write_policy": "SCOPE_ONLY"}, VERIFIED, True, True),
        ({"scope_type": "PROGRAM", "program_id": 5, "write_policy": "SCOPE_ONLY"}, VERIFIED, True, False),
        ({"scope_type": "COHORT", "cohort_id": 3, "read_policy": "SCOPE_ONLY"}, VERIFIED, False, True),
        ({"scope_type": "COHORT", "cohort_id": 3, "write_policy": "SCOPE_ONLY"}, OTHER, True, False),
        ({"scope_type": "COHORT", "cohort_id": 3, "read_policy": "ALL_VERIFIED"}, OTHER, False, True),
        ({"scope_type": "COHORT", "cohort_id": 3, "read_policy": "ALL_VERIFIED"}, [], False, False),
        ({"scope_type": "COHORT", "cohort_id": 3, "write_policy": "STAFF_ONLY"}, VERIFIED, True, False),
        ({"scope_type": "UNKNOWN", "cohort_id": 3}, VERIFIED, False, False),
        ({"scope_type": "COHORT", "cohort_id": None, "read_policy": "SCOPE_ONLY"}, VERIFIED, False, False),
    ],
)
def test_scope_matrix(board, enrollments, write, expected):
    assert service._can_access_board(board, MEMBER, enrollments, write=write) is expected


def test_admin_can_access_scoped_boards_without_enrollment():
    board = {"scope_type": "COHORT", "cohort_id": 3, "write_policy": "STAFF_ONLY"}
    assert service._can_access_board(board, ADMIN, [], write=True)
    assert service._can_access_board(board, ADMIN, [], write=False)


def test_legacy_read_unchanged():
    board = {"scope_type": "LEGACY", "course_code": "multi-agent", "cohort": 1}
    assert service._can_access_board(board, MEMBER, [], write=False)


class RecordingCursor:
    def __init__(self, rows=None):
        self.rows = [] if rows is None else rows
        self.queries = []

    def execute(self, sql, params=None):
        self.queries.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.rows


def test_verified_scope_query_excludes_pending_and_expired():
    cursor = RecordingCursor(VERIFIED)
    assert service._verified_enrollments(cursor, 8) == VERIFIED
    sql, params = cursor.queries[0]
    assert "e.enrollment_status = 'VERIFIED'" in sql
    assert "e.verified_at IS NOT NULL" in sql
    assert "e.expires_at > NOW()" in sql
    assert params == (8,)


def test_pending_member_cannot_read_scoped_board(monkeypatch):
    monkeypatch.setattr(service, "_require_board", lambda *_: {
        "scope_type": "COHORT", "cohort_id": 3, "read_policy": "SCOPE_ONLY"
    })
    monkeypatch.setattr(service, "_get_board_member", lambda *_: MEMBER)
    monkeypatch.setattr(service, "_verified_enrollments", lambda *_: [])
    with pytest.raises(HTTPException) as exc:
        service._require_board_reader(object(), 8, 10)
    assert exc.value.status_code == 403


def test_featured_applies_allowed_boards_before_sql_limit(monkeypatch):
    cursor = RecordingCursor()

    @contextmanager
    def fake_cursor(**_kwargs):
        yield cursor

    monkeypatch.setattr(service, "db_cursor", fake_cursor)
    monkeypatch.setattr(service.repository, "list_boards", lambda *_: [
        {"id": 1, "scope_type": "LEGACY", "course_code": None},
        {"id": 2, "scope_type": "COHORT", "cohort_id": 3, "read_policy": "SCOPE_ONLY"},
        {"id": 3, "scope_type": "COHORT", "cohort_id": 40, "read_policy": "SCOPE_ONLY"},
    ])
    monkeypatch.setattr(service, "_get_board_member", lambda *_: MEMBER)
    monkeypatch.setattr(service, "_verified_enrollments", lambda *_: VERIFIED)
    captured = {}

    def fake_featured(_cursor, kind, search, member_id, *, allowed_board_ids):
        captured.update(kind=kind, search=search, member_id=member_id, allowed=allowed_board_ids)
        return []

    monkeypatch.setattr(service.repository, "list_featured_posts", fake_featured)
    assert service.list_featured_posts("hot", None, 10) == []
    assert captured == {"kind": "hot", "search": "", "member_id": 10, "allowed": [1, 2]}


def test_featured_repository_filters_before_limit():
    cursor = RecordingCursor()
    assert repository.list_featured_posts(
        cursor, "hot", "", 10, allowed_board_ids=[2]
    ) == []
    sql, params = cursor.queries[0]
    assert "AND p.board_id = ANY(%s)" in sql
    assert sql.index("AND p.board_id = ANY(%s)") < sql.index("LIMIT 100")
    assert params == [10, 10, [2]]


def test_featured_empty_allowed_ids_does_not_query():
    cursor = RecordingCursor()
    assert repository.list_featured_posts(
        cursor, "hot", "", 10, allowed_board_ids=[]
    ) == []
    assert cursor.queries == []
