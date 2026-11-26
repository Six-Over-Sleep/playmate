"""모임 댓글의 답글 대상(Issue #153) 저장·조회 규칙을 DB 없이 확인한다.

Repository 함수를 가짜로 바꾸고 Mock 세션으로 commit/rollback을 확인한다.
게시판·취업 댓글과 같은 오류 코드·저장값·응답 필드인지 본다.
실제 SQL·잠금·알림 받는 사람은 tests/integration/test_postgres_comment_reply.py에서 확인한다.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from backend.app.repositories import recruit as recruit_repo
from backend.app.schemas.recruit import RecruitCommentCreate, RecruitCommentUpdate
from backend.app.services import recruit_comment as service

NOW = datetime(2026, 11, 19, 12, 0)
NICKNAMES = {1: "원작성자", 3: "나", 4: "답글작성자", 6: "탈퇴한 사용자", 7: ""}


def comment(comment_id, parent=None, author=1, deleted=False, post_id=20, reply_to=None, anonymous=False):
    return SimpleNamespace(
        comment_id=comment_id, post_id=post_id, parent_comment_id=parent, reply_to_comment_id=reply_to,
        is_anonymous=anonymous, author_member_id=author, body=f"댓글{comment_id}",
        created_at=NOW, updated_at=NOW, deleted_at=NOW if deleted else None,
    )


@pytest.fixture
def repo(monkeypatch):
    state = SimpleNamespace(added=[], notified=[])

    def add_comment(db, new_comment):
        new_comment.comment_id = 50
        new_comment.created_at = new_comment.updated_at = NOW
        new_comment.is_anonymous = False
        state.added.append(new_comment)
        return new_comment

    monkeypatch.setattr(service, "get_recruit_post", lambda db, recruit_id: SimpleNamespace(post_id=20))
    monkeypatch.setattr(recruit_repo, "add_comment", add_comment)
    monkeypatch.setattr(recruit_repo, "get_member_nickname", lambda db, member_id: NICKNAMES.get(member_id))
    monkeypatch.setattr(service, "save_comment_notification",
                        lambda *args: state.notified.append(args) or 1)
    return state


def use_target(monkeypatch, target, root=None):
    monkeypatch.setattr(recruit_repo, "get_reply_target", lambda db, comment_id: (target, root))
    monkeypatch.setattr(recruit_repo, "get_active_comment", Mock(side_effect=AssertionError("기존 방식 검사 호출 안 됨")))


# =========================================================
# 작성
# =========================================================
def test_reply_to_reply_is_saved_under_root_with_server_computed_parent(repo, monkeypatch):
    use_target(monkeypatch, comment(5, parent=1, author=4), comment(1))
    db = Mock()
    result = service.create_comment(db, 7, 3, RecruitCommentCreate(body="답글", reply_to_comment_id=5))

    saved = repo.added[0]
    assert (saved.parent_comment_id, saved.reply_to_comment_id) == (1, 5)
    assert (result["parent_comment_id"], result["reply_to_comment_id"]) == (1, 5)
    assert result["reply_to_author_name"] == "답글작성자" and result["reply_to_is_deleted"] is False
    # 알림에는 서버가 계산한 원댓글을 넘긴다(받는 사람은 notification_writer가 저장된 관계로 계산).
    assert repo.notified == [(20, 50, 3, 1)]
    db.commit.assert_called_once()


def test_reply_to_root_stores_root_as_both_fields(repo, monkeypatch):
    use_target(monkeypatch, comment(1, author=1))
    result = service.create_comment(Mock(), 7, 3, RecruitCommentCreate(body="답글", reply_to_comment_id=1))
    assert (repo.added[0].parent_comment_id, repo.added[0].reply_to_comment_id) == (1, 1)
    assert result["reply_to_author_name"] == "원작성자"


def test_consistent_parent_and_reply_to_are_accepted(repo, monkeypatch):
    use_target(monkeypatch, comment(5, parent=1, author=4), comment(1))
    service.create_comment(Mock(), 7, 3, RecruitCommentCreate(body="답글", parent_comment_id=1, reply_to_comment_id=5))
    assert (repo.added[0].parent_comment_id, repo.added[0].reply_to_comment_id) == (1, 5)


def test_legacy_parent_only_keeps_null_reply_target(repo, monkeypatch):
    monkeypatch.setattr(recruit_repo, "get_active_comment", lambda db, cid: comment(1))
    monkeypatch.setattr(recruit_repo, "get_reply_target", Mock(side_effect=AssertionError("새 경로 호출 안 됨")))
    result = service.create_comment(Mock(), 7, 3, RecruitCommentCreate(body="답글", parent_comment_id=1))
    assert (repo.added[0].parent_comment_id, repo.added[0].reply_to_comment_id) == (1, None)
    assert result["reply_to_comment_id"] == 1 and result["reply_to_author_name"] == "원작성자"
    assert repo.notified == [(20, 50, 3, 1)]


@pytest.mark.parametrize(
    "target,root,parent,status",
    [
        (None, None, None, 404),                                          # 없거나 삭제된 대상
        (comment(5, post_id=99), None, None, 422),                        # 다른 게시글(모임)의 댓글
        (comment(5, parent=1), comment(1, post_id=99), None, 422),        # 원댓글이 다른 게시글
        (comment(5, parent=1), comment(1, parent=9), None, 422),          # 깨진 스레드(3단계)
        (comment(5, parent=1), comment(1), 2, 422),                       # parent와 다른 스레드
    ],
    ids=["missing_or_deleted", "other_post", "root_other_post", "broken_thread", "conflict"],
)
def test_invalid_reply_target_rolls_back_without_saving_or_notifying(repo, monkeypatch, target, root, parent, status):
    use_target(monkeypatch, target, root)
    db = Mock()
    with pytest.raises(HTTPException) as error:
        service.create_comment(db, 7, 3, RecruitCommentCreate(body="답글", parent_comment_id=parent, reply_to_comment_id=5))
    assert error.value.status_code == status
    assert repo.added == [] and repo.notified == []
    db.commit.assert_not_called()
    db.rollback.assert_called_once()


def test_error_messages_match_board_rules(repo, monkeypatch):
    """모임과 게시판·취업이 같은 규칙 함수를 쓰므로 문구도 같다."""
    use_target(monkeypatch, comment(5, post_id=99))
    with pytest.raises(HTTPException) as error:
        service.create_comment(Mock(), 7, 3, RecruitCommentCreate(body="답글", reply_to_comment_id=5))
    assert error.value.detail == "같은 게시글의 댓글에만 답글을 작성할 수 있습니다."


# =========================================================
# 조회
# =========================================================
def test_get_comments_returns_reply_target_with_masking(repo, monkeypatch):
    rows = [
        (comment(1, author=1), "원작성자"),
        (comment(2, parent=1, author=4), "답글작성자"),                       # 기존 데이터: 대상 NULL → 원댓글
        (comment(3, parent=1, author=3, reply_to=2), "나"),                  # 대댓글에 답글
        (comment(4, parent=1, author=5, reply_to=3, anonymous=True), "실명"),  # 익명 답글
        (comment(5, parent=1, author=4, reply_to=4), "답글작성자"),           # 익명에게 답글
        (comment(6, parent=1, author=6, deleted=True), "탈퇴한 사용자"),       # 삭제된 답글 (목록에서 빠짐)
        (comment(7, parent=1, author=4, reply_to=6), "답글작성자"),           # 삭제된 대상
        (comment(8, author=6), "탈퇴한 사용자"),
        (comment(9, parent=8, author=4, reply_to=8), "답글작성자"),           # 탈퇴 회원 대상
        (comment(10, parent=8, author=4, reply_to=9), "답글작성자"),
    ]
    monkeypatch.setattr(recruit_repo, "list_post_comments", lambda db, post_id: rows)
    result = {row["comment_id"]: row for row in service.get_comments(Mock(), 7, 3)}

    assert list(result) == [1, 2, 3, 4, 5, 7, 8, 9, 10]
    assert result[1]["reply_to_comment_id"] is None and result[1]["reply_to_is_deleted"] is False
    assert (result[2]["reply_to_comment_id"], result[2]["reply_to_author_name"]) == (1, "원작성자")
    assert (result[3]["reply_to_comment_id"], result[3]["reply_to_author_name"]) == (2, "답글작성자")
    assert result[4]["author_id"] is None and result[4]["author_name"] == "익명"
    assert (result[5]["reply_to_comment_id"], result[5]["reply_to_author_name"]) == (4, "익명")
    assert (result[7]["reply_to_author_name"], result[7]["reply_to_is_deleted"]) == (None, True)
    assert result[9]["reply_to_author_name"] == "탈퇴한 사용자"
    assert all("실명" not in str(value) for row in result.values() for value in row.values())
    assert all(row["author_id"] != 5 for row in result.values())


def test_reply_under_deleted_root_keeps_placeholder(repo, monkeypatch):
    rows = [
        (comment(1, deleted=True), "원작성자"),
        (comment(2, parent=1, author=4), "답글작성자"),
        (comment(3, parent=1, author=3, reply_to=2), "나"),
    ]
    monkeypatch.setattr(recruit_repo, "list_post_comments", lambda db, post_id: rows)
    result = service.get_comments(Mock(), 7, 3)
    assert [row["comment_id"] for row in result] == [1, 2, 3]
    assert result[0]["is_deleted"] is True and result[0]["body"] == ""
    assert result[1]["reply_to_is_deleted"] is True and result[1]["reply_to_author_name"] is None
    assert result[2]["reply_to_author_name"] == "답글작성자"


# =========================================================
# 수정
# =========================================================
def test_update_keeps_relation_and_reports_target(repo, monkeypatch):
    mine = comment(3, parent=1, author=3, reply_to=2)
    comments = {3: mine, 2: comment(2, parent=1, author=4)}
    monkeypatch.setattr(recruit_repo, "get_active_comment", lambda db, cid: comments.get(cid))
    result = service.update_comment(Mock(), 7, 3, 3, RecruitCommentUpdate(body="수정"))
    assert (mine.parent_comment_id, mine.reply_to_comment_id) == (1, 2)
    assert (result["reply_to_comment_id"], result["reply_to_author_name"]) == (2, "답글작성자")


@pytest.mark.parametrize("field", ["parent_comment_id", "reply_to_comment_id"])
def test_update_schema_rejects_relation_change(field):
    with pytest.raises(ValidationError):
        RecruitCommentUpdate.model_validate({"body": "수정", field: 3})
    assert RecruitCommentUpdate.model_validate({"body": "수정", field: None}).body == "수정"


@pytest.mark.parametrize("value", [0, -1, "abc"])
def test_create_schema_requires_positive_reply_target(value):
    with pytest.raises(ValidationError):
        RecruitCommentCreate(body="답글", reply_to_comment_id=value)
