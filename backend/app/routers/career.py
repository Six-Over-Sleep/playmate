
"""PLAYMATE 취업 카테고리 API 라우터.

취준 도감 후기 등록 및 상세 조회 API를 관리한다.
DB 처리와 트랜잭션은 career_service에서 담당한다.
"""

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.concurrency import run_in_threadpool

from app.core.auth import get_current_member_id

from app.schemas.career import (
    CareerReviewCreate,
    CareerReviewResponse,
    CareerReviewListResponse,
    CareerReviewUpdate,
    ReviewSubcategory,
    ProcessStage,
    ProcessResult,
)
from app.services import career_service


# 취업 카테고리 API
router = APIRouter(
    prefix="/api/career",
    tags=["career"],
)


# =========================================
# 취준 도감 - 후기 등록
# =========================================

@router.post(
    "/reviews",
    response_model=CareerReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_review(
    payload: CareerReviewCreate,
    member_id: int = Depends(get_current_member_id),
):
    """로그인한 회원의 취업 후기를 등록한다."""

    return await run_in_threadpool(
        career_service.create_review,
        payload,
        member_id,
    )


# =========================================
# 취준 도감 - 후기 상세 조회
# =========================================
# =========================================
# 취준 도감 - 후기 목록 조회
# =========================================

@router.get(
    "/reviews",
    response_model=CareerReviewListResponse,
)
async def list_reviews(
    q: str | None = Query(default=None, max_length=100),

    subcategory_code: ReviewSubcategory | None = Query(
        default=None
    ),

    job_category_code: str | None = Query(
        default=None,
        min_length=1,
        max_length=50,
    ),

    process_stage: ProcessStage | None = Query(
        default=None
    ),

    process_result: ProcessResult | None = Query(
        default=None
    ),

    page: int = Query(default=1, ge=1),

    page_size: int = Query(default=10, ge=1, le=50),

    member_id: int = Depends(get_current_member_id),
):
    """취준 도감 후기 목록을 검색하고 조회한다."""

    return await run_in_threadpool(
        career_service.list_reviews,
        member_id=member_id,
        q=q,
        subcategory_code=subcategory_code,
        job_category_code=job_category_code,
        process_stage=process_stage,
        process_result=process_result,
        page=page,
        page_size=page_size,
    )

@router.get(
    "/reviews/{post_id}",
    response_model=CareerReviewResponse,
)
async def get_review(
    post_id: int,
    member_id: int = Depends(get_current_member_id),
):
    """게시글 ID로 취업 후기를 조회한다."""

    return await run_in_threadpool(
        career_service.get_review,
        post_id,
        member_id,
    )

# =========================================
# 취준 도감 - 후기 수정 API
# =========================================

@router.patch(
    "/reviews/{post_id}",
    response_model=CareerReviewResponse,
)
async def update_review(
    post_id: int,
    payload: CareerReviewUpdate,
    member_id: int = Depends(get_current_member_id),
):
    """작성자 본인의 취준 도감 후기를 수정한다."""

    return await run_in_threadpool(
        career_service.update_review,
        post_id,
        payload,
        member_id,
    )


# =========================================
# 취준 도감 - 후기 삭제 API
# =========================================

@router.delete(
    "/reviews/{post_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_review(
    post_id: int,
    member_id: int = Depends(get_current_member_id),
):
    """작성자 본인의 취준 도감 후기를 논리 삭제한다."""

    await run_in_threadpool(
        career_service.delete_review,
        post_id,
        member_id,
    )

    return Response(
        status_code=status.HTTP_204_NO_CONTENT
    )