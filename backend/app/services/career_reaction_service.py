"""취업 게시글 4종 공통 좋아요·스크랩·댓글 업무를 처리한다.

게시판(#27)의 좋아요·스크랩·댓글 Repository 함수를 그대로 재사용한다.
취업 글은 board_id가 NULL이라 게시판 Service의 게시글 확인(_require_post)을
쓸 수 없으므로, 대상 확인만 취업 게시글 기준(career_post_exists)으로 바꾼다.
댓글 수정·삭제는 게시판 공통 API(/api/comments/{comment_id})를 그대로 사용한다.
"""

import logging
from typing import Any

from fastapi import HTTPException

from app.core.db_connect import db_cursor
from app.repositories import board_repository, career_repository
from app.services import board_service
from app.services.xp_service import (
    grant_xp,
    grant_post_like_xp,
)
from app.services.notification_writer import save_comment_notification


logger = logging.getLogger(__name__)


def _require_career_post(cursor, post_id: int) -> None:
    """삭제되지 않은 취업 게시글이 아니면 404를 발생시킨다."""
    if not career_repository.career_post_exists(cursor, post_id):
        raise HTTPException(status_code=404, detail="취업 게시글을 찾을 수 없습니다.")


# =========================================
# 좋아요·스크랩
# =========================================

# 취업 게시글 좋아요 및 작성자 XP 지급
def like_post(post_id: int, member_id: int) -> dict[str, Any]:

    with db_cursor(commit=True) as cursor:

        # 1. 취업 게시글 존재 확인
        _require_career_post(cursor, post_id)

        # 2. 좋아요 등록
        is_new_like = board_repository.like_post(
            cursor, post_id, member_id
        )

        # 3. 새로운 좋아요일 때만 작성자에게 XP 지급
        if is_new_like:
            grant_post_like_xp(
                cursor,
                post_id,
                member_id,
            )

        # 4. 좋아요 결과 반환
        return board_repository.get_post_like(
            cursor, post_id, member_id
        )

def unlike_post(post_id: int, member_id: int) -> dict[str, Any]:
    """게시글 확인 후 좋아요를 취소하고 응답을 조회한다. 좋아요가 없어도 성공한다."""
    with db_cursor(commit=True) as cursor:
        _require_career_post(cursor, post_id)
        board_repository.unlike_post(cursor, post_id, member_id)
        return board_repository.get_post_like(cursor, post_id, member_id)


def scrap_post(post_id: int, member_id: int) -> dict[str, Any]:
    """게시글 확인·스크랩 저장·응답 조회를 한 트랜잭션에서 수행한다. 중복 요청은 현재 상태를 반환한다."""
    with db_cursor(commit=True) as cursor:
        _require_career_post(cursor, post_id)
        board_repository.scrap_post(cursor, post_id, member_id)
        return board_repository.get_post_scrap(cursor, post_id, member_id)


def unscrap_post(post_id: int, member_id: int) -> dict[str, Any]:
    """게시글 확인 후 스크랩을 취소하고 응답을 조회한다. 스크랩이 없어도 성공한다."""
    with db_cursor(commit=True) as cursor:
        _require_career_post(cursor, post_id)
        board_repository.unscrap_post(cursor, post_id, member_id)
        return board_repository.get_post_scrap(cursor, post_id, member_id)


# =========================================
# 댓글·대댓글
# =========================================

def list_comments(post_id: int, member_id: int) -> list[dict[str, Any]]:
    """게시글 확인 후 댓글을 부모 → 대댓글 순서로 반환한다. 삭제된 부모 자리표시 규칙은 게시판과 같다."""
    with db_cursor(read_only=True) as cursor:
        _require_career_post(cursor, post_id)
        return board_repository.list_comments(cursor, post_id, member_id)


def create_comment(
    post_id: int,
    body: str,
    member_id: int,
    parent_comment_id: int | None = None,
    is_anonymous: bool = False,
) -> dict[str, Any]:
    """게시글·부모 댓글 확인, 댓글 저장, 응답 조회 후 게시판과 같이 XP를 지급한다."""
    with db_cursor(commit=True) as cursor:
        # 1. 취업 게시글 존재 확인
        _require_career_post(cursor, post_id)

        # 2. 대댓글이면 게시판과 같은 규칙으로 부모 댓글 검증 (1단계까지만 허용)
        if parent_comment_id is not None:
            board_service._require_parent_comment(cursor, post_id, parent_comment_id)

        # 3. 댓글 또는 대댓글 저장
        comment_id = board_repository.create_comment(
            cursor,
            post_id,
            body,
            member_id,
            parent_comment_id,
            is_anonymous,
        )
        comment = board_service._comment_detail(cursor, comment_id, member_id)

    # 4. DB 저장 완료 후 XP 지급 (삭제 시 회수는 공통 댓글 삭제 API가 수행함)
    if member_id > 0:
        activity_type = "REPLY" if parent_comment_id is not None else "COMMENT"
        try:
            grant_xp(member_id, activity_type, comment_id)
        except Exception:
            logger.exception("취업 댓글 XP 지급 실패: comment_id=%s", comment_id)

    # 5. DB 저장 완료 후 Discord DM 알림 대기 행 저장 (실패해도 댓글은 유지)
    try:
        save_comment_notification(post_id, comment_id, member_id, parent_comment_id)
    except Exception:
        logger.exception("취업 댓글 알림 저장 실패: comment_id=%s", comment_id)

    return comment
