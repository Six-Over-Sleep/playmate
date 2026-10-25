"""모임 좋아요·스크랩 등록·취소에 관한 비즈니스 로직.

좋아요·스크랩 테이블은 모임 ID가 아니라 게시글 ID(post_id)를 기준으로 저장함.
같은 요청을 여러 번 보내도 최종 상태가 같도록 등록은 중복을 무시하고,
취소는 없는 기록을 지워도 오류가 나지 않음.
"""

from sqlalchemy.orm import Session

from backend.app.repositories import recruit as recruit_repo
from backend.app.services.recruit import get_recruit_post


def _like_state(db: Session, recruit_id: int, post_id: int, member_id: int):
    """좋아요 등록·취소 후 화면에 필요한 현재 상태를 반환함."""
    return {
        "recruit_id": recruit_id,
        "like_count": recruit_repo.count_post_likes(db, post_id),
        "liked_by_me": recruit_repo.has_post_like(db, post_id, member_id),
    }


def _scrap_state(db: Session, recruit_id: int, post_id: int, member_id: int):
    """스크랩 등록·취소 후 화면에 필요한 현재 상태를 반환함."""
    return {
        "recruit_id": recruit_id,
        "scrapped_by_me": recruit_repo.has_post_scrap(db, post_id, member_id),
    }


def like_recruit(db: Session, recruit_id: int, member_id: int):
    """모임 확인 → 좋아요 저장 → 현재 상태 조회를 하나의 트랜잭션으로 처리함.

    이미 좋아요한 모임이면 행을 추가하지 않고 현재 상태를 반환함.
    삭제된 모임은 404이며 아무것도 저장하지 않음.
    """
    try:
        post = get_recruit_post(db, recruit_id)
        recruit_repo.add_post_like(db, post.post_id, member_id)
        result = _like_state(db, recruit_id, post.post_id, member_id)
        db.commit()
        return result

    except Exception:
        db.rollback()
        raise


def unlike_recruit(db: Session, recruit_id: int, member_id: int):
    """모임 확인 후 좋아요를 취소하고 현재 상태를 반환함. 좋아요가 없어도 성공함."""
    try:
        post = get_recruit_post(db, recruit_id)
        recruit_repo.delete_post_like(db, post.post_id, member_id)
        result = _like_state(db, recruit_id, post.post_id, member_id)
        db.commit()
        return result

    except Exception:
        db.rollback()
        raise


def scrap_recruit(db: Session, recruit_id: int, member_id: int):
    """모임 확인 → 스크랩 저장 → 현재 상태 조회를 하나의 트랜잭션으로 처리함."""
    try:
        post = get_recruit_post(db, recruit_id)
        recruit_repo.add_post_scrap(db, post.post_id, member_id)
        result = _scrap_state(db, recruit_id, post.post_id, member_id)
        db.commit()
        return result

    except Exception:
        db.rollback()
        raise


def unscrap_recruit(db: Session, recruit_id: int, member_id: int):
    """모임 확인 후 스크랩을 취소하고 현재 상태를 반환함. 스크랩이 없어도 성공함."""
    try:
        post = get_recruit_post(db, recruit_id)
        recruit_repo.delete_post_scrap(db, post.post_id, member_id)
        result = _scrap_state(db, recruit_id, post.post_id, member_id)
        db.commit()
        return result

    except Exception:
        db.rollback()
        raise
