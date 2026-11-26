"""모임 댓글·대댓글 조회·작성·수정·삭제에 관한 비즈니스 로직.

답글은 항상 2단계로 저장함. parent_comment_id = 최상위 원댓글, reply_to_comment_id = 실제 답글 대상.
기존 parent_comment_id 방식은 최상위 댓글에만 답글 가능하고, reply_to_comment_id로는 대댓글에도 답글 가능.
삭제는 deleted_at을 기록하는 논리삭제이며, 삭제된 부모 아래 살아 있는 대댓글이
있으면 부모를 "삭제된 댓글" 자리표시로 남겨 대댓글이 고아가 되지 않게 함.
"""

from datetime import datetime, timezone
import logging
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.app.models.comment import Comment
from backend.app.repositories import recruit as recruit_repo
from backend.app.schemas.recruit import RecruitCommentCreate, RecruitCommentUpdate
from backend.app.services.recruit import get_recruit_post
from backend.app.services.notification_writer import save_comment_notification
from backend.app.services.comment_reply_rules import decide_reply_root


logger = logging.getLogger(__name__)


def _db_timezone(db: Session):
    """comments의 시간 컬럼은 시간대 없는 TIMESTAMP이며 DB 세션 시간대(CURRENT_TIMESTAMP)로 기록된다."""
    try:
        if db.get_bind().dialect.name != "postgresql":
            return timezone.utc
        return ZoneInfo(db.execute(text("SHOW TIME ZONE")).scalar())
    except Exception:
        return timezone.utc


def _aware(value, tz):
    """응답에 시간대를 붙여 브라우저가 서버 시각을 현지 시각으로 오해하지 않게 함."""
    return value.replace(tzinfo=tz) if isinstance(value, datetime) and value.tzinfo is None else value


def _reply_target_fields(comment: Comment, target: Comment | None, target_nickname: str | None) -> dict:
    """답글 대상 표시 정보를 게시판 댓글 응답과 같은 규칙으로 만듦.

    - 원댓글: 대상 없음
    - 대상 ID = reply_to_comment_id, 기존 데이터(NULL)는 parent_comment_id
    - 대상이 없거나 삭제됨: 이름 None, reply_to_is_deleted True
    - 익명 대상은 "익명", 탈퇴 회원은 "탈퇴한 사용자"(target_nickname에 반영됨). 회원 ID는 내보내지 않음
    """
    if comment.parent_comment_id is None:
        return {"reply_to_comment_id": None, "reply_to_author_name": None, "reply_to_is_deleted": False}
    target_id = comment.reply_to_comment_id or comment.parent_comment_id
    if target is None or target.deleted_at is not None:
        return {"reply_to_comment_id": target_id, "reply_to_author_name": None, "reply_to_is_deleted": True}
    name = "익명" if target.is_anonymous else (target_nickname or "익명")
    return {"reply_to_comment_id": target_id, "reply_to_author_name": name, "reply_to_is_deleted": False}


def _serialize_comment(
    comment: Comment,
    nickname: str | None,
    member_id: int | None,
    tz=timezone.utc,
    reply_target: Comment | None = None,
    reply_target_nickname: str | None = None,
):
    """댓글 ORM 객체를 응답 형태로 바꿈. 삭제된 댓글은 본문·작성자를 숨기고, 익명 댓글은 작성자를 가림."""
    deleted = comment.deleted_at is not None
    hidden = deleted or bool(comment.is_anonymous)
    return {
        "comment_id": comment.comment_id,
        "parent_comment_id": comment.parent_comment_id,
        **_reply_target_fields(comment, reply_target, reply_target_nickname),
        "body": "" if deleted else comment.body,
        "author_id": None if hidden else comment.author_member_id,
        "author_name": "" if deleted else ("익명" if comment.is_anonymous else (nickname or "익명")),
        "created_at": _aware(comment.created_at, tz),
        "updated_at": _aware(comment.updated_at, tz),
        "is_owner": not deleted and comment.author_member_id == member_id,
        "is_deleted": deleted,
    }


def _target_with_nickname(db: Session, comment: Comment, target: Comment | None = None):
    """작성·수정 응답용으로 답글 대상과 그 작성자 표시 이름을 조회함. 원댓글이면 (None, None)."""
    if comment.parent_comment_id is None:
        return None, None
    if target is None:
        target = recruit_repo.get_active_comment(db, comment.reply_to_comment_id or comment.parent_comment_id)
    if target is None or target.is_anonymous:
        return target, None
    return target, recruit_repo.get_member_nickname(db, target.author_member_id)


def get_comments(db: Session, recruit_id: int, member_id: int | None = None):
    """모임 댓글을 부모 → 대댓글 순서로 반환함.

    1. 게시글의 모든 댓글을 작성 순서로 읽음 (삭제된 댓글 포함)
    2. 최상위 댓글과, 부모별로 묶은 살아 있는 대댓글로 나눔
    3. 최상위 댓글 순서대로 부모 → 그 부모의 대댓글을 이어 붙임
       삭제된 부모는 살아 있는 대댓글이 있을 때만 자리표시로 남김
    """
    post = get_recruit_post(db, recruit_id)
    rows = recruit_repo.list_post_comments(db, post.post_id)
    # 답글 대상은 같은 게시글의 댓글이므로 이미 읽은 행(삭제 포함)에서 찾음. 추가 쿼리 없음.
    by_id = {comment.comment_id: (comment, nickname) for comment, nickname in rows}

    def serialize(comment, nickname, tz):
        target, target_nickname = by_id.get(comment.reply_to_comment_id or comment.parent_comment_id, (None, None))
        return _serialize_comment(comment, nickname, member_id, tz, target, target_nickname)

    parents = []
    replies_by_parent = {}
    for comment, nickname in rows:
        if comment.parent_comment_id is None:
            parents.append((comment, nickname))
        elif comment.deleted_at is None:
            replies_by_parent.setdefault(comment.parent_comment_id, []).append(
                (comment, nickname)
            )

    tz = _db_timezone(db)
    result = []
    for comment, nickname in parents:
        replies = replies_by_parent.get(comment.comment_id, [])
        if comment.deleted_at is not None and not replies:
            continue
        result.append(serialize(comment, nickname, tz))
        result.extend(serialize(reply, reply_nickname, tz) for reply, reply_nickname in replies)
    return result


def _ensure_parent_comment(db: Session, post_id: int, parent_comment_id: int):
    """대댓글의 부모가 같은 모임의 삭제되지 않은 최상위 댓글인지 검사하고 그 댓글을 반환함."""
    parent = recruit_repo.get_active_comment(db, parent_comment_id)
    if parent is None or parent.post_id != post_id:
        raise HTTPException(status_code=404, detail="부모 댓글이 없습니다.")

    if parent.parent_comment_id is not None:
        raise HTTPException(
            status_code=400,
            detail="대댓글에는 답글을 달 수 없습니다.",
        )
    return parent


def _resolve_reply_target(
    db: Session,
    post_id: int,
    parent_comment_id: int | None,
    reply_to_comment_id: int | None,
):
    """저장할 (원댓글 ID, 답글 대상 ID, 대상 댓글)을 정함.

    - 둘 다 없음: 원댓글 → (None, None, None)
    - parent_comment_id만: 기존 방식과 기존 오류(404·400)를 그대로 유지 → (parent, None, 부모 댓글)
    - reply_to_comment_id: 게시판·취업 댓글과 같은 규칙(decide_reply_root)으로 검증하고
      서버가 원댓글을 계산함. 대상 행은 FOR SHARE로 잠금.
    """
    if reply_to_comment_id is None:
        if parent_comment_id is None:
            return None, None, None
        return parent_comment_id, None, _ensure_parent_comment(db, post_id, parent_comment_id)

    target, root = recruit_repo.get_reply_target(db, reply_to_comment_id)
    checked = None if target is None else {
        "comment_id": target.comment_id,
        "post_id": target.post_id,
        "parent_comment_id": target.parent_comment_id,
        "root_post_id": None if root is None else root.post_id,
        "root_parent_comment_id": None if root is None else root.parent_comment_id,
    }
    root_comment_id = decide_reply_root(post_id, parent_comment_id, checked)
    return root_comment_id, reply_to_comment_id, target


def create_comment(
    db: Session,
    recruit_id: int,
    member_id: int,
    data: RecruitCommentCreate,
):
    """모임·부모 댓글 확인 → 댓글 저장을 하나의 트랜잭션으로 처리함.

    검사에 실패하면 rollback하고 댓글을 저장하지 않음.
    """
    try:
        post = get_recruit_post(db, recruit_id)
        parent_comment_id, reply_to_comment_id, target = _resolve_reply_target(
            db, post.post_id, data.parent_comment_id, data.reply_to_comment_id
        )

        comment = Comment(
            post_id=post.post_id,
            author_member_id=member_id,
            parent_comment_id=parent_comment_id,
            reply_to_comment_id=reply_to_comment_id,
            body=data.body,
        )
        recruit_repo.add_comment(db, comment)  # comment_id를 확보함.

        # commit 후 ORM 객체가 만료되기 전에 응답과 알림에 쓸 값을 만듦.
        nickname = recruit_repo.get_member_nickname(db, member_id)
        target, target_nickname = _target_with_nickname(db, comment, target)
        result = _serialize_comment(comment, nickname, member_id, _db_timezone(db), target, target_nickname)
        post_id, comment_id = post.post_id, comment.comment_id

        db.commit()

    except Exception:
        db.rollback()
        raise

    # 댓글 커밋 후 Discord DM 알림 대기 행 저장 (별도 트랜잭션, 실패해도 댓글은 유지)
    # 서버가 계산한 원댓글을 넘기고, 받는 사람은 notification_writer가 저장된 관계로 계산함.
    try:
        save_comment_notification(post_id, comment_id, member_id, parent_comment_id)
    except Exception:
        logger.exception("모임 댓글 알림 저장 실패: comment_id=%s", comment_id)

    return result


def _get_owned_comment(db: Session, post_id: int, comment_id: int, member_id: int):
    """이 모임의 삭제되지 않은 댓글을 찾고 작성자인지 확인함.

    다른 모임·게시판의 댓글이거나 없으면 404, 작성자가 아니면 403.
    """
    comment = recruit_repo.get_active_comment(db, comment_id)
    if comment is None or comment.post_id != post_id:
        raise HTTPException(status_code=404, detail="댓글이 없습니다.")

    if comment.author_member_id != member_id:
        raise HTTPException(
            status_code=403,
            detail="작성자만 수정하거나 삭제할 수 있습니다.",
        )
    return comment


def update_comment(
    db: Session,
    recruit_id: int,
    comment_id: int,
    member_id: int,
    data: RecruitCommentUpdate,
):
    """작성자의 댓글 본문을 수정함. 일반 댓글과 대댓글 모두 같은 규칙을 따름."""
    try:
        post = get_recruit_post(db, recruit_id)
        comment = _get_owned_comment(db, post.post_id, comment_id, member_id)

        comment.body = data.body
        # 작성 시각(DB 기본값)과 같은 DB 시계로 기록함. 서버 로컬 시각을 섞지 않음.
        comment.updated_at = func.now()
        db.flush()
        db.refresh(comment)

        nickname = recruit_repo.get_member_nickname(db, member_id)
        target, target_nickname = _target_with_nickname(db, comment)
        result = _serialize_comment(comment, nickname, member_id, _db_timezone(db), target, target_nickname)

        db.commit()
        return result

    except Exception:
        db.rollback()
        raise


def delete_comment(db: Session, recruit_id: int, comment_id: int, member_id: int):
    """작성자의 댓글을 논리삭제함. 대댓글은 그대로 남음."""
    try:
        post = get_recruit_post(db, recruit_id)
        comment = _get_owned_comment(db, post.post_id, comment_id, member_id)

        comment.deleted_at = func.now()
        comment.updated_at = func.now()

        db.commit()
        return {"message": "댓글 삭제 완료"}

    except Exception:
        db.rollback()
        raise
