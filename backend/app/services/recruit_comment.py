"""모임 댓글·대댓글 조회·작성·수정·삭제에 관한 비즈니스 로직.

대댓글은 1단계까지만 허용함. (최상위 댓글에만 답글 가능)
삭제는 deleted_at을 기록하는 논리삭제이며, 삭제된 부모 아래 살아 있는 대댓글이
있으면 부모를 "삭제된 댓글" 자리표시로 남겨 대댓글이 고아가 되지 않게 함.
"""

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.app.models.comment import Comment
from backend.app.repositories import recruit as recruit_repo
from backend.app.schemas.recruit import RecruitCommentCreate, RecruitCommentUpdate
from backend.app.services.recruit import get_recruit_post


def _serialize_comment(comment: Comment, nickname: str | None, member_id: int | None):
    """댓글 ORM 객체를 응답 형태로 바꿈. 삭제된 댓글은 본문·작성자를 숨김."""
    deleted = comment.deleted_at is not None
    return {
        "comment_id": comment.comment_id,
        "parent_comment_id": comment.parent_comment_id,
        "body": "" if deleted else comment.body,
        "author_id": None if deleted else comment.author_member_id,
        "author_name": "" if deleted else (nickname or "익명"),
        "created_at": comment.created_at,
        "updated_at": comment.updated_at,
        "is_owner": not deleted and comment.author_member_id == member_id,
        "is_deleted": deleted,
    }


def get_comments(db: Session, recruit_id: int, member_id: int | None = None):
    """모임 댓글을 부모 → 대댓글 순서로 반환함.

    1. 게시글의 모든 댓글을 작성 순서로 읽음 (삭제된 댓글 포함)
    2. 최상위 댓글과, 부모별로 묶은 살아 있는 대댓글로 나눔
    3. 최상위 댓글 순서대로 부모 → 그 부모의 대댓글을 이어 붙임
       삭제된 부모는 살아 있는 대댓글이 있을 때만 자리표시로 남김
    """
    post = get_recruit_post(db, recruit_id)
    rows = recruit_repo.list_post_comments(db, post.post_id)

    parents = []
    replies_by_parent = {}
    for comment, nickname in rows:
        if comment.parent_comment_id is None:
            parents.append((comment, nickname))
        elif comment.deleted_at is None:
            replies_by_parent.setdefault(comment.parent_comment_id, []).append(
                (comment, nickname)
            )

    result = []
    for comment, nickname in parents:
        replies = replies_by_parent.get(comment.comment_id, [])
        if comment.deleted_at is not None and not replies:
            continue
        result.append(_serialize_comment(comment, nickname, member_id))
        result.extend(
            _serialize_comment(reply, reply_nickname, member_id)
            for reply, reply_nickname in replies
        )
    return result


def _ensure_parent_comment(db: Session, post_id: int, parent_comment_id: int) -> None:
    """대댓글의 부모가 같은 모임의 삭제되지 않은 최상위 댓글인지 검사함."""
    parent = recruit_repo.get_active_comment(db, parent_comment_id)
    if parent is None or parent.post_id != post_id:
        raise HTTPException(status_code=404, detail="부모 댓글이 없습니다.")

    if parent.parent_comment_id is not None:
        raise HTTPException(
            status_code=400,
            detail="대댓글에는 답글을 달 수 없습니다.",
        )


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
        if data.parent_comment_id is not None:
            _ensure_parent_comment(db, post.post_id, data.parent_comment_id)

        comment = Comment(
            post_id=post.post_id,
            author_member_id=member_id,
            parent_comment_id=data.parent_comment_id,
            body=data.body,
        )
        recruit_repo.add_comment(db, comment)  # comment_id를 확보함.

        # commit 후 ORM 객체가 만료되기 전에 응답을 만듦.
        nickname = recruit_repo.get_member_nickname(db, member_id)
        result = _serialize_comment(comment, nickname, member_id)

        db.commit()
        return result

    except Exception:
        db.rollback()
        raise


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
        comment.updated_at = datetime.now()

        nickname = recruit_repo.get_member_nickname(db, member_id)
        result = _serialize_comment(comment, nickname, member_id)

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

        comment.deleted_at = datetime.now()
        comment.updated_at = comment.deleted_at

        db.commit()
        return {"message": "댓글 삭제 완료"}

    except Exception:
        db.rollback()
        raise
