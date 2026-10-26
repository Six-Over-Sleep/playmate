
"""PLAYMATE 취업 카테고리 API 라우터.

취준 도감 후기 등록 및 상세 조회 API를 관리한다.
DB 처리와 트랜잭션은 career_service에서 담당한다.
"""

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.concurrency import run_in_threadpool

from app.core.auth import get_current_member_id

from app.schemas.career import (
    # 취준 도감
    CareerReviewCreate,
    CareerReviewResponse,
    CareerReviewListResponse,
    CareerReviewUpdate,
    ReviewSubcategory,
    ProcessStage,
    ProcessResult,

    # 커리어 톡톡
    CareerTalkCreate,
    CareerTalkUpdate,
    CareerTalkResponse,
    CareerTalkListResponse,
    TalkSubcategory,
    TalkStatus,
)

from app.services import career_service
from app.services import career_reaction_service

# 좋아요·스크랩·댓글은 게시판 공통 요청·응답 형식을 그대로 사용한다.
from app.schemas.board import (
    CommentResponse,
    CommentWrite,
    PostLikeResponse,
    PostScrapResponse,
)

from app.schemas.career import (
    CareerLoungeCreate,
    CareerLoungeUpdate,
    CareerLoungeResponse,
    CareerLoungeListResponse,
    LoungeSubcategory,
)

from app.schemas.career import (
    CareerLabCreate,
    CareerLabUpdate,
    CareerLabResponse,
    CareerLabListResponse,
    CareerLabResolveUpdate,
    CareerLabVoteCreate,
    LabSubcategory,
    LabPostType,
)

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



# =========================================
# 커리어 톡톡 - 게시글 등록
# =========================================

@router.post(
    "/talks",
    response_model=CareerTalkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_talk(
    payload: CareerTalkCreate,
    member_id: int = Depends(get_current_member_id),
):
    """로그인한 회원의 커리어 톡톡 게시글을 등록한다."""

    return await run_in_threadpool(
        career_service.create_talk,
        payload,
        member_id,
    )


# =========================================
# 커리어 톡톡 - 게시글 목록 조회
# =========================================

@router.get(
    "/talks",
    response_model=CareerTalkListResponse,
)
async def list_talks(
    q: str | None = Query(
        default=None,
        max_length=100,
    ),
    subcategory_code: TalkSubcategory | None = Query(
        default=None,
    ),
    job_category_code: str | None = Query(
        default=None,
        min_length=1,
        max_length=50,
    ),
    current_status: TalkStatus | None = Query(
        default=None,
    ),
    page: int = Query(
        default=1,
        ge=1,
    ),
    page_size: int = Query(
        default=10,
        ge=1,
        le=50,
    ),
    member_id: int = Depends(get_current_member_id),
):
    """검색·카테고리·직무·취업 상태별 게시글 목록을 조회한다."""

    return await run_in_threadpool(
        career_service.list_talks,
        member_id=member_id,
        q=q,
        subcategory_code=subcategory_code,
        job_category_code=job_category_code,
        current_status=current_status,
        page=page,
        page_size=page_size,
    )


# =========================================
# 커리어 톡톡 - 게시글 상세 조회
# =========================================

@router.get(
    "/talks/{post_id}",
    response_model=CareerTalkResponse,
)
async def get_talk(
    post_id: int,
    member_id: int = Depends(get_current_member_id),
):
    """게시글 ID로 커리어 톡톡 상세 정보를 조회한다."""

    return await run_in_threadpool(
        career_service.get_talk,
        post_id,
        member_id,
    )


# =========================================
# 커리어 톡톡 - 게시글 수정
# =========================================

@router.patch(
    "/talks/{post_id}",
    response_model=CareerTalkResponse,
)
async def update_talk(
    post_id: int,
    payload: CareerTalkUpdate,
    member_id: int = Depends(get_current_member_id),
):
    """작성자 본인의 커리어 톡톡 게시글을 수정한다."""

    return await run_in_threadpool(
        career_service.update_talk,
        post_id,
        payload,
        member_id,
    )


# =========================================
# 커리어 톡톡 - 게시글 삭제
# =========================================

@router.delete(
    "/talks/{post_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_talk(
    post_id: int,
    member_id: int = Depends(get_current_member_id),
):
    """작성자 본인의 커리어 톡톡 게시글을 논리 삭제한다."""

    await run_in_threadpool(
        career_service.delete_talk,
        post_id,
        member_id,
    )

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
    )

# =========================================================
# 현직자 라운지 Router
# =========================================================


# =========================================================
# 1. 현직자 라운지 게시글 등록
# POST /api/career/lounges
# =========================================================

@router.post(
    "/lounges",
    response_model=CareerLoungeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_lounge(
    payload: CareerLoungeCreate,
    member_id: int = Depends(get_current_member_id),
):
    """로그인한 회원의 현직자 라운지 게시글을 등록한다."""

    return await run_in_threadpool(
        career_service.create_lounge,
        payload,
        member_id,
    )


# =========================================================
# 2. 현직자 라운지 게시글 목록 조회
# GET /api/career/lounges
# =========================================================

@router.get(
    "/lounges",
    response_model=CareerLoungeListResponse,
)
async def list_lounges(
    q: str | None = Query(
        default=None,
        max_length=100,
    ),
    subcategory_code: LoungeSubcategory | None = Query(
        default=None,
    ),
    job_category_code: str | None = Query(
        default=None,
        min_length=1,
        max_length=50,
    ),
    experience_years: int | None = Query(
        default=None,
        ge=0,
        le=32767,
    ),
    page: int = Query(
        default=1,
        ge=1,
    ),
    page_size: int = Query(
        default=10,
        ge=1,
        le=50,
    ),
    member_id: int = Depends(get_current_member_id),
):
    """검색·카테고리·직무·경력 연차별 게시글을 조회한다."""

    return await run_in_threadpool(
        career_service.list_lounges,
        member_id=member_id,
        q=q,
        subcategory_code=subcategory_code,
        job_category_code=job_category_code,
        experience_years=experience_years,
        page=page,
        page_size=page_size,
    )


# =========================================================
# 3. 현직자 라운지 게시글 상세 조회
# GET /api/career/lounges/{post_id}
# =========================================================

@router.get(
    "/lounges/{post_id}",
    response_model=CareerLoungeResponse,
)
async def get_lounge(
    post_id: int,
    member_id: int = Depends(get_current_member_id),
):
    """게시글 ID로 현직자 라운지 상세 정보를 조회한다."""

    return await run_in_threadpool(
        career_service.get_lounge,
        post_id,
        member_id,
    )


# =========================================================
# 4. 현직자 라운지 게시글 수정
# PATCH /api/career/lounges/{post_id}
# =========================================================

@router.patch(
    "/lounges/{post_id}",
    response_model=CareerLoungeResponse,
)
async def update_lounge(
    post_id: int,
    payload: CareerLoungeUpdate,
    member_id: int = Depends(get_current_member_id),
):
    """작성자 본인의 현직자 라운지 게시글을 수정한다."""

    return await run_in_threadpool(
        career_service.update_lounge,
        post_id,
        payload,
        member_id,
    )


# =========================================================
# 5. 현직자 라운지 게시글 삭제
# DELETE /api/career/lounges/{post_id}
# =========================================================

@router.delete(
    "/lounges/{post_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_lounge(
    post_id: int,
    member_id: int = Depends(get_current_member_id),
):
    """작성자 본인의 게시글을 논리 삭제한다."""

    await run_in_threadpool(
        career_service.delete_lounge,
        post_id,
        member_id,
    )

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
    )


# =========================================================
# 커리어 연구소 Router
# =========================================================


# =========================================================
# 1. 게시글 등록
# POST /api/career/labs
# =========================================================

@router.post(
    "/labs",
    response_model=CareerLabResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_lab(
    payload: CareerLabCreate,
    member_id: int = Depends(get_current_member_id),
):
    """질문·토론 게시글을 등록한다."""

    return await run_in_threadpool(
        career_service.create_lab,
        payload,
        member_id,
    )


# =========================================================
# 2. 게시글 목록 조회
# GET /api/career/labs
# =========================================================

@router.get(
    "/labs",
    response_model=CareerLabListResponse,
)
async def list_labs(
    q: str | None = Query(
        default=None,
        max_length=100,
    ),
    subcategory_code: LabSubcategory | None = Query(
        default=None,
    ),
    post_type: LabPostType | None = Query(
        default=None,
    ),
    is_resolved: bool | None = Query(
        default=None,
    ),
    page: int = Query(
        default=1,
        ge=1,
    ),
    page_size: int = Query(
        default=10,
        ge=1,
        le=50,
    ),
    member_id: int = Depends(get_current_member_id),
):
    """검색·유형·해결 여부·페이지별 게시글을 조회한다."""

    return await run_in_threadpool(
        career_service.list_labs,
        member_id=member_id,
        q=q,
        subcategory_code=subcategory_code,
        post_type=post_type,
        is_resolved=is_resolved,
        page=page,
        page_size=page_size,
    )


# =========================================================
# 3. 게시글 상세 조회
# GET /api/career/labs/{post_id}
# =========================================================

@router.get(
    "/labs/{post_id}",
    response_model=CareerLabResponse,
)
async def get_lab(
    post_id: int,
    member_id: int = Depends(get_current_member_id),
):
    """게시글 상세 내용 및 투표 현황을 조회한다."""

    return await run_in_threadpool(
        career_service.get_lab,
        post_id,
        member_id,
    )


# =========================================================
# 4. 게시글 수정
# PATCH /api/career/labs/{post_id}
# =========================================================

@router.patch(
    "/labs/{post_id}",
    response_model=CareerLabResponse,
)
async def update_lab(
    post_id: int,
    payload: CareerLabUpdate,
    member_id: int = Depends(get_current_member_id),
):
    """작성자 본인의 게시글을 수정한다."""

    return await run_in_threadpool(
        career_service.update_lab,
        post_id,
        payload,
        member_id,
    )


# =========================================================
# 5. 게시글 삭제
# DELETE /api/career/labs/{post_id}
# =========================================================

@router.delete(
    "/labs/{post_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_lab(
    post_id: int,
    member_id: int = Depends(get_current_member_id),
):
    """작성자 본인의 게시글을 논리 삭제한다."""

    await run_in_threadpool(
        career_service.delete_lab,
        post_id,
        member_id,
    )

    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
    )


# =========================================================
# 6. 질문 해결 상태 변경
# PATCH /api/career/labs/{post_id}/resolve
# =========================================================

@router.patch(
    "/labs/{post_id}/resolve",
    response_model=CareerLabResponse,
)
async def update_lab_resolved(
    post_id: int,
    payload: CareerLabResolveUpdate,
    member_id: int = Depends(get_current_member_id),
):
    """질문 작성자가 해결 여부를 변경한다."""

    return await run_in_threadpool(
        career_service.update_lab_resolved,
        post_id,
        payload,
        member_id,
    )


# =========================================================
# 7. 토론 게시글 투표
# POST /api/career/labs/{post_id}/votes
# =========================================================

@router.post(
    "/labs/{post_id}/votes",
    response_model=CareerLabResponse,
    status_code=status.HTTP_201_CREATED,
)
async def vote_lab(
    post_id: int,
    payload: CareerLabVoteCreate,
    member_id: int = Depends(get_current_member_id),
):
    """토론 게시글에 한 번 투표한다."""

    return await run_in_threadpool(
        career_service.vote_lab,
        post_id,
        payload,
        member_id,
    )


# =========================================================
# 취업 게시글 4종 공통 - 좋아요·스크랩·댓글
# 취준 도감·커리어 톡톡·현직자 라운지·커리어 연구소 모두 post_id로 처리한다.
# 댓글 수정·삭제는 게시판 공통 API(PATCH/DELETE /api/comments/{comment_id})를 사용한다.
# =========================================================

# PUT /api/career/posts/{post_id}/like : 좋아요 등록 (중복 요청은 현재 상태 반환)
@router.put(
    "/posts/{post_id}/like",
    response_model=PostLikeResponse,
)
async def like_post(
    post_id: int,
    member_id: int = Depends(get_current_member_id),
):
    """취업 게시글에 좋아요를 등록하고 좋아요 수·여부를 반환한다."""

    return await run_in_threadpool(
        career_reaction_service.like_post,
        post_id,
        member_id,
    )


# DELETE /api/career/posts/{post_id}/like : 좋아요 취소 (없어도 성공)
@router.delete(
    "/posts/{post_id}/like",
    response_model=PostLikeResponse,
)
async def unlike_post(
    post_id: int,
    member_id: int = Depends(get_current_member_id),
):
    """취업 게시글 좋아요를 취소하고 좋아요 수·여부를 반환한다."""

    return await run_in_threadpool(
        career_reaction_service.unlike_post,
        post_id,
        member_id,
    )


# PUT /api/career/posts/{post_id}/scrap : 스크랩 등록 (중복 요청은 현재 상태 반환)
@router.put(
    "/posts/{post_id}/scrap",
    response_model=PostScrapResponse,
)
async def scrap_post(
    post_id: int,
    member_id: int = Depends(get_current_member_id),
):
    """취업 게시글을 스크랩하고 스크랩 여부를 반환한다."""

    return await run_in_threadpool(
        career_reaction_service.scrap_post,
        post_id,
        member_id,
    )


# DELETE /api/career/posts/{post_id}/scrap : 스크랩 취소 (없어도 성공)
@router.delete(
    "/posts/{post_id}/scrap",
    response_model=PostScrapResponse,
)
async def unscrap_post(
    post_id: int,
    member_id: int = Depends(get_current_member_id),
):
    """취업 게시글 스크랩을 취소하고 스크랩 여부를 반환한다."""

    return await run_in_threadpool(
        career_reaction_service.unscrap_post,
        post_id,
        member_id,
    )


# GET /api/career/posts/{post_id}/comments : 댓글 목록 (부모 → 대댓글 순서, 삭제 자리표시 포함)
@router.get(
    "/posts/{post_id}/comments",
    response_model=list[CommentResponse],
)
async def list_comments(
    post_id: int,
    member_id: int = Depends(get_current_member_id),
):
    """취업 게시글의 댓글과 대댓글을 조회한다."""

    return await run_in_threadpool(
        career_reaction_service.list_comments,
        post_id,
        member_id,
    )


# POST /api/career/posts/{post_id}/comments : 댓글·대댓글 작성 (parent_comment_id가 있으면 대댓글)
@router.post(
    "/posts/{post_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_comment(
    post_id: int,
    payload: CommentWrite,
    member_id: int = Depends(get_current_member_id),
):
    """취업 게시글에 댓글 또는 1단계 대댓글을 작성한다."""

    return await run_in_threadpool(
        career_reaction_service.create_comment,
        post_id,
        payload.body,
        member_id,
        payload.parent_comment_id,
        payload.is_anonymous,
    )
