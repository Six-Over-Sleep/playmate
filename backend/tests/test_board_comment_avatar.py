"""Non-anonymous board comments may show a picture; anonymous ones never expose it."""
from contextlib import contextmanager

from app.repositories import board_repository
from app.schemas.board import CommentResponse
from app.services import member_service


class QueryCursor:
    def __init__(self):
        self.sql = None
        self.params = None

    def execute(self, sql, params=None):
        self.sql = ' '.join(sql.split())
        self.params = params

    def fetchall(self):
        return []

    def fetchone(self):
        return None


def test_list_comments_redacts_anonymous_and_deleted_avatar():
    cursor = QueryCursor()
    assert board_repository.list_comments(cursor, 10, 1) == []
    assert "WHEN c.deleted_at IS NOT NULL OR c.is_anonymous THEN NULL" in cursor.sql
    assert "NULLIF(m.profile_image_url, '')" in cursor.sql
    assert "AS author_avatar_url" in cursor.sql


def test_comment_detail_redacts_anonymous_avatar():
    cursor = QueryCursor()
    assert board_repository.get_comment(cursor, 10, 1) is None
    assert "WHEN c.is_anonymous THEN NULL" in cursor.sql
    assert "NULLIF(m.profile_image_url, '')" in cursor.sql


def test_comment_schema_avatar_optional():
    field = CommentResponse.model_fields['author_avatar_url']
    assert field.default is None


def test_member_avatar_sync_updates_only_changes(monkeypatch):
    cursor = QueryCursor()
    commits = []

    @contextmanager
    def fake_db_cursor(**kwargs):
        commits.append(kwargs.get('commit'))
        yield cursor

    monkeypatch.setattr(member_service, 'db_cursor', fake_db_cursor)
    url = 'https://cdn.discordapp.com/avatars/123/hash.png'
    member_service.sync_member_avatar(5, url)
    assert commits == [True]
    assert 'profile_image_url IS DISTINCT FROM %s' in cursor.sql
    assert cursor.params == (url, 5, url)
