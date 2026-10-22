"""실제 Service·Repository·HTTP 인증 경로를 DB 커서 대역으로 검증한다.

공유 DB에는 접근하지 않는다. SQL 실행 계획·실DB 무결성은 별도 통합 검증 대상이다.
"""

from base64 import b64encode
from copy import deepcopy
from datetime import datetime, timezone
import json
from unittest.mock import Mock

from fastapi import HTTPException
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
import pytest

from app.core import db_connect
from app.main import app
from app.services import board_service as service

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def post_row(post_id=1):
    return dict(
        id=post_id,
        board_id=1,
        title="제목",
        body="본문",
        author_id=1,
        author_name="닉네임",
        created_at=NOW,
        updated_at=NOW,
        comment_count=2,
        is_owner=True,
    )


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
        if isinstance(self.result, Exception):
            raise self.result

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result


@pytest.fixture
def database(monkeypatch):
    """실제 db_cursor의 커밋·롤백·종료를 관찰할 연결 대역을 제공한다."""

    def install(results, rowcount=1):
        cursor = Cursor(results, rowcount)
        connection = Mock()
        connection.cursor.return_value = cursor
        factory = Mock(return_value=connection)
        monkeypatch.setattr(
            db_connect,
            "_acquire_connection",
            lambda: db_connect._ConnectionLease(factory(), None),
        )
        return cursor, connection, factory

    return install


@pytest.mark.parametrize("count", [0, 1, 25, 100])
def test_list_posts_bounded_queries_and_image_mapping(database, count):
    rows = [post_row(index + 1) for index in range(count)]
    images = [
        dict(
            post_id=1, id=8, url="/uploads/posts/first.png", original_name="first.png"
        ),
        dict(
            post_id=1, id=9, url="/uploads/posts/second.png", original_name="second.png"
        ),
    ]
    results = [{"id": 1}, rows] + ([images] if count else [])
    cursor, connection, factory = database(results)
    response = service.list_posts(1, "  공부' OR 1=1 --  ", "latest", 1)
    assert len(cursor.queries) == (3 if count else 2)
    factory.assert_called_once()
    connection.commit.assert_not_called()
    connection.close.assert_called_once()
    assert response == [
        dict(
            row,
            images=(
                [{k: v for k, v in image.items() if k != "post_id"} for image in images]
                if row["id"] == 1
                else []
            ),
        )
        for row in rows
    ]
    sql, params = cursor.queries[1]
    assert "공부" not in sql
    assert params == [1, 1, 1, "%공부' OR 1=1 --%", "%공부' OR 1=1 --%"]
    assert "AS like_count" in sql and "l.member_id = %s ) AS liked_by_me" in sql
    assert "p.deleted_at IS NULL" in sql and "NOT EXISTS" in sql
    assert "c.deleted_at IS NULL" in sql
    assert "ORDER BY p.created_at DESC" in sql
    if count:
        sql, params = cursor.queries[2]
        assert params == ([row["id"] for row in rows],)
        assert "ORDER BY post_id, display_order, image_id" in sql


def test_comments_only_check_post_existence(database):
    cursor, _, factory = database([{"exists": 1}, []])
    assert service.list_comments(1, 2, 1) == []
    assert len(cursor.queries) == 2
    assert all("post_images" not in sql for sql, _ in cursor.queries)
    factory.assert_called_once()


@pytest.mark.parametrize(
    "method,args",
    [
        (service.delete_post, (1, 2, 1)),
        (service.delete_comment, (2, 1)),
        (service.update_post, (1, 2, "제목", "본문", 1)),
        (service.update_comment, (2, "댓글", 1)),
    ],
)
@pytest.mark.parametrize("exists,status", [(None, 404), ({"exists": 1}, 403)])
def test_owner_failure_rolls_back(database, method, args, exists, status):
    cursor, connection, _ = database([None, exists], rowcount=0)
    with pytest.raises(HTTPException) as error:
        method(*args)
    assert error.value.status_code == status
    assert "author_member_id = %s" in cursor.queries[0][0]
    connection.commit.assert_not_called()
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()


def test_create_post_response_failure_rolls_back(database):
    _, connection, _ = database(
        [{"id": 1}, {"post_id": 2}, RuntimeError("response read failure")]
    )
    with pytest.raises(RuntimeError):
        service.create_post(1, "제목", "본문", 1)
    connection.commit.assert_not_called()
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()


def test_create_post_single_transaction(database):
    images = [
        dict(
            stored_name="posts/a.png",
            original_name="a.png",
            content_type="image/png",
            file_size=12,
        )
    ]
    cursor, connection, factory = database(
        [{"id": 1}, {"post_id": 2}, None, post_row(2), []]
    )
    result = service.create_post(1, "제목", "본문", 1, images)
    assert result["id"] == 2 and result["images"] == []
    assert cursor.queries[2][1][-1] == 0
    factory.assert_called_once()
    connection.commit.assert_called_once()
    connection.rollback.assert_not_called()
    connection.close.assert_called_once()


def test_commit_failure_rolls_back(database):
    _, connection, _ = database([None])
    connection.commit.side_effect = RuntimeError("commit failed")
    with pytest.raises(RuntimeError):
        service.delete_post(1, 2, 1)
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()


def session_cookie(member_id=1, discord_id="discord-user"):
    data = b64encode(
        json.dumps(dict(member_id=member_id, user=dict(discord_id=discord_id))).encode()
    )
    return TimestampSigner("isolated-test-secret").sign(data).decode()


@pytest.mark.parametrize(
    "env,header,status",
    [
        ("production", None, 401),
        ("production", "1", 401),
        ("test", None, 401),
        ("test", "bad", 422),
    ],
)
def test_real_auth_rejects_missing_or_bad_headers(monkeypatch, env, header, status):
    monkeypatch.setenv("APP_ENV", env)
    with TestClient(app) as client:
        response = client.get(
            "/api/boards", headers={"X-Dev-Member-ID": header} if header else {}
        )
    assert response.status_code == status


def test_real_auth_missing_member(database):
    database([None])
    with TestClient(app) as client:
        assert (
            client.get("/api/boards", headers={"X-Dev-Member-ID": "999"}).status_code
            == 401
        )


def test_real_auth_valid_dev_member(database):
    cursor, _, _ = database([{"exists": 1}, []])
    with TestClient(app) as client:
        response = client.get("/api/boards", headers={"X-Dev-Member-ID": "1"})
    assert response.status_code == 200 and response.json() == []
    assert cursor.queries[0][1] == (1,)


def test_real_signed_session_precedes_dev_header(database, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    cursor, _, _ = database([{"exists": 1}, []])
    with TestClient(app) as client:
        client.cookies.set("playmate_session", session_cookie())
        response = client.get("/api/boards", headers={"X-Dev-Member-ID": "99"})
    assert response.status_code == 200
    assert cursor.queries[0][1] == (1, "discord-user")


@pytest.mark.parametrize(
    "cookie", [session_cookie(member_id="1"), session_cookie() + "tampered"]
)
def test_invalid_session_rejected(monkeypatch, cookie):
    monkeypatch.setenv("APP_ENV", "production")
    with TestClient(app) as client:
        client.cookies.set("playmate_session", cookie)
        assert client.get("/api/boards").status_code == 401


def test_session_member_discord_mismatch_rejected(database, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    database([None])
    with TestClient(app) as client:
        client.cookies.set("playmate_session", session_cookie())
        assert client.get("/api/boards").status_code == 401


def test_http_posts_uses_service_repository(client, database):
    database([{"id": 1}, [post_row()], []])
    response = client.get("/api/boards/1/posts?q=검색&sort=latest")
    assert response.status_code == 200
    assert response.json()[0]["images"] == []
    assert response.json()[0]["comment_count"] == 2
    assert response.json()[0]["body"] == "본문"


def test_http_missing_post_and_bad_sort(client, database):
    database([None])
    assert client.get("/api/boards/1/posts/999").status_code == 404
    assert client.get("/api/boards/1/posts?sort=oldest").status_code == 422
    assert client.get("/api/boards/1/posts?q=" + "a" * 101).status_code == 422


def test_http_wrong_owner(client, database):
    database([None, {"exists": 1}], rowcount=0)
    assert (
        client.patch(
            "/api/boards/1/posts/2", json={"title": "수정", "body": "본문"}
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "method,url,payload,results,status",
    [
        ("get", "/api/boards/1/posts/2", None, [post_row(2), []], 200),
        (
            "patch",
            "/api/boards/1/posts/2",
            {"title": "수정", "body": "본문"},
            [None, post_row(2), []],
            200,
        ),
        ("delete", "/api/boards/1/posts/2", None, [None], 204),
        (
            "post",
            "/api/boards",
            {"name": "새 게시판"},
            [
                {"board_id": 2},
                {"id": 2, "name": "새 게시판", "description": None, "created_at": NOW},
            ],
            201,
        ),
    ],
)
def test_http_successful_mutations_and_detail(
    client, database, method, url, payload, results, status
):
    """HTTP→Service→Repository를 통과하는 정상 응답·커밋을 검증한다."""
    _, connection, _ = database(results)
    response = client.request(
        method.upper(), url, **({"json": payload} if payload else {})
    )
    assert response.status_code == status
    if method in {"post", "patch", "delete"}:
        connection.commit.assert_called_once()
    else:
        connection.commit.assert_not_called()
    if status == 204:
        assert response.content == b""


@pytest.mark.parametrize(
    "method,results,status",
    [
        ("post", [{"exists": 1}, {"comment_id": 3}, "comment"], 201),
        ("patch", [None, "comment"], 200),
        ("delete", [None], 204),
        ("get", [{"exists": 1}, ["comment"]], 200),
    ],
)
def test_http_comment_service_repository(client, database, method, results, status):
    """댓글 생성·목록·수정·논리 삭제의 기존 HTTP 계약을 검증한다."""
    comment = dict(
        id=3,
        post_id=2,
        body="댓글",
        author_id=1,
        author_name="닉네임",
        created_at=NOW,
        updated_at=NOW,
        is_owner=True,
    )
    results = [
        comment if row == "comment" else [comment] if row == ["comment"] else row
        for row in results
    ]
    cursor, connection, _ = database(results)
    url = (
        "/api/boards/1/posts/2/comments"
        if method in {"post", "get"}
        else "/api/comments/3"
    )
    response = client.request(
        method.upper(),
        url,
        **({"json": {"body": "댓글"}} if method in {"post", "patch"} else {}),
    )
    assert response.status_code == status
    if method != "get":
        connection.commit.assert_called_once()
    if method == "delete":
        assert "SET deleted_at = CURRENT_TIMESTAMP" in cursor.queries[0][0]
    elif method == "get":
        assert response.json()[0]["id"] == 3
    else:
        assert response.json()["id"] == 3


def like_row(post_id=2, like_count=1, liked_by_me=True):
    return dict(post_id=post_id, like_count=like_count, liked_by_me=liked_by_me)


def test_like_post_single_transaction(database):
    cursor, connection, factory = database([{"exists": 1}, None, like_row()])
    assert service.like_post(1, 2, 1) == like_row()
    sql, params = cursor.queries[1]
    assert "INSERT INTO post_likes (post_id, member_id)" in sql
    assert "ON CONFLICT (post_id, member_id) DO NOTHING" in sql
    assert params == (2, 1)
    assert cursor.queries[2][1] == (2, 1, 2)
    factory.assert_called_once()
    connection.commit.assert_called_once()
    connection.rollback.assert_not_called()
    connection.close.assert_called_once()


def test_duplicate_like_keeps_single_row(database):
    """이미 좋아요한 글은 기본키 충돌을 무시하므로 오류 없이 같은 상태를 반환한다."""
    cursor, connection, _ = database([{"exists": 1}, None, like_row(like_count=1)])
    assert service.like_post(1, 2, 1)["like_count"] == 1
    assert "ON CONFLICT (post_id, member_id) DO NOTHING" in cursor.queries[1][0]
    connection.commit.assert_called_once()


def test_unlike_post_without_existing_like(database):
    """좋아요가 없는 상태에서 취소해도 DELETE 0건으로 성공한다."""
    cursor, connection, _ = database(
        [{"exists": 1}, None, like_row(like_count=0, liked_by_me=False)], rowcount=0
    )
    assert service.unlike_post(1, 2, 1) == like_row(like_count=0, liked_by_me=False)
    sql, params = cursor.queries[1]
    assert "DELETE FROM post_likes" in sql and params == (2, 1)
    connection.commit.assert_called_once()


def test_like_count_increases_and_decreases(database):
    database([{"exists": 1}, None, like_row(like_count=3)])
    assert service.like_post(1, 2, 1)["like_count"] == 3
    database([{"exists": 1}, None, like_row(like_count=2, liked_by_me=False)])
    response = service.unlike_post(1, 2, 1)
    assert response["like_count"] == 2 and response["liked_by_me"] is False


def test_different_members_like_same_post(database):
    first, _, _ = database([{"exists": 1}, None, like_row(like_count=1)])
    service.like_post(1, 2, 1)
    second, _, _ = database([{"exists": 1}, None, like_row(like_count=2)])
    assert service.like_post(1, 2, 7)["like_count"] == 2
    assert first.queries[1][1] == (2, 1) and second.queries[1][1] == (2, 7)


@pytest.mark.parametrize("method", [service.like_post, service.unlike_post])
def test_like_missing_or_deleted_post_rolls_back(database, method):
    """없는 글·삭제된 글·모임 글은 게시글 확인에서 404이며 좋아요를 변경하지 않는다."""
    cursor, connection, _ = database([None])
    with pytest.raises(HTTPException) as error:
        method(1, 999, 1)
    assert error.value.status_code == 404
    sql, params = cursor.queries[0]
    assert "p.deleted_at IS NULL" in sql and "NOT EXISTS" in sql
    assert params == (1, 999) and len(cursor.queries) == 1
    connection.commit.assert_not_called()
    connection.rollback.assert_called_once()


def test_get_post_includes_like_fields(database):
    cursor, _, _ = database([dict(post_row(2), like_count=5, liked_by_me=True), []])
    response = service.get_post(1, 2, 3)
    assert response["like_count"] == 5 and response["liked_by_me"] is True
    sql, params = cursor.queries[0]
    assert "FROM post_likes AS l WHERE l.post_id = p.post_id" in sql
    assert params == (3, 3, 3, 1, 2)


@pytest.mark.parametrize(
    "method,liked",
    [("put", True), ("delete", False)],
)
def test_http_like_service_repository(client, database, method, liked):
    """좋아요 등록·취소의 HTTP→Service→Repository 계약과 커밋을 검증한다."""
    row = like_row(like_count=1 if liked else 0, liked_by_me=liked)
    _, connection, _ = database([{"exists": 1}, None, row])
    response = client.request(method.upper(), "/api/boards/1/posts/2/like")
    assert response.status_code == 200 and response.json() == row
    connection.commit.assert_called_once()


def test_http_like_missing_post(client, database):
    database([None])
    assert client.request("PUT", "/api/boards/1/posts/999/like").status_code == 404


def test_http_post_detail_like_fields(client, database):
    database([dict(post_row(2), like_count=1, liked_by_me=False), []])
    response = client.get("/api/boards/1/posts/2")
    assert response.status_code == 200
    assert response.json()["like_count"] == 1
    assert response.json()["liked_by_me"] is False


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_real_auth_rejects_unauthenticated_like(monkeypatch, method):
    monkeypatch.setenv("APP_ENV", "production")
    with TestClient(app) as client:
        response = client.request(method, "/api/boards/1/posts/2/like")
    assert response.status_code == 401


def scrap_row(post_id=2, scrapped_by_me=True):
    return dict(post_id=post_id, scrapped_by_me=scrapped_by_me)


def test_scrap_post_single_transaction(database):
    cursor, connection, factory = database([{"exists": 1}, None, scrap_row()])
    assert service.scrap_post(1, 2, 1) == scrap_row()
    sql, params = cursor.queries[1]
    assert "INSERT INTO post_scraps (post_id, member_id)" in sql
    assert "ON CONFLICT (post_id, member_id) DO NOTHING" in sql
    assert params == (2, 1)
    assert cursor.queries[2][1] == (2, 2, 1)
    factory.assert_called_once()
    connection.commit.assert_called_once()
    connection.rollback.assert_not_called()
    connection.close.assert_called_once()


def test_duplicate_scrap_keeps_single_row(database):
    """이미 스크랩한 글은 기본키 충돌을 무시하므로 오류 없이 같은 상태를 반환한다."""
    cursor, connection, _ = database([{"exists": 1}, None, scrap_row()])
    assert service.scrap_post(1, 2, 1)["scrapped_by_me"] is True
    assert "ON CONFLICT (post_id, member_id) DO NOTHING" in cursor.queries[1][0]
    connection.commit.assert_called_once()


def test_unscrap_post_without_existing_scrap(database):
    """스크랩이 없는 상태에서 취소해도 DELETE 0건으로 성공한다."""
    cursor, connection, _ = database(
        [{"exists": 1}, None, scrap_row(scrapped_by_me=False)], rowcount=0
    )
    assert service.unscrap_post(1, 2, 1) == scrap_row(scrapped_by_me=False)
    sql, params = cursor.queries[1]
    assert "DELETE FROM post_scraps" in sql and params == (2, 1)
    connection.commit.assert_called_once()


def test_different_members_scrap_same_post(database):
    first, _, _ = database([{"exists": 1}, None, scrap_row()])
    service.scrap_post(1, 2, 1)
    second, _, _ = database([{"exists": 1}, None, scrap_row()])
    assert service.scrap_post(1, 2, 7)["scrapped_by_me"] is True
    assert first.queries[1][1] == (2, 1) and second.queries[1][1] == (2, 7)
    assert first.queries[2][1] == (2, 2, 1) and second.queries[2][1] == (2, 2, 7)


@pytest.mark.parametrize("method", [service.scrap_post, service.unscrap_post])
def test_scrap_missing_or_deleted_post_rolls_back(database, method):
    """없는 글·삭제된 글·모임 글은 게시글 확인에서 404이며 스크랩을 변경하지 않는다."""
    cursor, connection, _ = database([None])
    with pytest.raises(HTTPException) as error:
        method(1, 999, 1)
    assert error.value.status_code == 404
    sql, params = cursor.queries[0]
    assert "p.deleted_at IS NULL" in sql and "NOT EXISTS" in sql
    assert params == (1, 999) and len(cursor.queries) == 1
    connection.commit.assert_not_called()
    connection.rollback.assert_called_once()


@pytest.mark.parametrize("scrapped", [True, False])
def test_get_post_includes_scrap_field(database, scrapped):
    cursor, _, _ = database([dict(post_row(2), scrapped_by_me=scrapped), []])
    assert service.get_post(1, 2, 3)["scrapped_by_me"] is scrapped
    sql, _ = cursor.queries[0]
    assert "FROM post_scraps AS s WHERE s.post_id = p.post_id" in sql


def test_list_posts_does_not_query_scraps(database):
    """목록은 스크랩 여부를 계산하지 않아 기존 SQL·바인딩을 유지한다."""
    cursor, _, _ = database([{"id": 1}, [post_row()], []])
    assert service.list_posts(1, None, "latest", 1)[0]["id"] == 1
    assert all("post_scraps" not in sql for sql, _ in cursor.queries)


@pytest.mark.parametrize(
    "method,scrapped",
    [("put", True), ("delete", False)],
)
def test_http_scrap_service_repository(client, database, method, scrapped):
    """스크랩 등록·취소의 HTTP→Service→Repository 계약과 커밋을 검증한다."""
    row = scrap_row(scrapped_by_me=scrapped)
    _, connection, _ = database([{"exists": 1}, None, row])
    response = client.request(method.upper(), "/api/boards/1/posts/2/scrap")
    assert response.status_code == 200 and response.json() == row
    connection.commit.assert_called_once()


def test_http_scrap_missing_post(client, database):
    database([None])
    assert client.request("PUT", "/api/boards/1/posts/999/scrap").status_code == 404


def test_http_post_detail_and_list_scrap_fields(client, database):
    database([dict(post_row(2), scrapped_by_me=True), []])
    assert client.get("/api/boards/1/posts/2").json()["scrapped_by_me"] is True
    database([{"id": 1}, [post_row()], []])
    assert client.get("/api/boards/1/posts").json()[0]["scrapped_by_me"] is None


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_real_auth_rejects_unauthenticated_scrap(monkeypatch, method):
    monkeypatch.setenv("APP_ENV", "production")
    with TestClient(app) as client:
        response = client.request(method, "/api/boards/1/posts/2/scrap")
    assert response.status_code == 401


def comment_row(comment_id=5, parent_comment_id=3, **changes):
    return dict(
        dict(
            id=comment_id,
            post_id=2,
            parent_comment_id=parent_comment_id,
            body="답글",
            author_id=1,
            author_name="닉네임",
            created_at=NOW,
            updated_at=NOW,
            is_owner=True,
        ),
        **changes,
    )


def test_create_top_level_comment_skips_parent_check(database):
    """일반 댓글은 부모 조회 없이 parent_comment_id NULL로 저장한다."""
    row = comment_row(3, None, body="댓글")
    cursor, connection, _ = database([{"exists": 1}, {"comment_id": 3}, row])
    assert service.create_comment(1, 2, "댓글", 1) == row
    assert len(cursor.queries) == 3
    sql, params = cursor.queries[1]
    assert "INSERT INTO comments (post_id, author_member_id, body, parent_comment_id)" in sql
    assert params == (2, 1, "댓글", None)
    connection.commit.assert_called_once()


def test_create_reply_validates_parent_in_same_transaction(database):
    cursor, connection, factory = database(
        [
            {"exists": 1},
            {"post_id": 2, "parent_comment_id": None},
            {"comment_id": 5},
            comment_row(),
        ]
    )
    assert service.create_comment(1, 2, "답글", 1, 3)["parent_comment_id"] == 3
    sql, params = cursor.queries[1]
    assert "FROM comments WHERE comment_id = %s AND deleted_at IS NULL" in sql
    assert params == (3,)
    assert cursor.queries[2][1] == (2, 1, "답글", 3)
    factory.assert_called_once()
    connection.commit.assert_called_once()
    connection.rollback.assert_not_called()


@pytest.mark.parametrize(
    "parent,status",
    [
        (None, 404),
        ({"post_id": 9, "parent_comment_id": None}, 404),
        ({"post_id": 2, "parent_comment_id": 1}, 422),
    ],
    ids=["missing_or_deleted_parent", "other_post_parent", "reply_to_reply"],
)
def test_invalid_reply_parent_rolls_back(database, parent, status):
    """없는·삭제된·다른 글의 부모와 대댓글의 대댓글은 저장하지 않는다."""
    cursor, connection, _ = database([{"exists": 1}, parent])
    with pytest.raises(HTTPException) as error:
        service.create_comment(1, 2, "답글", 1, 3)
    assert error.value.status_code == status
    assert len(cursor.queries) == 2
    assert all("INSERT INTO comments" not in sql for sql, _ in cursor.queries)
    connection.commit.assert_not_called()
    connection.rollback.assert_called_once()


def test_list_comments_keeps_deleted_parent_with_replies(database):
    """삭제된 부모는 살아 있는 대댓글이 있을 때만 본문·작성자를 비운 행으로 남긴다."""
    rows = [
        comment_row(
            3, None, body="", author_id=None, author_name="", is_owner=False,
            is_deleted=True,
        ),
        comment_row(5, 3),
    ]
    cursor, _, _ = database([{"exists": 1}, rows])
    assert service.list_comments(1, 2, 1) == rows
    sql, params = cursor.queries[1]
    assert params == (1, 2)
    assert "CASE WHEN c.deleted_at IS NULL THEN c.body ELSE '' END AS body" in sql
    assert "(c.deleted_at IS NULL AND c.author_member_id = %s) AS is_owner" in sql
    assert "r.parent_comment_id = c.comment_id AND r.deleted_at IS NULL" in sql
    assert (
        "ORDER BY COALESCE(parent.created_at, c.created_at), "
        "COALESCE(parent.comment_id, c.comment_id), "
        "c.parent_comment_id IS NOT NULL, c.created_at, c.comment_id"
    ) in sql


def test_delete_parent_comment_does_not_touch_replies(database):
    """부모 삭제는 기존처럼 해당 댓글 한 건만 논리 삭제한다."""
    cursor, connection, _ = database([None])
    service.delete_comment(3, 1)
    sql, params = cursor.queries[0]
    assert "SET deleted_at = CURRENT_TIMESTAMP" in sql
    assert "WHERE comment_id = %s AND author_member_id = %s" in sql
    assert "parent_comment_id" not in sql and params == (3, 1)
    connection.commit.assert_called_once()


def test_comment_count_includes_replies(database):
    """댓글 수는 기존처럼 삭제되지 않은 댓글·대댓글을 모두 센다."""
    cursor, _, _ = database([dict(post_row(2), comment_count=5), []])
    assert service.get_post(1, 2, 1)["comment_count"] == 5
    sql, _ = cursor.queries[0]
    assert "FROM comments AS c WHERE c.post_id = p.post_id AND c.deleted_at IS NULL" in sql
    assert "parent_comment_id" not in sql


@pytest.mark.parametrize(
    "method,payload,results,status",
    [
        (
            "post",
            {"body": "답글", "parent_comment_id": 3},
            [{"exists": 1}, {"post_id": 2, "parent_comment_id": None},
             {"comment_id": 5}, "reply"],
            201,
        ),
        (
            "post",
            {"body": "답글", "parent_comment_id": 5},
            [{"exists": 1}, {"post_id": 2, "parent_comment_id": 3}],
            422,
        ),
        ("patch", {"body": "수정 답글"}, [None, "reply"], 200),
        ("patch", {"body": "수정", "parent_comment_id": 3}, [], 422),
        ("delete", None, [None], 204),
    ],
    ids=["create_reply", "reply_to_reply", "update_reply", "move_reply", "delete_reply"],
)
def test_http_reply_service_repository(client, database, method, payload, results, status):
    """대댓글 작성·수정·삭제가 기존 댓글 HTTP 계약과 권한 흐름을 따른다."""
    results = [comment_row() if row == "reply" else row for row in results]
    _, connection, _ = database(results)
    url = "/api/boards/1/posts/2/comments" if method == "post" else "/api/comments/5"
    response = client.request(
        method.upper(), url, **({"json": payload} if payload else {})
    )
    assert response.status_code == status
    if status in {200, 201}:
        assert response.json()["parent_comment_id"] == 3
        assert response.json()["is_deleted"] is False
    if status < 400:
        connection.commit.assert_called_once()
    else:
        connection.commit.assert_not_called()


def test_http_reply_owner_failure_returns_403(client, database):
    """다른 회원의 대댓글 수정은 기존 작성자 권한 규칙대로 403이다."""
    _, connection, _ = database([None, {"exists": 1}], rowcount=0)
    response = client.patch("/api/comments/5", json={"body": "남의 답글"})
    assert response.status_code == 403
    connection.rollback.assert_called_once()


def test_http_list_deleted_parent_placeholder(client, database):
    rows = [
        comment_row(
            3, None, body="", author_id=None, author_name="", is_owner=False,
            is_deleted=True,
        ),
        comment_row(5, 3),
    ]
    database([{"exists": 1}, rows])
    response = client.get("/api/boards/1/posts/2/comments")
    assert response.status_code == 200
    parent, reply = response.json()
    assert parent["is_deleted"] is True and parent["body"] == ""
    assert parent["author_id"] is None and parent["is_owner"] is False
    assert reply["parent_comment_id"] == 3 and reply["is_deleted"] is False


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_real_auth_rejects_unauthenticated_reply(monkeypatch, method):
    monkeypatch.setenv("APP_ENV", "production")
    url = "/api/boards/1/posts/2/comments" if method == "POST" else "/api/comments/5"
    with TestClient(app) as client:
        response = client.request(
            method, url, json={"body": "답글", "parent_comment_id": 3}
        )
    assert response.status_code == 401


def test_http_duplicate_board_rolls_back(client, database):
    from psycopg2.errors import UniqueViolation

    _, connection, _ = database([UniqueViolation("duplicate")])
    assert client.post("/api/boards", json={"name": "중복 게시판"}).status_code == 409
    connection.rollback.assert_called_once()
    connection.commit.assert_not_called()


def test_http_response_query_failure_cleans_upload_and_rolls_back(
    client, database, tmp_path, monkeypatch
):
    from app.core import uploads

    monkeypatch.setattr(uploads, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(uploads, "UPLOAD_DIR", tmp_path / "uploads" / "posts")
    _, connection, _ = database(
        [{"id": 1}, {"post_id": 2}, None, RuntimeError("response read failed")]
    )
    response = client.post(
        "/api/boards/1/posts",
        data={"title": "제목", "body": "본문"},
        files={"images": ("image.png", b"\x89PNG\r\n\x1a\nexample", "image/png")},
    )
    assert response.status_code == 503
    connection.rollback.assert_called_once()
    connection.commit.assert_not_called()
    assert not list(uploads.UPLOAD_DIR.glob("*"))


def test_connection_failure_does_not_disclose_diagnostic(monkeypatch):
    """DB 드라이버 진단은 서버 로그에 남기고 클라이언트 예외에서는 숨긴다."""
    from psycopg2 import OperationalError

    monkeypatch.setattr(
        db_connect.psycopg2,
        "connect",
        Mock(side_effect=OperationalError("private-host private-user")),
    )
    with pytest.raises(RuntimeError) as error:
        db_connect.get_connection()
    assert str(error.value) == "PostgreSQL 연결에 실패했습니다."


@pytest.mark.parametrize("rollback_fails", [False, True])
def test_http_commit_disconnect_preserves_upload(
    client, database, tmp_path, monkeypatch, rollback_fails
):
    """COMMIT 응답 유실 시 이미 저장됐을 수 있는 DB 참조 파일을 삭제하지 않는다."""
    from app.core import uploads
    from psycopg2 import InterfaceError, OperationalError

    monkeypatch.setattr(uploads, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(uploads, "UPLOAD_DIR", tmp_path / "uploads" / "posts")
    _, connection, _ = database([{"id": 1}, {"post_id": 2}, None, post_row(2), []])
    connection.commit.side_effect = OperationalError("commit acknowledgement lost")
    if rollback_fails:
        connection.rollback.side_effect = InterfaceError("connection closed")
    response = client.post(
        "/api/boards/1/posts",
        data={"title": "제목", "body": "본문"},
        files={"images": ("image.png", b"\x89PNG\r\n\x1a\nexample", "image/png")},
    )
    assert response.status_code == 503
    assert len(list(uploads.UPLOAD_DIR.glob("*"))) == 1
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()


def test_http_confirmed_commit_close_failure_preserves_upload(
    client, database, tmp_path, monkeypatch
):
    """커밋 성공 후 연결 종료 오류가 저장된 이미지 삭제로 이어지지 않아야 한다."""
    from app.core import uploads
    from psycopg2 import InterfaceError

    monkeypatch.setattr(uploads, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(uploads, "UPLOAD_DIR", tmp_path / "uploads" / "posts")
    _, connection, _ = database([{"id": 1}, {"post_id": 2}, None, post_row(2), []])
    connection.close.side_effect = InterfaceError("close failed")
    response = client.post(
        "/api/boards/1/posts",
        data={"title": "제목", "body": "본문"},
        files={"images": ("image.png", b"\x89PNG\r\n\x1a\nexample", "image/png")},
    )
    assert response.status_code == 201
    assert len(list(uploads.UPLOAD_DIR.glob("*"))) == 1
    connection.commit.assert_called_once()
    connection.rollback.assert_not_called()


def test_http_known_commit_rejection_cleans_upload(
    client, database, tmp_path, monkeypatch
):
    """서버 SQLSTATE로 확인된 커밋 거부는 결과 불명확 오류로 분류하지 않는다."""
    from app.core import uploads
    from psycopg2 import OperationalError

    class RejectedCommit(OperationalError):
        pgcode = "40001"

    monkeypatch.setattr(uploads, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(uploads, "UPLOAD_DIR", tmp_path / "uploads" / "posts")
    _, connection, _ = database([{"id": 1}, {"post_id": 2}, None, post_row(2), []])
    connection.commit.side_effect = RejectedCommit("server rejected commit")
    with pytest.raises(RejectedCommit):
        client.post(
            "/api/boards/1/posts",
            data={"title": "제목", "body": "본문"},
            files={"images": ("image.png", b"\x89PNG\r\n\x1a\nexample", "image/png")},
        )
    assert not list(uploads.UPLOAD_DIR.glob("*"))
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()
