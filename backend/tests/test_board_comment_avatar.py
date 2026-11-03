"""Non-anonymous board comments may show a picture; anonymous ones never expose it."""
import sqlite3
from contextlib import contextmanager

import pytest

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


class SqliteCursor:
    """repository가 만든 SQL을 그대로 실행하는 격리 SQLite 커서(%s 자리표시자만 변환)."""

    def __init__(self, connection):
        self.cursor = connection.cursor()

    def execute(self, sql, params=None):
        self.cursor.execute(sql.replace("%s", "?"), params or ())

    def fetchall(self):
        return [dict(row) for row in self.cursor.fetchall()]

    def fetchone(self):
        row = self.cursor.fetchone()
        return dict(row) if row else None


AVATAR = "https://cdn.discordapp.com/avatars/{}/hash.png"


@pytest.fixture
def comment_db():
    """작성자 상태별 댓글을 담은 메모리 SQLite DB. 실제 DB에는 접속하지 않는다.

    회원 1: 일반, 2: 일반(익명 댓글 작성), 3: 이미지가 빈 문자열인 일반 회원,
    4: 탈퇴 회원(비식별화 전 이미지가 남은 경우도 노출되지 않아야 함), 5: 삭제된 부모 댓글 작성자.
    댓글 106은 답글 107이 남은 삭제 댓글, 108은 답글 없는 삭제 댓글이다.
    """
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        f"""
        CREATE TABLE members (
            member_id INTEGER PRIMARY KEY, nickname TEXT, profile_image_url TEXT, member_status TEXT
        );
        CREATE TABLE comments (
            comment_id INTEGER PRIMARY KEY, post_id INTEGER, parent_comment_id INTEGER, body TEXT,
            author_member_id INTEGER, is_anonymous BOOLEAN, deleted_at TEXT,
            created_at TEXT, updated_at TEXT
        );
        INSERT INTO members VALUES
            (1, '일반회원', '{AVATAR.format(1)}', 'ACTIVE'),
            (2, '익명작성자', '{AVATAR.format(2)}', 'ACTIVE'),
            (3, '빈이미지', '', 'ACTIVE'),
            (4, '탈퇴전닉네임', '{AVATAR.format(4)}', 'WITHDRAWN'),
            (5, '삭제작성자', '{AVATAR.format(5)}', 'ACTIVE');
        INSERT INTO comments VALUES
            (101, 10, NULL, '일반 댓글', 1, 0, NULL, '2026-11-01 10:00', NULL),
            (102, 10, NULL, '익명 댓글', 2, 1, NULL, '2026-11-01 10:01', NULL),
            (103, 10, NULL, '빈 이미지 댓글', 3, 0, NULL, '2026-11-01 10:02', NULL),
            (104, 10, NULL, '탈퇴 회원 댓글', 4, 0, NULL, '2026-11-01 10:03', NULL),
            (105, 10, NULL, '탈퇴 회원 익명 댓글', 4, 1, NULL, '2026-11-01 10:04', NULL),
            (106, 10, NULL, '삭제된 부모', 5, 0, '2026-11-02 09:00', '2026-11-01 10:05', NULL),
            (107, 10, 106, '남은 답글', 1, 0, NULL, '2026-11-01 10:06', NULL),
            (108, 10, NULL, '답글 없는 삭제 댓글', 5, 0, '2026-11-02 09:00', '2026-11-01 10:07', NULL);
        """
    )
    yield connection
    connection.close()


def author_view(row):
    """작성자 표시 정책과 관련된 필드만 비교용으로 꺼낸다."""
    return (row["author_id"], row["author_name"], row["author_avatar_url"], bool(row["is_anonymous"]))


def test_list_comments_redacts_anonymous_and_deleted_avatar(comment_db):
    """목록에서 일반 회원만 작성자 ID·아바타를 보여주고 익명·삭제·탈퇴 작성자는 숨긴다."""
    rows = {row["id"]: row for row in board_repository.list_comments(SqliteCursor(comment_db), 10, 1)}

    assert set(rows) == {101, 102, 103, 104, 105, 106, 107}  # 답글 없는 삭제 댓글(108)은 제외
    assert author_view(rows[101]) == (1, "일반회원", AVATAR.format(1), False)
    assert author_view(rows[102]) == (None, "익명", None, True)
    assert author_view(rows[103]) == (3, "빈이미지", None, False)  # 빈 이미지 문자열은 NULL
    assert author_view(rows[104]) == (None, "탈퇴한 사용자", None, False)
    assert author_view(rows[105]) == (None, "익명", None, True)
    assert author_view(rows[106]) == (None, "", None, False)
    assert rows[106]["body"] == "" and bool(rows[106]["is_deleted"])
    assert author_view(rows[107]) == (1, "일반회원", AVATAR.format(1), False)
    # 탈퇴 회원의 기존 닉네임·이미지는 어떤 행에도 남지 않는다.
    exposed = {value for row in rows.values() for value in row.values()}
    assert "탈퇴전닉네임" not in exposed and AVATAR.format(4) not in exposed


def test_comment_detail_redacts_anonymous_avatar(comment_db):
    """단건 조회도 목록과 같은 작성자 표시 정책을 따르고, 삭제된 댓글은 반환하지 않는다."""
    def detail(comment_id):
        return board_repository.get_comment(SqliteCursor(comment_db), comment_id, 1)

    assert author_view(detail(101)) == (1, "일반회원", AVATAR.format(1), False)
    assert author_view(detail(102)) == (None, "익명", None, True)
    assert author_view(detail(103)) == (3, "빈이미지", None, False)
    assert author_view(detail(104)) == (None, "탈퇴한 사용자", None, False)
    assert author_view(detail(105)) == (None, "익명", None, True)
    assert detail(106) is None and detail(108) is None
    assert bool(detail(101)["is_owner"]) is True and bool(detail(104)["is_owner"]) is False


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
