"""일반·취업 게시판 공통 댓글의 '대댓글에 대한 답글'(Issue #153) 저장·조회·수정 규칙. DB에 접속하지 않는다.

- 저장: 가짜 커서로 실행 SQL과 바인딩을 기록해 서버가 정한 원댓글·실제 대상, 검증 순서, 롤백을 확인한다.
- 조회: repository가 만든 SQL을 메모리 SQLite에서 그대로 실행해 대상 작성자 이름 가리기·삭제 표시·NULL 호환을 확인한다.
"""
from copy import deepcopy
from datetime import datetime, timezone
import sqlite3
from unittest.mock import Mock

from fastapi import HTTPException
import pytest

from app.core import db_connect
from app.repositories import board_repository
from app.schemas.board import CommentWrite
from app.services import board_service as service
from app.services import career_reaction_service as career

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class Cursor:
    """예정된 DB 결과를 반환하고 실행 SQL·바인딩을 기록한다."""

    def __init__(self, results, rowcount=1):
        self.results = iter(deepcopy(results))
        self.queries = []
        self.rowcount = rowcount

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql, params=None):
        self.queries.append((" ".join(sql.split()), params))
        self.result = next(self.results)

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result


@pytest.fixture
def database(monkeypatch):
    """실제 db_cursor의 커밋·롤백을 관찰할 연결 대역."""

    def install(results):
        cursor = Cursor(results)
        connection = Mock()
        connection.cursor.return_value = cursor
        monkeypatch.setattr(db_connect, "_acquire_connection",
                            lambda: db_connect._ConnectionLease(connection, None))
        return cursor, connection

    return install


@pytest.fixture(autouse=True)
def isolate_side_effects(monkeypatch):
    """권한·XP·알림은 별도 테스트가 있으므로 여기서는 기록만 한다."""
    calls = {"xp": [], "notify": []}
    monkeypatch.setattr(service, "_require_course_board_writer", lambda *_: None)
    monkeypatch.setattr(service, "_require_comment_board_writer", lambda *_: None)
    monkeypatch.setattr(service, "grant_xp", lambda member_id, kind, source: calls["xp"].append(kind))
    monkeypatch.setattr(service, "save_comment_notification",
                        lambda post_id, comment_id, actor, parent=None: calls["notify"].append(parent))
    monkeypatch.setattr(career, "grant_xp", lambda member_id, kind, source: calls["xp"].append(kind))
    monkeypatch.setattr(career, "save_comment_notification",
                        lambda post_id, comment_id, actor, parent=None: calls["notify"].append(parent))
    return calls


def detail(comment_id=9, parent=None, reply_to=None):
    return dict(id=comment_id, post_id=2, parent_comment_id=parent, reply_to_comment_id=reply_to,
                reply_to_author_name=None, reply_to_is_deleted=False, body="답글", author_id=1,
                author_name="닉네임", is_anonymous=False, created_at=NOW, updated_at=NOW, is_owner=True)


def target(comment_id, parent=None, post_id=2, root_post_id=None, root_parent=None):
    """get_reply_target 결과 행. 대상이 대댓글이면 원댓글 정보가 함께 온다."""
    return dict(comment_id=comment_id, post_id=post_id, parent_comment_id=parent,
                root_post_id=(post_id if root_post_id is None else root_post_id) if parent else None,
                root_parent_comment_id=root_parent)


POST_EXISTS = {"exists": 1}


def inserts(cursor):
    return [(sql, params) for sql, params in cursor.queries if "INSERT INTO comments" in sql]


# ---------------------------------------------------------------------------
# 저장
# ---------------------------------------------------------------------------
def test_top_level_comment_unchanged(database, isolate_side_effects):
    """원댓글: 답글 관계 조회 없이 기존 INSERT(답글 대상 컬럼 없음)로 저장한다."""
    cursor, connection = database([POST_EXISTS, {"comment_id": 9}, detail()])
    service.create_comment(1, 2, "댓글", 1)
    (sql, params), = inserts(cursor)
    assert "reply_to_comment_id" not in sql and params == (2, 1, "댓글", None, False)
    assert isolate_side_effects == {"xp": ["COMMENT"], "notify": [None]}
    connection.commit.assert_called_once()


def test_legacy_parent_only_reply_keeps_existing_query_and_null_target(database, isolate_side_effects):
    """기존 방식(parent_comment_id만): 기존 부모 검증·기존 INSERT 그대로, 저장되는 답글 대상은 NULL."""
    cursor, _ = database([POST_EXISTS, {"post_id": 2, "parent_comment_id": None},
                          {"comment_id": 9}, detail(parent=3, reply_to=3)])
    service.create_comment(1, 2, "답글", 1, 3)
    assert cursor.queries[1][0].endswith("FROM comments WHERE comment_id = %s AND deleted_at IS NULL")
    (sql, params), = inserts(cursor)
    assert "reply_to_comment_id" not in sql and params == (2, 1, "답글", 3, False)
    assert isolate_side_effects == {"xp": ["REPLY"], "notify": [3]}


def test_legacy_parent_pointing_to_reply_keeps_existing_error(database):
    """기존 방식으로 대댓글 ID를 parent_comment_id에 주면 기존과 같이 422로 거부한다."""
    cursor, connection = database([POST_EXISTS, {"post_id": 2, "parent_comment_id": 3}])
    with pytest.raises(HTTPException) as error:
        service.create_comment(1, 2, "답글", 1, 5)
    assert error.value.status_code == 422 and "대댓글에는" in error.value.detail
    assert inserts(cursor) == []
    connection.rollback.assert_called_once()


def test_reply_to_root_stores_root_as_both(database, isolate_side_effects):
    """새 방식으로 원댓글에 답글: parent = reply_to = 원댓글. 대상 행은 FOR SHARE로 잠근다."""
    cursor, _ = database([POST_EXISTS, target(3), {"comment_id": 9}, detail(parent=3, reply_to=3)])
    service.create_comment(1, 2, "답글", 1, reply_to_comment_id=3)
    sql, params = cursor.queries[1]
    assert "FOR SHARE OF target" in sql and "target.deleted_at IS NULL" in sql and params == (3,)
    (sql, params), = inserts(cursor)
    assert "reply_to_comment_id" in sql and params == (2, 1, "답글", 3, 3, False)
    assert isolate_side_effects == {"xp": ["REPLY"], "notify": [3]}


@pytest.mark.parametrize("target_id,label", [(5, "대댓글에 답글"), (7, "답글에 다시 답글")])
def test_reply_to_reply_is_saved_under_root(database, target_id, label):
    """대댓글·답글의 답글도 서버가 원댓글(3)을 계산해 항상 2단계로 저장한다."""
    cursor, _ = database([POST_EXISTS, target(target_id, parent=3), {"comment_id": 9},
                          detail(parent=3, reply_to=target_id)])
    result = service.create_comment(1, 2, label, 1, reply_to_comment_id=target_id)
    (_, params), = inserts(cursor)
    assert params == (2, 1, label, 3, target_id, False)
    assert result["parent_comment_id"] == 3 and result["reply_to_comment_id"] == target_id


def test_consistent_parent_and_target_accepted(database):
    """두 필드를 함께 주면 parent_comment_id가 계산된 원댓글과 같을 때만 허용한다."""
    cursor, _ = database([POST_EXISTS, target(5, parent=3), {"comment_id": 9}, detail(parent=3, reply_to=5)])
    service.create_comment(1, 2, "답글", 1, 3, reply_to_comment_id=5)
    assert inserts(cursor)[0][1] == (2, 1, "답글", 3, 5, False)


@pytest.mark.parametrize(
    "row,status,fragment",
    [
        (None, 404, "답글 대상 댓글을 찾을 수 없습니다"),                              # 없거나 삭제됨
        (target(5, parent=3, post_id=99), 422, "같은 게시글"),                         # 다른 게시글의 댓글 ID
        (target(5, parent=3, root_post_id=99), 422, "스레드 정보"),                    # 원댓글이 다른 글
        (target(5, parent=3, root_parent=1), 422, "스레드 정보"),                      # 3단계 데이터
    ],
    ids=["missing_or_deleted", "other_post", "root_in_other_post", "broken_thread"],
)
def test_invalid_reply_target_rolls_back(database, row, status, fragment):
    cursor, connection = database([POST_EXISTS, row])
    with pytest.raises(HTTPException) as error:
        service.create_comment(1, 2, "답글", 1, reply_to_comment_id=5)
    assert error.value.status_code == status and fragment in error.value.detail
    assert inserts(cursor) == []
    connection.commit.assert_not_called()
    connection.rollback.assert_called_once()


def test_conflicting_parent_and_target_rejected(database):
    """parent_comment_id(4)가 대상(5)의 원댓글(3)과 다르면 422로 거부한다."""
    cursor, connection = database([POST_EXISTS, target(5, parent=3)])
    with pytest.raises(HTTPException) as error:
        service.create_comment(1, 2, "답글", 1, 4, reply_to_comment_id=5)
    assert error.value.status_code == 422 and "같은 댓글 스레드" in error.value.detail
    assert inserts(cursor) == []
    connection.rollback.assert_called_once()


def test_career_comment_uses_same_rules(database, monkeypatch, isolate_side_effects):
    """취업 게시판도 같은 검증으로 원댓글을 계산해 저장한다."""
    monkeypatch.setattr(career, "_require_career_post", lambda cursor, post_id: None)
    cursor, _ = database([target(5, parent=3), {"comment_id": 9}, detail(parent=3, reply_to=5)])
    career.create_comment(2, "취업 답글", 1, None, True, 5)
    (_, params), = inserts(cursor)
    assert params == (2, 1, "취업 답글", 3, 5, True)
    assert isolate_side_effects == {"xp": ["REPLY"], "notify": [3]}


def test_career_conflicting_fields_rejected(database, monkeypatch):
    monkeypatch.setattr(career, "_require_career_post", lambda cursor, post_id: None)
    cursor, connection = database([target(5, parent=3)])
    with pytest.raises(HTTPException) as error:
        career.create_comment(2, "답글", 1, 8, False, 5)
    assert error.value.status_code == 422
    assert inserts(cursor) == []
    connection.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# HTTP 요청·수정 차단
# ---------------------------------------------------------------------------
def test_http_create_reply_to_reply(client, database):
    database([POST_EXISTS, target(5, parent=3), {"comment_id": 9},
              dict(detail(parent=3, reply_to=5), reply_to_author_name="원작성자")])
    response = client.post("/api/boards/1/posts/2/comments",
                           json={"body": "답글", "reply_to_comment_id": 5})
    assert response.status_code == 201
    body = response.json()
    assert (body["parent_comment_id"], body["reply_to_comment_id"]) == (3, 5)
    assert body["reply_to_author_name"] == "원작성자" and body["reply_to_is_deleted"] is False


@pytest.mark.parametrize("payload", [
    {"body": "수정", "reply_to_comment_id": 5},
    {"body": "수정", "parent_comment_id": 3, "reply_to_comment_id": 5},
    {"body": "수정", "parent_comment_id": 3},
])
def test_http_update_cannot_change_reply_relation(client, database, payload):
    """수정 API는 parent_comment_id·reply_to_comment_id를 바꿀 수 없다(DB 접근 전 422)."""
    _, connection = database([])
    response = client.patch("/api/comments/9", json=payload)
    assert response.status_code == 422
    connection.cursor.assert_not_called()


@pytest.mark.parametrize("value", [0, -1, "abc"])
def test_reply_target_id_must_be_positive_integer(value):
    with pytest.raises(ValueError):
        CommentWrite(body="답글", reply_to_comment_id=value)


# ---------------------------------------------------------------------------
# 조회 SQL (메모리 SQLite에서 repository SQL을 그대로 실행)
# ---------------------------------------------------------------------------
class SqliteCursor:
    def __init__(self, connection):
        self.cursor = connection.cursor()

    def execute(self, sql, params=None):
        self.cursor.execute(sql.replace("%s", "?"), params or ())

    def fetchall(self):
        return [dict(row) for row in self.cursor.fetchall()]

    def fetchone(self):
        row = self.cursor.fetchone()
        return dict(row) if row else None


@pytest.fixture
def reply_db():
    """원댓글 201 아래의 기존·새 방식 답글과 익명·탈퇴·삭제 대상을 담은 메모리 DB."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE members (member_id INTEGER PRIMARY KEY, nickname TEXT, profile_image_url TEXT, member_status TEXT);
        CREATE TABLE comments (
            comment_id INTEGER PRIMARY KEY, post_id INTEGER, parent_comment_id INTEGER, reply_to_comment_id INTEGER,
            body TEXT, author_member_id INTEGER, is_anonymous BOOLEAN, deleted_at TEXT, created_at TEXT, updated_at TEXT
        );
        INSERT INTO members VALUES
            (1, '알파', NULL, 'ACTIVE'), (2, '베타', NULL, 'ACTIVE'),
            (3, '탈퇴전닉네임', NULL, 'WITHDRAWN'), (4, '익명실명', NULL, 'ACTIVE'), (5, '', NULL, 'ACTIVE');
        INSERT INTO comments VALUES
            (201, 10, NULL, NULL, '원댓글', 1, 0, NULL, '2026-11-01 10:00', NULL),
            (202, 10, 201,  NULL, '기존 대댓글(NULL)', 2, 0, NULL, '2026-11-01 10:01', NULL),
            (203, 10, 201,  202,  '대댓글에 답글', 1, 0, NULL, '2026-11-01 10:02', NULL),
            (204, 10, 201,  201,  '익명 답글', 4, 1, NULL, '2026-11-01 10:03', NULL),
            (205, 10, 201,  204,  '익명 대상에 답글', 2, 0, NULL, '2026-11-01 10:04', NULL),
            (206, 10, 201,  201,  '탈퇴 회원 답글', 3, 0, NULL, '2026-11-01 10:05', NULL),
            (207, 10, 201,  206,  '탈퇴 대상에 답글', 1, 0, NULL, '2026-11-01 10:06', NULL),
            (208, 10, 201,  201,  '삭제될 답글', 2, 0, '2026-11-02 09:00', '2026-11-01 10:07', NULL),
            (209, 10, 201,  208,  '삭제 대상에 답글', 1, 0, NULL, '2026-11-01 10:08', NULL),
            (210, 10, 201,  203,  '답글의 답글', 5, 0, NULL, '2026-11-01 10:09', NULL),
            (211, 10, 201,  210,  '빈 닉네임 대상에 답글', 2, 0, NULL, '2026-11-01 10:10', NULL),
            (301, 10, NULL, NULL, '다른 원댓글', 2, 0, NULL, '2026-11-01 11:00', NULL);
        """
    )
    yield connection
    connection.close()


def reply_view(row):
    return (row["reply_to_comment_id"], row["reply_to_author_name"], bool(row["reply_to_is_deleted"]))


def test_list_comments_reply_targets_and_masking(reply_db):
    rows = board_repository.list_comments(SqliteCursor(reply_db), 10, 1)
    by_id = {row["id"]: row for row in rows}

    # 2단계 평면 구조와 기존 정렬: 원댓글 → 작성 순 답글 → 다음 원댓글. 삭제된 답글(208)은 빠진다.
    assert [row["id"] for row in rows] == [201, 202, 203, 204, 205, 206, 207, 209, 210, 211, 301]
    assert all(by_id[i]["parent_comment_id"] == 201 for i in (202, 203, 205, 207, 209, 210, 211))

    assert reply_view(by_id[201]) == (None, None, False)            # 원댓글
    assert reply_view(by_id[202]) == (201, "알파", False)            # 기존 데이터 NULL → 원댓글로 해석
    assert reply_view(by_id[203]) == (202, "베타", False)            # 대댓글에 답글
    assert reply_view(by_id[205]) == (204, "익명", False)            # 익명 대상은 '익명'
    assert reply_view(by_id[207]) == (206, "탈퇴한 사용자", False)    # 탈퇴 대상
    assert reply_view(by_id[209]) == (208, None, True)              # 삭제된 대상: 이름 없음 + 삭제 표시
    assert reply_view(by_id[210]) == (203, "알파", False)            # 답글의 답글
    assert reply_view(by_id[211]) == (210, "익명", False)            # 빈 닉네임은 작성자 규칙과 같이 '익명'

    # 대상 작성자의 실제 닉네임·회원 ID를 어떤 행에도 내보내지 않는다(답글 대상 관련 필드).
    exposed = {row["reply_to_author_name"] for row in rows}
    assert "익명실명" not in exposed and "탈퇴전닉네임" not in exposed
    assert all("reply_to_author_id" not in row and "target_member_id" not in row for row in rows)
    assert by_id[204]["author_id"] is None and by_id[204]["author_name"] == "익명"


def test_comment_detail_has_same_reply_target_policy(reply_db):
    def get(comment_id):
        return board_repository.get_comment(SqliteCursor(reply_db), comment_id, 1)

    assert reply_view(get(201)) == (None, None, False)
    assert reply_view(get(202)) == (201, "알파", False)
    assert reply_view(get(205)) == (204, "익명", False)
    assert reply_view(get(207)) == (206, "탈퇴한 사용자", False)
    assert reply_view(get(209)) == (208, None, True)
    assert get(208) is None


def test_deleted_root_placeholder_policy_unchanged(reply_db):
    """원댓글이 삭제돼도 살아 있는 답글이 있으면 자리표시로 남고, 그 원댓글을 향한 답글은 삭제 표시만 붙는다."""
    reply_db.execute("UPDATE comments SET deleted_at = '2026-11-03 00:00' WHERE comment_id = 201")
    rows = {row["id"]: row for row in board_repository.list_comments(SqliteCursor(reply_db), 10, 1)}
    assert rows[201]["is_deleted"] and rows[201]["body"] == "" and rows[201]["author_name"] == ""
    assert reply_view(rows[202]) == (201, None, True)
    assert reply_view(rows[203]) == (202, "베타", False)   # 다른 대상은 영향 없음
