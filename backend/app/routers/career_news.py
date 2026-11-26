"""PLAYMATE 커리어 브리핑 뉴스 API 라우터 (Issue #74).

뉴스 목록 조회와 회원별 뉴스 스크랩을 관리한다. DB 처리와 트랜잭션은 career_news_service에서 담당한다.
기존 취업 게시글 API(routers/career.py)와 같은 /api/career 아래에 두되 파일은 분리한다.
"""

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool

from app.core.auth import get_current_member_id
from app.schemas.career_news import (
    CareerNewsDetailResponse,
    CareerNewsFieldCode,
    CareerNewsListResponse,
    CareerNewsMyScrapListResponse,
    CareerNewsScrapResponse,
)
from app.services import career_news_service

# 커리어 브리핑 뉴스 API
router = APIRouter(
    prefix="/api/career/news",
    tags=["career-news"],
)


# GET /api/career/news : 최근 뉴스 목록 (직무 분야 필터, 최신순)
@router.get(
    "",
    response_model=CareerNewsListResponse,
)
async def list_news(
    field_code: CareerNewsFieldCode | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=90),
    limit: int = Query(default=100, ge=1, le=300),
    member_id: int = Depends(get_current_member_id),
):
    """최근 days일 동안의 숨기지 않은 뉴스를 최신순으로 반환한다. 결과가 없으면 빈 목록이다."""

    return await run_in_threadpool(
        career_news_service.list_news,
        member_id,
        field_code,
        days,
        limit,
    )


# GET /api/career/news/scraps : 내가 스크랩한 뉴스 최근 목록 (마이페이지 내 스크랩)
# /{news_id}보다 먼저 선언해야 'scraps'가 뉴스 ID로 해석되지 않는다.
@router.get(
    "/scraps",
    response_model=CareerNewsMyScrapListResponse,
)
async def list_my_scraps(
    limit: int = Query(default=20, ge=1, le=50),
    member_id: int = Depends(get_current_member_id),
):
    """내가 스크랩한 뉴스 중 최근 limit건을 스크랩 최신순으로 반환한다. 숨긴 뉴스도 표시용으로 포함한다."""

    return await run_in_threadpool(
        career_news_service.list_my_scraps,
        member_id,
        limit,
    )


# GET /api/career/news/{news_id} : 뉴스 상세 (기간 제한 없음, 숨긴 뉴스는 내 스크랩일 때만)
@router.get(
    "/{news_id}",
    response_model=CareerNewsDetailResponse,
)
async def get_news(
    news_id: int,
    member_id: int = Depends(get_current_member_id),
):
    """뉴스 한 건을 반환한다. 없거나 볼 수 없는 뉴스는 404다."""

    return await run_in_threadpool(
        career_news_service.get_news,
        news_id,
        member_id,
    )


# PUT /api/career/news/{news_id}/scrap : 뉴스 스크랩 등록 (중복 요청은 현재 상태 반환)
@router.put(
    "/{news_id}/scrap",
    response_model=CareerNewsScrapResponse,
)
async def scrap_news(
    news_id: int,
    member_id: int = Depends(get_current_member_id),
):
    """뉴스를 스크랩하고 스크랩 여부를 반환한다."""

    return await run_in_threadpool(
        career_news_service.scrap_news,
        news_id,
        member_id,
    )


# DELETE /api/career/news/{news_id}/scrap : 뉴스 스크랩 취소 (없어도 성공)
@router.delete(
    "/{news_id}/scrap",
    response_model=CareerNewsScrapResponse,
)
async def unscrap_news(
    news_id: int,
    member_id: int = Depends(get_current_member_id),
):
    """뉴스 스크랩을 취소하고 스크랩 여부를 반환한다."""

    return await run_in_threadpool(
        career_news_service.unscrap_news,
        news_id,
        member_id,
    )
