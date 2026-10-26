"""모임 좋아요·스크랩·댓글(대댓글) Service와 HTTP 인증을 DB 없이 검증한다.

Repository 함수를 가짜로 바꾸고 Mock 세션으로 commit/rollback 호출을 확인한다.
실제 SQL·중복 방지·정렬은 tests/integration/test_postgres_recruit_social.py에서 검증한다.
"""

from base64 import b64encode
from datetime import datetime
import json
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import HTTPException
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
import pytest

from app.main import app
from backend.app.core.database import get_db
from backend.app.repositories import recruit as recruit_repo
from backend.app.schemas.recruit import RecruitCommentCreate, RecruitCommentUpdate
from backend.app.services import recruit as recruit_service
from backend.app.services import recruit_comment as comment_service
from backend.app.services import recruit_reaction as reaction_service

NOW = datetime(2026, 1, 1, 12, 0)
POST = SimpleNamespace(post_id=20)
RECRUIT = SimpleNamespace(recruit_id=7)


@pytest.fixture
def repo(monkeypatch):
    """모임이 존재하는 상태의 Repository 대역. 호출 기록을 calls에 남긴다."""
    calls = []
    state = {"liked": False, "scrapped": False, "likes": 0}

    def record(name, result=None):
        def fake(*args):
            calls.append((name, args[1:]))
            return result(*args) if callable(result) else result
        return fake

    monkeypatch.setattr(recruit_repo, "find_recruit_with_post", lambda db, rid: (POST, RECRUIT))
    monkeypatch.setattr(recruit_repo, "add_post_like", record("add_post_like"))
    monkeypatch.setattr(recruit_repo, "delete_post_like", record("delete_post_like"))
    monkeypatch.setattr(recruit_repo, "add_post_scrap", record("add_post_scrap"))
    monkeypatch.setattr(recruit_repo, "delete_post_scrap", record("delete_post_scrap"))
    monkeypatch.setattr(recruit_repo, "count_post_likes", lambda db, post_id: state["likes"])
    monkeypatch.setattr(recruit_repo, "has_post_like", lambda db, post_id, member_id: state["liked"])
    monkeypatch.setattr(recruit_repo, "has_post_scrap", lambda db, post_id, member_id: state["scrapped"])
    return SimpleNamespace(calls=calls, state=state)


# =========================================================
# 좋아요·스크랩
# =========================================================
def test_like_saves_and_returns_state_in_one_transaction(repo):
    db = Mock()
    repo.state.update(liked=True, likes=1)
    assert reaction_service.like_recruit(db, 7, 3) == {
        "recruit_id": 7, "like_count": 1, "liked_by_me": True,
    }
    assert repo.calls == [("add_post_like", (20, 3))]
    db.commit.assert_called_once()
    db.rollback.assert_not_called()


def test_repeated_like_and_unlike_keep_final_state(repo):
    """같은 요청을 반복해도 Repository의 중복 무시·0건 삭제에 기대어 오류 없이 같은 상태를 반환한다."""
    db = Mock()
    repo.state.update(liked=True, likes=1)
    first = reaction_service.like_recruit(db, 7, 3)
    second = reaction_service.like_recruit(db, 7, 3)
    assert first == second
    repo.state.update(liked=False, likes=0)
    assert reaction_service.unlike_recruit(db, 7, 3) == reaction_service.unlike_recruit(db, 7, 3)
    assert [name for name, _ in repo.calls] == [
        "add_post_like", "add_post_like", "delete_post_like", "delete_post_like",
    ]
    assert db.commit.call_count == 4


@pytest.mark.parametrize(
    "method,expected",
    [
        (reaction_service.scrap_recruit, ("add_post_scrap", True)),
        (reaction_service.unscrap_recruit, ("delete_post_scrap", False)),
    ],
)
def test_scrap_and_unscrap(repo, method, expected):
    db = Mock()
    name, scrapped = expected
    repo.state.update(scrapped=scrapped)
    assert method(db, 7, 3) == {"recruit_id": 7, "scrapped_by_me": scrapped}
    assert repo.calls == [(name, (20, 3))]
    db.commit.assert_called_once()


@pytest.mark.parametrize(
    "method",
    [
        reaction_service.like_recruit,
        reaction_service.unlike_recruit,
        reaction_service.scrap_recruit,
        reaction_service.unscrap_recruit,
    ],
)
def test_missing_or_deleted_recruit_rolls_back(repo, monkeypatch, method):
    """삭제된 모임은 find_recruit_with_post가 None이므로 404이며 아무것도 저장하지 않는다."""
    monkeypatch.setattr(recruit_repo, "find_recruit_with_post", lambda db, rid: None)
    db = Mock()
    with pytest.raises(HTTPException) as error:
        method(db, 999, 3)
    assert error.value.status_code == 404
    assert repo.calls == []
    db.commit.assert_not_called()
    db.rollback.assert_called_once()


def test_like_db_error_rolls_back(repo, monkeypatch):
    def broken(*args):
        raise RuntimeError("db write failed")

    monkeypatch.setattr(recruit_repo, "add_post_like", broken)
    db = Mock()
    with pytest.raises(RuntimeError):
        reaction_service.like_recruit(db, 7, 3)
    db.commit.assert_not_called()
    db.rollback.assert_called_once()


# =========================================================
# 모임 상세·목록 응답
# =========================================================
@pytest.fixture
def detail_repo(repo, monkeypatch):
    recruit = SimpleNamespace(
        recruit_id=7, category="study", capacity=5, state="OPEN", recruit_mode="short",
        deadline_at=NOW, regular_days=None, regular_time=None, meeting_start=NOW,
        regular_start_date=None, meeting_end=NOW, place=None, is_online=True,
        contact_method=None,
    )
    post = SimpleNamespace(post_id=20, title="스터디", body="본문")
    monkeypatch.setattr(recruit_repo, "find_recruit_with_post", lambda db, rid: (post, recruit))
    monkeypatch.setattr(recruit_repo, "get_category_detail", lambda db, model, rid: None)
    return repo


def test_get_recruit_includes_like_and_scrap_for_login_member(detail_repo):
    detail_repo.state.update(liked=True, scrapped=True, likes=4)
    result = recruit_service.get_recruit(Mock(), 7, 3)
    assert (result["like_count"], result["liked_by_me"], result["scrapped_by_me"]) == (4, True, True)
    assert result["title"] == "스터디" and result["detail"] == {}


def test_get_recruit_without_login_is_false_and_keeps_existing_fields(detail_repo):
    detail_repo.state.update(liked=True, scrapped=True, likes=4)
    result = recruit_service.get_recruit(Mock(), 7)
    assert (result["like_count"], result["liked_by_me"], result["scrapped_by_me"]) == (4, False, False)
    assert {"recruit_id", "title", "body", "category", "capacity", "state", "detail"} <= set(result)


def test_get_recruits_adds_like_count(monkeypatch):
    post = SimpleNamespace(post_id=20, title="스터디", body="본문", view_count=0)
    recruit = SimpleNamespace(
        recruit_id=7, category="study", capacity=5, state="OPEN", recruit_mode="short",
        deadline_at=NOW, regular_days=None, regular_time=None, regular_start_date=None,
        meeting_start=NOW, meeting_end=NOW,
    )
    monkeypatch.setattr(
        recruit_repo, "list_recruits_with_posts", lambda db, category=None: [(post, recruit, 2, 3)]
    )
    row = recruit_service.get_recruits(Mock())[0]
    assert row["participant_count"] == 2 and row["like_count"] == 3
    assert "liked_by_me" not in row and "scrapped_by_me" not in row


# =========================================================
# 댓글·대댓글
# =========================================================
def comment(comment_id, parent=None, author=1, deleted=False, post_id=20):
    return SimpleNamespace(
        comment_id=comment_id, post_id=post_id, parent_comment_id=parent,
        author_member_id=author, body=f"댓글{comment_id}", created_at=NOW,
        updated_at=NOW, deleted_at=NOW if deleted else None,
    )


def test_get_comments_orders_parent_then_replies_and_keeps_placeholder(repo, monkeypatch):
    """작성 순서(A, B, A-1, B-1, A-2)로 읽어도 부모 → 대댓글 순서로 묶는다."""
    rows = [
        (comment(1, deleted=True, author=3), "민혁"),   # A (삭제됨, 대댓글 있음)
        (comment(2), "효원"),                            # B
        (comment(3, parent=1, author=3), "민혁"),        # A-1
        (comment(4, parent=2), "효원"),                  # B-1
        (comment(5, parent=1, deleted=True), "효원"),    # A-2 (삭제됨)
        (comment(6, parent=1), "효원"),                  # A-3
        (comment(7, deleted=True), "효원"),              # C (삭제됨, 대댓글 없음)
    ]
    monkeypatch.setattr(recruit_repo, "list_post_comments", lambda db, post_id: rows)
    result = comment_service.get_comments(Mock(), 7, 3)
    assert [c["comment_id"] for c in result] == [1, 3, 6, 2, 4]
    placeholder = result[0]
    assert placeholder["is_deleted"] is True and placeholder["body"] == ""
    assert placeholder["author_id"] is None and placeholder["author_name"] == ""
    assert placeholder["is_owner"] is False
    assert result[1]["parent_comment_id"] == 1 and result[1]["is_owner"] is True
    assert result[3]["is_owner"] is False


@pytest.fixture
def comment_repo(repo, monkeypatch):
    added = []

    def add_comment(db, new_comment):
        new_comment.comment_id = 50
        new_comment.created_at = NOW
        new_comment.updated_at = NOW
        added.append(new_comment)
        return new_comment

    monkeypatch.setattr(recruit_repo, "add_comment", add_comment)
    monkeypatch.setattr(recruit_repo, "get_member_nickname", lambda db, member_id: "민혁")
    repo.added = added
    return repo


def test_create_reply_saves_parent_comment_id(comment_repo, monkeypatch):
    monkeypatch.setattr(recruit_repo, "get_active_comment", lambda db, cid: comment(1))
    db = Mock()
    result = comment_service.create_comment(
        db, 7, 3, RecruitCommentCreate(body=" 답글 ", parent_comment_id=1)
    )
    assert result["parent_comment_id"] == 1 and result["body"] == "답글"
    assert comment_repo.added[0].post_id == 20 and comment_repo.added[0].author_member_id == 3
    db.commit.assert_called_once()


def test_create_top_level_comment_skips_parent_check(comment_repo, monkeypatch):
    monkeypatch.setattr(recruit_repo, "get_active_comment", Mock(side_effect=AssertionError))
    db = Mock()
    result = comment_service.create_comment(db, 7, 3, RecruitCommentCreate(body="댓글"))
    assert result["parent_comment_id"] is None and result["is_deleted"] is False
    db.commit.assert_called_once()


@pytest.mark.parametrize(
    "parent,status",
    [
        (None, 404),                       # 없거나 삭제된 부모
        (comment(1, post_id=99), 404),     # 다른 모임·게시판의 댓글
        (comment(2, parent=1), 400),       # 대댓글의 대댓글
    ],
    ids=["missing_or_deleted_parent", "other_post_parent", "reply_to_reply"],
)
def test_invalid_parent_rolls_back_without_saving(comment_repo, monkeypatch, parent, status):
    monkeypatch.setattr(recruit_repo, "get_active_comment", lambda db, cid: parent)
    db = Mock()
    with pytest.raises(HTTPException) as error:
        comment_service.create_comment(
            db, 7, 3, RecruitCommentCreate(body="답글", parent_comment_id=1)
        )
    assert error.value.status_code == status
    assert comment_repo.added == []
    db.commit.assert_not_called()
    db.rollback.assert_called_once()


@pytest.mark.parametrize(
    "target,status",
    [(None, 404), (comment(9, post_id=99, author=3), 404), (comment(9, author=1), 403)],
    ids=["missing", "other_post", "not_author"],
)
@pytest.mark.parametrize("action", ["update", "delete"])
def test_update_delete_permission(comment_repo, monkeypatch, target, status, action):
    monkeypatch.setattr(recruit_repo, "get_active_comment", lambda db, cid: target)
    db = Mock()
    with pytest.raises(HTTPException) as error:
        if action == "update":
            comment_service.update_comment(db, 7, 9, 3, RecruitCommentUpdate(body="수정"))
        else:
            comment_service.delete_comment(db, 7, 9, 3)
    assert error.value.status_code == status
    db.commit.assert_not_called()
    db.rollback.assert_called_once()


def test_author_updates_and_deletes_reply(comment_repo, monkeypatch):
    reply = comment(9, parent=1, author=3)
    monkeypatch.setattr(recruit_repo, "get_active_comment", lambda db, cid: reply)
    db = Mock()
    result = comment_service.update_comment(db, 7, 9, 3, RecruitCommentUpdate(body="수정"))
    assert result["body"] == "수정" and result["parent_comment_id"] == 1
    assert comment_service.delete_comment(db, 7, 9, 3) == {"message": "댓글 삭제 완료"}
    assert reply.deleted_at is not None
    assert db.commit.call_count == 2


def test_comment_schemas():
    with pytest.raises(ValueError):
        RecruitCommentCreate(body="   ")
    # 수정 스키마에는 부모 댓글 필드가 없어 위치를 바꿀 수 없다.
    assert "parent_comment_id" not in RecruitCommentUpdate.model_fields


# =========================================================
# HTTP 인증 (기존 add_recruit와 같은 세션 방식)
# =========================================================
def session_cookie(member_id=3):
    data = b64encode(
        json.dumps(dict(member_id=member_id, user=dict(discord_id="discord-user"))).encode()
    )
    return TimestampSigner("isolated-test-secret").sign(data).decode()


@pytest.fixture
def http(monkeypatch):
    app.dependency_overrides[get_db] = lambda: Mock()
    seen = {}

    def fake(name):
        def service(db, recruit_id, *args):
            seen[name] = args
            return {"ok": name}
        return service

    for module, name in [
        (reaction_service, "like_recruit"), (reaction_service, "unlike_recruit"),
        (reaction_service, "scrap_recruit"), (reaction_service, "unscrap_recruit"),
        (comment_service, "get_comments"), (comment_service, "create_comment"),
        (comment_service, "update_comment"), (comment_service, "delete_comment"),
    ]:
        monkeypatch.setattr(module, name, fake(name))
    with TestClient(app) as client:
        yield client, seen
    app.dependency_overrides.clear()


WRITE_REQUESTS = [
    ("PUT", "/api/recruits/7/like", None),
    ("DELETE", "/api/recruits/7/like", None),
    ("PUT", "/api/recruits/7/scrap", None),
    ("DELETE", "/api/recruits/7/scrap", None),
    ("POST", "/api/recruits/7/comments", {"body": "댓글", "parent_comment_id": 1}),
    ("PATCH", "/api/recruits/7/comments/9", {"body": "수정"}),
    ("DELETE", "/api/recruits/7/comments/9", None),
]


@pytest.mark.parametrize("method,url,payload", WRITE_REQUESTS)
def test_write_requests_require_login(http, method, url, payload):
    client, seen = http
    response = client.request(method, url, **({"json": payload} if payload else {}))
    assert response.status_code == 401
    assert seen == {}


@pytest.mark.parametrize("method,url,payload", WRITE_REQUESTS)
def test_write_requests_use_session_member(http, method, url, payload):
    client, seen = http
    client.cookies.set("playmate_session", session_cookie(3))
    response = client.request(method, url, **({"json": payload} if payload else {}))
    assert response.status_code == (201 if method == "POST" else 200)
    (args,) = seen.values()
    assert 3 in args


def test_comment_list_is_public_and_uses_optional_member(http):
    client, seen = http
    assert client.get("/api/recruits/7/comments").status_code == 200
    assert seen["get_comments"] == (None,)
    client.cookies.set("playmate_session", session_cookie(3))
    client.get("/api/recruits/7/comments")
    assert seen["get_comments"] == (3,)
