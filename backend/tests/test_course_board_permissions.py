"""과정·기수별 게시판 서버 권한 테스트 (실제 DB 접속 불필요)."""

import pytest
from fastapi import HTTPException
from app.services import board_service


@pytest.mark.parametrize(
    'board, member, permitted',
    [
        ({'course_code': None, 'cohort': None}, {'course': 'data-ml', 'cohort': 1, 'role_code': 'USER'}, True),
        ({'course_code': 'data-engineering', 'cohort': 2}, {'course': 'data-engineering', 'cohort': 2, 'role_code': 'USER'}, True),
        ({'course_code': 'data-engineering', 'cohort': 2}, {'course': 'data-engineering', 'cohort': 1, 'role_code': 'USER'}, False),
        ({'course_code': 'data-engineering', 'cohort': 2}, {'course': 'data-ml', 'cohort': 2, 'role_code': 'USER'}, False),
        ({'course_code': 'data-engineering', 'cohort': 2}, {'course': None, 'cohort': None, 'role_code': 'USER'}, False),
        ({'course_code': 'data-engineering', 'cohort': 2}, {'course': None, 'cohort': None, 'role_code': 'ADMIN'}, True),
    ],
)
def test_can_write_course_board(board, member, permitted):
    assert board_service._can_write_course_board(board, member) is permitted


def test_foreign_cohort_blocked_with_403(monkeypatch):
    monkeypatch.setattr(board_service, '_require_board', lambda _cursor, _board_id: {'course_code': 'multi-agent', 'cohort': 1})
    monkeypatch.setattr(board_service, '_get_board_member', lambda _cursor, _member_id: {'course': 'multi-agent', 'cohort': 2, 'role_code': 'USER'})
    with pytest.raises(HTTPException) as exc:
        board_service._require_course_board_writer(object(), 5, 123)
    assert exc.value.status_code == 403


def test_foreign_course_cannot_edit_comment(monkeypatch):
    class Cursor:
        def execute(self, sql, params):
            assert 'FROM comments' in sql
            assert params == (55,)
        def fetchone(self):
            return {'board_id': 77}

    def prohibit(_cursor, board_id, member_id):
        assert (board_id, member_id) == (77, 123)
        raise HTTPException(status_code=403, detail='열람만 가능')

    monkeypatch.setattr(board_service, '_require_course_board_writer', prohibit)
    with pytest.raises(HTTPException) as exc:
        board_service._require_comment_board_writer(Cursor(), 55, 123)
    assert exc.value.status_code == 403
