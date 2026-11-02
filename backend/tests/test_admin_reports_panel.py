"""관리자 신고 상세 조회: 신고 없는 게시글 배제와 신고 사유 결합 검증."""
from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from app.routers import board_moderation as moderation


class FakeCursor:
    def __init__(self, records):
        self.records = iter(records)
        self.sql = []
        self.params = []

    def execute(self, sql, params=()):
        self.sql.append(' '.join(sql.split()))
        self.params.append(params)

    def fetchall(self):
        return next(self.records)


def fake_database(monkeypatch, records):
    cursor = FakeCursor(records)

    @contextmanager
    def db_cursor(**kwargs):
        assert kwargs.get('read_only') is True
        yield cursor

    monkeypatch.setattr(moderation, 'db_cursor', db_cursor)
    return cursor


def test_admin_report_details_and_hidden_visible(monkeypatch):
    calls = []
    monkeypatch.setattr(moderation.admin_service, 'assert_admin', lambda member_id: calls.append(member_id))
    cursor = fake_database(monkeypatch, [
        [
            {'post_id': 10, 'board_id': 1, 'title': '신고 글', 'report_count': 2, 'post_status': 'PUBLISHED'},
            {'post_id': 11, 'board_id': 2, 'title': '숨긴 글', 'report_count': 3, 'post_status': 'HIDDEN'},
        ],
        [
            {'post_id': 10, 'report_id': 1, 'reason': 'SPAM', 'details': '광고 링크', 'reporter_name': 'A'},
            {'post_id': 10, 'report_id': 2, 'reason': 'ABUSE', 'details': None, 'reporter_name': 'B'},
            {'post_id': 11, 'report_id': 3, 'reason': 'PRIVACY', 'details': '전화번호', 'reporter_name': 'C'},
        ],
    ])
    result = moderation.list_reported_posts_details(7)
    assert calls == [7]
    assert len(result) == 2
    assert [r['reason'] for r in result[0]['reports']] == ['SPAM', 'ABUSE']
    assert result[0]['reports'][0]['details'] == '광고 링크'
    assert result[1]['post_status'] == 'HIDDEN'
    assert result[1]['reports'][0]['reason'] == 'PRIVACY'
    assert cursor.params[1] == ([10, 11],)
    assert "FROM post_reports AS r" in cursor.sql[0]
    assert "p.deleted_at IS NULL" in cursor.sql[0]


def test_empty_reports_do_not_query_details(monkeypatch):
    monkeypatch.setattr(moderation.admin_service, 'assert_admin', lambda member_id: None)
    cursor = fake_database(monkeypatch, [[]])
    assert moderation.list_reported_posts_details(7) == []
    assert len(cursor.sql) == 1


def test_non_admin_cannot_read_reports(monkeypatch):
    def forbidden(member_id):
        raise HTTPException(status_code=403, detail='관리자 권한이 없습니다.')

    monkeypatch.setattr(moderation.admin_service, 'assert_admin', forbidden)
    with pytest.raises(HTTPException) as exc:
        moderation.list_reported_posts_details(5)
    assert exc.value.status_code == 403
