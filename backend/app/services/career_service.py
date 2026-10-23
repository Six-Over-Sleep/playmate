"""PLAYMATE 취준 도감 후기 등록·상세 조회 업무를 처리한다.

DB 트랜잭션은 Service가 관리하고, SQL은 Repository에 맡긴다.
"""

from fastapi import HTTPException

from app.core.db_connect import db_cursor
from app.repositories import career_repository
from app.schemas.career import CareerReviewCreate, CareerReviewResponse
from app.schemas.career import (
    CareerReviewCreate,
    CareerReviewResponse,
    CareerReviewListResponse,
)
from app.schemas.career import CareerReviewUpdate

def create_review(payload: CareerReviewCreate, member_id: int) -> CareerReviewResponse:
    """게시글·취업 분류·후기를 하나의 트랜잭션으로 저장한다."""
    with db_cursor(commit=True) as cursor:
        # Repository는 commit하지 않으므로 세 테이블 저장은 함께 성공하거나 롤백된다.
        post_id = career_repository.create_review(
            cursor,
            member_id,
            payload.model_dump(),
        )

        # 커밋하기 전에 상세 데이터를 읽고 응답 형식까지 검증한다.
        # 조회·검증에 실패하면 with 블록을 벗어나면서 커밋되지 않는다.
        review = career_repository.get_review(cursor, post_id, member_id)
        if review is None:
            raise HTTPException(status_code=500, detail="등록한 후기를 조회하지 못했습니다.")

        return CareerReviewResponse.model_validate(review)


def get_review(post_id: int, member_id: int) -> CareerReviewResponse:
    """삭제되지 않은 후기를 조회한다. 없으면 404를 반환한다."""
    with db_cursor(read_only=True) as cursor:
        review = career_repository.get_review(cursor, post_id, member_id)
        if review is None:
            raise HTTPException(status_code=404, detail="취업 후기를 찾을 수 없습니다.")

        return CareerReviewResponse.model_validate(review)

# =========================================
# 취준 도감 - 후기 목록 조회
# =========================================

def list_reviews(
    member_id: int,
    page: int = 1,
    page_size: int = 10,
    q: str | None = None,
    subcategory_code: str | None = None,
    job_category_code: str | None = None,
    process_stage: str | None = None,
    process_result: str | None = None,
) -> CareerReviewListResponse:
    """검색 조건에 맞는 취업 후기 목록을 조회한다."""

    with db_cursor(read_only=True) as cursor:

        result = career_repository.list_reviews(
            cursor=cursor,
            member_id=member_id,
            q=q,
            subcategory_code=subcategory_code,
            job_category_code=job_category_code,
            process_stage=process_stage,
            process_result=process_result,
            page=page,
            page_size=page_size,
        )

        return CareerReviewListResponse.model_validate(result)


# =========================================
# 취준 도감 - 후기 수정
# =========================================

def update_review(
    post_id: int,
    payload: CareerReviewUpdate,
    member_id: int,
) -> CareerReviewResponse:
    """작성자 권한 확인 후 후기를 수정한다."""

    with db_cursor(commit=True) as cursor:

        # 1. 작성자 확인 및 행 잠금
        author_id = career_repository.get_review_author_for_update(
            cursor,
            post_id,
        )

        # 2. 게시글 존재 여부
        if author_id is None:
            raise HTTPException(
                status_code=404,
                detail="취업 후기를 찾을 수 없습니다.",
            )

        # 3. 작성자 권한 확인
        if author_id != member_id:
            raise HTTPException(
                status_code=403,
                detail="작성자만 후기를 수정할 수 있습니다.",
            )

        # 4. 전달된 항목만 추출
        changes = payload.model_dump(exclude_unset=True)

        # 5. DB 수정
        career_repository.update_review(
            cursor,
            post_id,
            changes,
        )

        # 6. 수정된 후기 재조회
        review = career_repository.get_review(
            cursor,
            post_id,
            member_id,
        )

        if review is None:
            raise HTTPException(
                status_code=500,
                detail="수정한 후기를 조회하지 못했습니다.",
            )

        # 7. 응답 검증 후 트랜잭션 커밋
        return CareerReviewResponse.model_validate(review)
    
# =========================================
# 취준 도감 - 후기 삭제
# =========================================

def delete_review(post_id: int, member_id: int) -> None:
    """작성자 권한을 확인한 뒤 후기를 논리 삭제한다."""

    with db_cursor(commit=True) as cursor:

        # 1. 게시글 존재 확인 및 행 잠금
        author_id = career_repository.get_review_author_for_update(
            cursor,
            post_id,
        )

        # 2. 존재하지 않거나 이미 삭제된 게시글
        if author_id is None:
            raise HTTPException(
                status_code=404,
                detail="취업 후기를 찾을 수 없습니다.",
            )

        # 3. 작성자 권한 검증
        if author_id != member_id:
            raise HTTPException(
                status_code=403,
                detail="작성자만 후기를 삭제할 수 있습니다.",
            )

        # 4. 논리 삭제
        deleted = career_repository.delete_review(
            cursor,
            post_id,
            member_id,
        )

        if not deleted:
            raise HTTPException(
                status_code=404,
                detail="취업 후기를 삭제하지 못했습니다.",
            )