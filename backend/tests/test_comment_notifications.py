"""댓글·대댓글 작성 후 Discord DM 알림 저장 연결을 DB 없이 확인한다.

게시판·모임·취업 댓글 Service가 댓글 커밋이 끝난 뒤 save_comment_notification을
실제 comment_id로 한 번 호출하는지, 알림 저장 실패가 댓글 응답과 XP를 바꾸지 않는지 확인한다.
알림 SQL(받는 사람·본인 제외·FK)은 일회용 PostgreSQL 통합 검증에서 확인한다.
"""
from contextlib import contextmanager
import logging
from types import SimpleNamespace

import pytest

from app.schemas.recruit import RecruitCommentCreate
from app.services import board_service, career_reaction_service, recruit_comment


@pytest.fixture
def events():
    return []


def fake_db_cursor(events):
    @contextmanager
    def db_cursor(**_):
        events.append("begin")
        yield object()
        events.append("commit")
    return db_cursor


def record_notification(events, fail=False):
    def save(post_id, comment_id, actor_member_id, parent_comment_id=None):
        events.append(("notify", post_id, comment_id, actor_member_id, parent_comment_id))
        if fail:
            raise RuntimeError("notifications insert failed")
        return 1
    return save


def comment_row(comment_id, parent_comment_id=None):
    return {"id": comment_id, "post_id": 2, "parent_comment_id": parent_comment_id, "body": "댓글"}


# ---------------------------------------------------------------------------
# 게시판
# ---------------------------------------------------------------------------
def prepare_board(monkeypatch, events, fail=False):
    monkeypatch.setattr(board_service, "db_cursor", fake_db_cursor(events))
    monkeypatch.setattr(board_service, "_require_post", lambda cursor, board_id, post_id: None)
    monkeypatch.setattr(board_service, "_require_parent_comment", lambda cursor, post_id, parent_id: None)
    monkeypatch.setattr(board_service.repository, "create_comment",
                        lambda cursor, post_id, body, member_id, parent_id=None, is_anonymous=False: 9)
    monkeypatch.setattr(board_service, "_comment_detail",
                        lambda cursor, comment_id, member_id: comment_row(comment_id))
    monkeypatch.setattr(board_service, "grant_xp", lambda member_id, kind, source_id: events.append(("xp", kind)))
    monkeypatch.setattr(board_service, "save_comment_notification", record_notification(events, fail))


@pytest.mark.parametrize("parent_id,kind", [(None, "COMMENT"), (3, "REPLY")])
def test_board_comment_saves_notification_after_commit(monkeypatch, events, parent_id, kind):
    prepare_board(monkeypatch, events)
    result = board_service.create_comment(1, 2, "댓글", 5, parent_id)
    assert result == comment_row(9)
    assert events == ["begin", "commit", ("xp", kind), ("notify", 2, 9, 5, parent_id)]


def test_board_notification_failure_keeps_comment(monkeypatch, events, caplog):
    prepare_board(monkeypatch, events, fail=True)
    with caplog.at_level(logging.ERROR):
        assert board_service.create_comment(1, 2, "댓글", 5) == comment_row(9)
    assert ("xp", "COMMENT") in events
    assert "댓글 알림 저장 실패" in caplog.text


def test_board_failed_comment_does_not_notify(monkeypatch, events):
    prepare_board(monkeypatch, events)
    monkeypatch.setattr(board_service.repository, "create_comment",
                        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("insert failed")))
    with pytest.raises(RuntimeError):
        board_service.create_comment(1, 2, "댓글", 5)
    assert not any(isinstance(e, tuple) and e[0] == "notify" for e in events)


# ---------------------------------------------------------------------------
# 취업 (취준 도감·커리어 톡톡·현직자 라운지·커리어 연구소 공통 post_id API)
# ---------------------------------------------------------------------------
def prepare_career(monkeypatch, events, fail=False):
    monkeypatch.setattr(career_reaction_service, "db_cursor", fake_db_cursor(events))
    monkeypatch.setattr(career_reaction_service, "_require_career_post", lambda cursor, post_id: None)
    monkeypatch.setattr(career_reaction_service.board_service, "_require_parent_comment",
                        lambda cursor, post_id, parent_id: None)
    monkeypatch.setattr(career_reaction_service.board_repository, "create_comment",
                        lambda cursor, post_id, body, member_id, parent_id=None, is_anonymous=False: 9)
    monkeypatch.setattr(career_reaction_service.board_service, "_comment_detail",
                        lambda cursor, comment_id, member_id: comment_row(comment_id))
    monkeypatch.setattr(career_reaction_service, "grant_xp",
                        lambda member_id, kind, source_id: events.append(("xp", kind)))
    monkeypatch.setattr(career_reaction_service, "save_comment_notification", record_notification(events, fail))


@pytest.mark.parametrize("parent_id,kind", [(None, "COMMENT"), (3, "REPLY")])
def test_career_comment_saves_notification_after_commit(monkeypatch, events, parent_id, kind):
    prepare_career(monkeypatch, events)
    assert career_reaction_service.create_comment(2, "댓글", 5, parent_id) == comment_row(9)
    assert events == ["begin", "commit", ("xp", kind), ("notify", 2, 9, 5, parent_id)]


def test_career_notification_failure_keeps_comment(monkeypatch, events, caplog):
    prepare_career(monkeypatch, events, fail=True)
    with caplog.at_level(logging.ERROR):
        assert career_reaction_service.create_comment(2, "댓글", 5) == comment_row(9)
    assert ("xp", "COMMENT") in events
    assert "취업 댓글 알림 저장 실패" in caplog.text


# ---------------------------------------------------------------------------
# 모임 (SQLAlchemy Session)
# ---------------------------------------------------------------------------
class FakeSession:
    def __init__(self, events):
        self.events = events

    def commit(self):
        self.events.append("commit")

    def rollback(self):
        self.events.append("rollback")


def prepare_recruit(monkeypatch, events, fail=False):
    # 모임 댓글은 recruit_id가 아닌 모임 게시글의 post_id(20)에 저장된다.
    monkeypatch.setattr(recruit_comment, "get_recruit_post", lambda db, recruit_id: SimpleNamespace(post_id=20))
    monkeypatch.setattr(recruit_comment, "_ensure_parent_comment", lambda db, post_id, parent_id: None)

    def add_comment(db, comment):
        comment.comment_id = 9

    monkeypatch.setattr(recruit_comment.recruit_repo, "add_comment", add_comment)
    monkeypatch.setattr(recruit_comment.recruit_repo, "get_member_nickname", lambda db, member_id: "민혁")
    monkeypatch.setattr(recruit_comment, "save_comment_notification", record_notification(events, fail))
    return FakeSession(events)


@pytest.mark.parametrize("parent_id", [None, 3])
def test_recruit_comment_saves_notification_after_commit(monkeypatch, events, parent_id):
    db = prepare_recruit(monkeypatch, events)
    result = recruit_comment.create_comment(db, 1, 5, RecruitCommentCreate(body="댓글", parent_comment_id=parent_id))
    assert result["comment_id"] == 9 and result["parent_comment_id"] == parent_id
    assert events == ["commit", ("notify", 20, 9, 5, parent_id)]


def test_recruit_notification_failure_keeps_comment(monkeypatch, events, caplog):
    db = prepare_recruit(monkeypatch, events, fail=True)
    with caplog.at_level(logging.ERROR):
        result = recruit_comment.create_comment(db, 1, 5, RecruitCommentCreate(body="댓글"))
    assert result["comment_id"] == 9
    assert "rollback" not in events, "이미 커밋된 댓글은 알림 실패로 롤백하지 않는다"
    assert "모임 댓글 알림 저장 실패" in caplog.text


def test_recruit_failed_comment_does_not_notify(monkeypatch, events):
    db = prepare_recruit(monkeypatch, events)
    monkeypatch.setattr(recruit_comment.recruit_repo, "get_member_nickname",
                        lambda db, member_id: (_ for _ in ()).throw(RuntimeError("db error")))
    with pytest.raises(RuntimeError):
        recruit_comment.create_comment(db, 1, 5, RecruitCommentCreate(body="댓글"))
    assert events == ["rollback"]
