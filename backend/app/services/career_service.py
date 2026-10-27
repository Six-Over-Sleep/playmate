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
from app.schemas.career import (
    CareerTalkCreate,
    CareerTalkUpdate,
    CareerTalkResponse,
    CareerTalkListResponse,
)

from app.schemas.career import (
    CareerLoungeCreate,
    CareerLoungeUpdate,
    CareerLoungeResponse,
    CareerLoungeListResponse,
)

from app.schemas.career import (
    CareerLabCreate,
    CareerLabUpdate,
    CareerLabResponse,
    CareerLabListResponse,
    CareerLabResolveUpdate,
    CareerLabVoteCreate,
)

import logging

from app.services.xp_service import (
    grant_career_review_xp,
    revoke_xp,
    reconcile_career_review_xp,
    grant_career_guide_xp,
)

logger = logging.getLogger(__name__)


# 취준 도감 후기 작성 및 XP 지급
def create_review(
    payload: CareerReviewCreate,
    member_id: int,
) -> CareerReviewResponse:

    # 1. 게시글 및 취업 후기 저장
    with db_cursor(commit=True) as cursor:
        post_id = career_repository.create_review(
            cursor,
            member_id,
            payload.model_dump(),
        )

        # 2. 저장된 후기 조회
        review = career_repository.get_review(
            cursor,
            post_id,
            member_id,
        )

        if review is None:
            raise HTTPException(
                status_code=500,
                detail="등록한 후기를 조회하지 못했습니다.",
            )

        response = CareerReviewResponse.model_validate(review)

    # 3. DB 저장 성공 후 XP 지급
    if member_id > 0:
        try:
            result = grant_career_review_xp(
                member_id,
                post_id,
            )

            if result["awarded"]:
                logger.info(
                    "취업 후기 XP 지급 완료: post_id=%s, xp=%s",
                    post_id,
                    result["earned_xp"],
                )
            else:
                logger.info(
                    "취업 후기 XP 미지급: post_id=%s, reason=%s",
                    post_id,
                    result["reason"],
                )

        except Exception:
            logger.exception(
                "취업 후기 XP 지급 실패: post_id=%s",
                post_id,
            )

    # 4. 작성된 후기 반환
    return response



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

        # 7. 수정된 후기 응답 검증
        response = CareerReviewResponse.model_validate(review)

        # 8. 수정된 후기 유형을 기준으로 XP 차액 정산
        # 게시글 수정과 XP 정산은 같은 트랜잭션에서 처리됨
        xp_result = reconcile_career_review_xp(cursor, member_id, post_id)
        logger.info(
            "취업 후기 XP 정산: post_id=%s, result=%s",
            post_id,
            xp_result,
        )

        return response
    
# =========================================
# 취준 도감 - 후기 삭제
# =========================================


# 취업 후기 삭제 및 XP 자동 회수
def delete_review(post_id: int, member_id: int) -> None:
    """취업 후기 삭제와 XP 회수를 같은 트랜잭션에서 처리한다."""

    with db_cursor(commit=True) as cursor:

        # 1. 게시글 존재 및 작성자 확인
        author_id = career_repository.get_review_author_for_update(
            cursor,
            post_id,
        )

        if author_id is None:
            raise HTTPException(
                status_code=404,
                detail="취업 후기를 찾을 수 없습니다.",
            )

        # 2. 작성자 권한 검증
        if author_id != member_id:
            raise HTTPException(
                status_code=403,
                detail="작성자만 후기를 삭제할 수 있습니다.",
            )

        # 3. 게시글 논리 삭제
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

        # 4. 지급받은 XP 회수
        # XP 이력이 없다면 회수 없이 삭제만 완료
        # 이미 회수한 XP는 다시 회수하지 않음
        revoke_xp(
            cursor,
            member_id,
            "POST",
            post_id,
        )



# =========================================
# 커리어 톡톡 - 게시글 등록
# =========================================

def create_talk(
    payload: CareerTalkCreate,
    member_id: int,
) -> CareerTalkResponse:
    """커리어 톡톡 게시글을 등록한다.

    posts, career_posts, career_talks를
    하나의 트랜잭션으로 저장한다.
    """

    with db_cursor(commit=True) as cursor:

        # 1. 입력 데이터를 Dictionary로 변환
        data = payload.model_dump()

        # 2. 게시글과 상세 정보 저장
        post_id = career_repository.create_talk(
            cursor,
            member_id,
            data,
        )

        # 3. 저장한 게시글 상세 조회
        talk = career_repository.get_talk(
            cursor,
            post_id,
            member_id,
        )

        # 4. 조회 실패 시 트랜잭션 롤백
        if talk is None:
            raise HTTPException(
                status_code=500,
                detail="등록한 게시글을 조회하지 못했습니다.",
            )

        # 5. 응답 검증 후 트랜잭션 커밋
        return CareerTalkResponse.model_validate(talk)


# =========================================
# 커리어 톡톡 - 게시글 목록 조회
# =========================================

def list_talks(
    member_id: int,
    page: int = 1,
    page_size: int = 10,
    q: str | None = None,
    subcategory_code: str | None = None,
    job_category_code: str | None = None,
    current_status: str | None = None,
) -> CareerTalkListResponse:
    """검색, 필터, 페이지네이션을 적용한다."""

    with db_cursor(read_only=True) as cursor:

        # 1. Repository에서 목록 조회
        result = career_repository.list_talks(
            cursor=cursor,
            member_id=member_id,
            q=q,
            subcategory_code=subcategory_code,
            job_category_code=job_category_code,
            current_status=current_status,
            page=page,
            page_size=page_size,
        )

        # 2. 응답 데이터 검증
        return CareerTalkListResponse.model_validate(
            result
        )


# =========================================
# 커리어 톡톡 - 게시글 상세 조회
# =========================================

def get_talk(
    post_id: int,
    member_id: int,
) -> CareerTalkResponse:
    """게시글 ID로 상세 정보를 조회한다."""

    with db_cursor(read_only=True) as cursor:

        # 1. 게시글 조회
        talk = career_repository.get_talk(
            cursor,
            post_id,
            member_id,
        )

        # 2. 존재하지 않거나 삭제된 게시글
        if talk is None:
            raise HTTPException(
                status_code=404,
                detail="커리어 톡톡 게시글을 찾을 수 없습니다.",
            )

        # 3. 응답 데이터 검증
        return CareerTalkResponse.model_validate(talk)


# =========================================
# 커리어 톡톡 - 게시글 수정
# =========================================

def update_talk(
    post_id: int,
    payload: CareerTalkUpdate,
    member_id: int,
) -> CareerTalkResponse:
    """작성자 본인의 게시글만 수정한다."""

    with db_cursor(commit=True) as cursor:

        # 1. 게시글 잠금 및 작성자 확인
        author_id = (
            career_repository.get_talk_author_for_update(
                cursor,
                post_id,
            )
        )

        # 2. 존재하지 않거나 삭제된 게시글
        if author_id is None:
            raise HTTPException(
                status_code=404,
                detail="커리어 톡톡 게시글을 찾을 수 없습니다.",
            )

        # 3. 작성자 권한 검사
        if author_id != member_id:
            raise HTTPException(
                status_code=403,
                detail="작성자만 게시글을 수정할 수 있습니다.",
            )

        # 4. 전달된 필드만 추출
        changes = payload.model_dump(
            exclude_unset=True
        )

        # 5. 게시글 수정
        career_repository.update_talk(
            cursor,
            post_id,
            changes,
        )

        # 6. 수정된 게시글 재조회
        talk = career_repository.get_talk(
            cursor,
            post_id,
            member_id,
        )

        # 7. 수정 결과 조회 실패
        if talk is None:
            raise HTTPException(
                status_code=500,
                detail="수정한 게시글을 조회하지 못했습니다.",
            )

        # 8. 응답 검증 후 트랜잭션 커밋
        return CareerTalkResponse.model_validate(talk)


# =========================================
# 커리어 톡톡 - 게시글 논리 삭제
# =========================================

def delete_talk(
    post_id: int,
    member_id: int,
) -> None:
    """작성자 본인의 게시글을 논리 삭제한다."""

    with db_cursor(commit=True) as cursor:

        # 1. 게시글 잠금 및 작성자 확인
        author_id = (
            career_repository.get_talk_author_for_update(
                cursor,
                post_id,
            )
        )

        # 2. 존재하지 않거나 이미 삭제된 게시글
        if author_id is None:
            raise HTTPException(
                status_code=404,
                detail="커리어 톡톡 게시글을 찾을 수 없습니다.",
            )

        # 3. 작성자 권한 검사
        if author_id != member_id:
            raise HTTPException(
                status_code=403,
                detail="작성자만 게시글을 삭제할 수 있습니다.",
            )

        # 4. 논리 삭제
        deleted = career_repository.delete_talk(
            cursor,
            post_id,
            member_id,
        )

        # 5. 삭제 실패
        if not deleted:
            raise HTTPException(
                status_code=404,
                detail="게시글을 삭제하지 못했습니다.",
            )


# =========================================================
# 현직자 라운지 Service
# =========================================================


# =========================================================
# 1. 현직자 라운지 게시글 등록
# =========================================================

def create_lounge(
    payload: CareerLoungeCreate,
    member_id: int,
) -> CareerLoungeResponse:
    """현직자 라운지 게시글을 등록한다.

    posts, career_posts, career_lounges
    세 테이블을 하나의 트랜잭션으로 저장한다.
    """

    with db_cursor(commit=True) as cursor:

        # 1. Pydantic 데이터를 딕셔너리로 변환
        data = payload.model_dump()

        # 2. 게시글 등록
        post_id = career_repository.create_lounge(
            cursor,
            member_id,
            data,
        )

        # 3. 등록한 게시글 조회
        lounge = career_repository.get_lounge(
            cursor,
            post_id,
            member_id,
        )

        # 4. 게시글 조회 실패
        if lounge is None:
            raise HTTPException(
                status_code=500,
                detail="등록한 현직자 라운지 게시글을 조회하지 못했습니다.",
            )

        # 5. 응답 스키마 검증
        return CareerLoungeResponse.model_validate(lounge)


# =========================================================
# 2. 현직자 라운지 게시글 목록 조회
# =========================================================

def list_lounges(
    member_id: int,
    page: int = 1,
    page_size: int = 10,
    q: str | None = None,
    subcategory_code: str | None = None,
    job_category_code: str | None = None,
    experience_years: int | None = None,
) -> CareerLoungeListResponse:
    """검색 조건과 페이지네이션을 적용한다."""

    with db_cursor(read_only=True) as cursor:

        # 1. Repository에서 게시글 목록 조회
        result = career_repository.list_lounges(
            cursor=cursor,
            member_id=member_id,
            q=q,
            subcategory_code=subcategory_code,
            job_category_code=job_category_code,
            experience_years=experience_years,
            page=page,
            page_size=page_size,
        )

        # 2. 목록 응답 검증
        return CareerLoungeListResponse.model_validate(
            result
        )


# =========================================================
# 3. 현직자 라운지 게시글 상세 조회
# =========================================================

def get_lounge(
    post_id: int,
    member_id: int,
) -> CareerLoungeResponse:
    """게시글 ID로 상세 정보를 조회한다."""

    with db_cursor(read_only=True) as cursor:

        # 1. 게시글 조회
        lounge = career_repository.get_lounge(
            cursor,
            post_id,
            member_id,
        )

        # 2. 게시글이 없거나 삭제된 경우
        if lounge is None:
            raise HTTPException(
                status_code=404,
                detail="현직자 라운지 게시글을 찾을 수 없습니다.",
            )

        # 3. 상세 응답 검증
        return CareerLoungeResponse.model_validate(lounge)


# =========================================================
# 4. 현직자 라운지 게시글 수정
# =========================================================

def update_lounge(
    post_id: int,
    payload: CareerLoungeUpdate,
    member_id: int,
) -> CareerLoungeResponse:
    """작성자 본인의 게시글만 수정한다."""

    with db_cursor(commit=True) as cursor:

        # 1. 게시글 행 잠금 및 작성자 확인
        author_id = (
            career_repository.get_lounge_author_for_update(
                cursor,
                post_id,
            )
        )

        # 2. 존재하지 않는 게시글
        if author_id is None:
            raise HTTPException(
                status_code=404,
                detail="현직자 라운지 게시글을 찾을 수 없습니다.",
            )

        # 3. 작성자 권한 검사
        if author_id != member_id:
            raise HTTPException(
                status_code=403,
                detail="작성자만 게시글을 수정할 수 있습니다.",
            )

        # 4. 요청에 포함된 수정 항목만 추출
        changes = payload.model_dump(
            exclude_unset=True
        )

        # 5. 게시글 수정
        career_repository.update_lounge(
            cursor,
            post_id,
            changes,
        )

        # 6. 수정된 게시글 재조회
        lounge = career_repository.get_lounge(
            cursor,
            post_id,
            member_id,
        )

        # 7. 수정 결과 조회 실패
        if lounge is None:
            raise HTTPException(
                status_code=500,
                detail="수정한 게시글을 조회하지 못했습니다.",
            )

        # 8. 응답 검증
        return CareerLoungeResponse.model_validate(lounge)


# =========================================================
# 5. 현직자 라운지 게시글 논리 삭제
# =========================================================

def delete_lounge(
    post_id: int,
    member_id: int,
) -> None:
    """작성자 본인의 게시글을 논리 삭제한다."""

    with db_cursor(commit=True) as cursor:

        # 1. 게시글 잠금 및 작성자 확인
        author_id = (
            career_repository.get_lounge_author_for_update(
                cursor,
                post_id,
            )
        )

        # 2. 게시글 존재 여부 검사
        if author_id is None:
            raise HTTPException(
                status_code=404,
                detail="현직자 라운지 게시글을 찾을 수 없습니다.",
            )

        # 3. 작성자 권한 검사
        if author_id != member_id:
            raise HTTPException(
                status_code=403,
                detail="작성자만 게시글을 삭제할 수 있습니다.",
            )

        # 4. 논리 삭제
        deleted = career_repository.delete_lounge(
            cursor,
            post_id,
            member_id,
        )

        # 5. 삭제 실패
        if not deleted:
            raise HTTPException(
                status_code=404,
                detail="게시글을 삭제하지 못했습니다.",
            )


# =========================================================
# 커리어 연구소 Service
# =========================================================


# =========================================================
# 1. 게시글 등록
# =========================================================

# 커리어 연구소 게시글 작성
def create_lab(
    payload: CareerLabCreate,
    member_id: int,
) -> CareerLabResponse:

    with db_cursor(commit=True) as cursor:

        # 1. 입력 데이터 변환
        data = payload.model_dump()

        # 2. 게시글 DB 저장
        post_id = career_repository.create_lab(
            cursor,
            member_id,
            data,
        )

        # 3. 저장된 게시글 조회
        lab = career_repository.get_lab(
            cursor,
            post_id,
            member_id,
        )

        if lab is None:
            raise HTTPException(
                status_code=500,
                detail="등록한 게시글을 조회하지 못했습니다.",
            )

        # 4. 응답 데이터 검증
        response = CareerLabResponse.model_validate(lab)

        # 5. GUIDE 게시글에만 +50XP 지급
        if payload.post_type == "GUIDE":

            grant_career_guide_xp(
                cursor,
                member_id,
                post_id,
            )

        # 6. 게시글 등록 결과 반환
        return response

# =========================================================
# 2. 게시글 목록 조회
# =========================================================

def list_labs(
    member_id: int,
    page: int = 1,
    page_size: int = 10,
    q: str | None = None,
    subcategory_code: str | None = None,
    post_type: str | None = None,
    is_resolved: bool | None = None,
) -> CareerLabListResponse:
    """검색·필터·페이지네이션을 적용한다."""

    with db_cursor(read_only=True) as cursor:

        result = career_repository.list_labs(
            cursor=cursor,
            member_id=member_id,
            q=q,
            subcategory_code=subcategory_code,
            post_type=post_type,
            is_resolved=is_resolved,
            page=page,
            page_size=page_size,
        )

        return CareerLabListResponse.model_validate(
            result
        )


# =========================================================
# 3. 게시글 상세 조회
# =========================================================

def get_lab(
    post_id: int,
    member_id: int,
) -> CareerLabResponse:
    """게시글 상세 내용과 투표 현황을 조회한다."""

    with db_cursor(read_only=True) as cursor:

        lab = career_repository.get_lab(
            cursor,
            post_id,
            member_id,
        )

        if lab is None:
            raise HTTPException(
                status_code=404,
                detail="커리어 연구소 게시글을 찾을 수 없습니다.",
            )

        return CareerLabResponse.model_validate(lab)


# =========================================================
# 4. 게시글 수정
# =========================================================

def update_lab(
    post_id: int,
    payload: CareerLabUpdate,
    member_id: int,
) -> CareerLabResponse:
    """작성자 본인의 게시글만 수정한다."""

    with db_cursor(commit=True) as cursor:

        # 1. 작성자 확인 및 행 잠금
        author_id = (
            career_repository.get_lab_author_for_update(
                cursor,
                post_id,
            )
        )

        # 2. 게시글 존재 여부
        if author_id is None:
            raise HTTPException(
                status_code=404,
                detail="커리어 연구소 게시글을 찾을 수 없습니다.",
            )

        # 3. 작성자 권한 검사
        if author_id != member_id:
            raise HTTPException(
                status_code=403,
                detail="작성자만 게시글을 수정할 수 있습니다.",
            )

        # 4. 수정 요청에 포함된 필드만 추출
        changes = payload.model_dump(
            exclude_unset=True
        )

        # GUIDE 수정 조건 검사

        # 1. 현재 게시글 정보 조회
        current_lab = career_repository.get_lab(
            cursor,
            post_id,
            member_id,
        )

        if current_lab is None:
            raise HTTPException(
                status_code=404,
                detail="게시글을 찾을 수 없습니다.",
            )

        # 2. GUIDE 게시글인 경우
        if current_lab["post_type"] == "GUIDE":

            # 수정 요청에 값이 있으면 새 값 사용
            # 없으면 기존 DB 값 유지
            body = changes.get(
                "body",
                current_lab["body"],
            )

            experience = changes.get(
                "guide_experience",
                current_lab["guide_experience"],
            )

            advice = changes.get(
                "guide_advice",
                current_lab["guide_advice"],
            )

            # 본문 최소 500자
            if len((body or "").strip()) < 500:
                raise HTTPException(
                    status_code=400,
                    detail="커리어 가이드 본문은 500자 이상이어야 합니다.",
                )

            # 경험 및 근거 최소 100자
            if len((experience or "").strip()) < 100:
                raise HTTPException(
                    status_code=400,
                    detail="경험 및 근거는 100자 이상이어야 합니다.",
                )

            # 실질적인 조언 최소 100자
            if len((advice or "").strip()) < 100:
                raise HTTPException(
                    status_code=400,
                    detail="실질적인 조언은 100자 이상이어야 합니다.",
                )

        # 3. QUESTION / DISCUSSION 게시글인 경우
        else:
            if (
                "guide_experience" in changes
                or "guide_advice" in changes
            ):
                raise HTTPException(
                    status_code=400,
                    detail="가이드 전용 항목은 GUIDE 게시글에서만 수정할 수 있습니다.",
                )
    
        # 5. 게시글 수정
        career_repository.update_lab(
            cursor,
            post_id,
            changes,
        )

        # 6. 수정한 게시글 재조회
        lab = career_repository.get_lab(
            cursor,
            post_id,
            member_id,
        )

        if lab is None:
            raise HTTPException(
                status_code=500,
                detail="수정한 게시글을 조회하지 못했습니다.",
            )

        return CareerLabResponse.model_validate(lab)


# =========================================================
# 5. 게시글 논리 삭제
# =========================================================

def delete_lab(
    post_id: int,
    member_id: int,
) -> None:
    """작성자 본인의 게시글을 논리 삭제한다."""

    with db_cursor(commit=True) as cursor:

        # 1. 작성자 확인 및 행 잠금
        author_id = (
            career_repository.get_lab_author_for_update(
                cursor,
                post_id,
            )
        )

        if author_id is None:
            raise HTTPException(
                status_code=404,
                detail="커리어 연구소 게시글을 찾을 수 없습니다.",
            )

        # 2. 작성자 권한 확인
        if author_id != member_id:
            raise HTTPException(
                status_code=403,
                detail="작성자만 게시글을 삭제할 수 있습니다.",
            )

        # 3. 논리 삭제
        deleted = career_repository.delete_lab(
            cursor,
            post_id,
            member_id,
        )

        if not deleted:
            raise HTTPException(
                status_code=404,
                detail="게시글을 삭제하지 못했습니다.",
            )

        # 4. 게시글 작성으로 지급받은 XP 회수
        # GUIDE 게시글은 50XP 회수
        # QUESTION / DISCUSSION은 지급 내역이 없으므로 회수하지 않음
        revoke_xp(
            cursor,
            member_id,
            "POST",
            post_id,
        )


# =========================================================
# 6. 질문 해결 상태 변경
# =========================================================

def update_lab_resolved(
    post_id: int,
    payload: CareerLabResolveUpdate,
    member_id: int,
) -> CareerLabResponse:
    """질문 작성자만 해결 상태를 변경할 수 있다."""

    with db_cursor(commit=True) as cursor:

        # 1. 작성자 확인 및 게시글 잠금
        author_id = (
            career_repository.get_lab_author_for_update(
                cursor,
                post_id,
            )
        )

        if author_id is None:
            raise HTTPException(
                status_code=404,
                detail="커리어 연구소 게시글을 찾을 수 없습니다.",
            )

        # 2. 작성자 권한 확인
        if author_id != member_id:
            raise HTTPException(
                status_code=403,
                detail="작성자만 해결 상태를 변경할 수 있습니다.",
            )

        # 3. 해결 여부 변경
        updated = career_repository.update_lab_resolved(
            cursor,
            post_id,
            payload.is_resolved,
        )

        # DISCUSSION 게시글은 변경 불가
        if not updated:
            raise HTTPException(
                status_code=400,
                detail="질문 게시글만 해결 상태를 변경할 수 있습니다.",
            )

        # 4. 변경 결과 조회
        lab = career_repository.get_lab(
            cursor,
            post_id,
            member_id,
        )

        if lab is None:
            raise HTTPException(
                status_code=500,
                detail="변경한 게시글을 조회하지 못했습니다.",
            )

        return CareerLabResponse.model_validate(lab)


# =========================================================
# 7. 토론 게시글 투표
# =========================================================

def vote_lab(
    post_id: int,
    payload: CareerLabVoteCreate,
    member_id: int,
) -> CareerLabResponse:
    """회원이 토론 게시글의 선택지에 투표한다.

    한 회원은 동일 게시글에 한 번만 투표할 수 있다.
    """

    with db_cursor(commit=True) as cursor:

        # 1. 게시글 조회 및 잠금
        lab_info = (
            career_repository.get_lab_poll_for_update(
                cursor,
                post_id,
            )
        )

        if lab_info is None:
            raise HTTPException(
                status_code=404,
                detail="커리어 연구소 게시글을 찾을 수 없습니다.",
            )

        # 2. 토론 게시글인지 확인
        if lab_info["post_type"] != "DISCUSSION":
            raise HTTPException(
                status_code=400,
                detail="토론 게시글에서만 투표할 수 있습니다.",
            )

        # 3. 선택지가 해당 게시글에 속하는지 확인
        option_exists = (
            career_repository.lab_poll_option_exists(
                cursor,
                post_id,
                payload.option_id,
            )
        )

        if not option_exists:
            raise HTTPException(
                status_code=400,
                detail="유효하지 않은 투표 선택지입니다.",
            )

        # 4. 투표 기록 등록
        created = career_repository.create_lab_vote(
            cursor,
            post_id,
            member_id,
            payload.option_id,
        )

        # 5. 중복 투표 방지
        if not created:
            raise HTTPException(
                status_code=409,
                detail="이미 투표한 게시글입니다.",
            )

        # 6. 투표 결과 재조회
        lab = career_repository.get_lab(
            cursor,
            post_id,
            member_id,
        )

        if lab is None:
            raise HTTPException(
                status_code=500,
                detail="투표 결과를 조회하지 못했습니다.",
            )

        return CareerLabResponse.model_validate(lab)
