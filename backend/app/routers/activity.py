"""회원 활동 기록과 관리자 전용 통계 API입니다."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.auth import get_current_member_id
from app.services import activity_service, admin_service


router = APIRouter(prefix="/api", tags=["activity"])


class BoardVisit(BaseModel):
    """게시판 진입을 기록하기 위한 요청 형식입니다."""

    board_key: str = Field(min_length=1, max_length=40)


def require_admin(member_id: int = Depends(get_current_member_id)) -> int:
    """관리자 API 호출 때마다 회원 권한을 다시 확인합니다."""
    admin_service.assert_admin(member_id)
    return member_id


@router.post("/activity/ping")
def record_ping(member_id: int = Depends(get_current_member_id)):
    return activity_service.ping(member_id)


@router.post("/activity/board-view")
def record_board_visit(
    payload: BoardVisit,
    member_id: int = Depends(get_current_member_id),
):
    """로그인한 회원의 게시판 진입 한 건을 집계합니다."""
    return activity_service.visit_board(member_id, payload.board_key)


@router.get("/admin/usage")
def get_admin_usage(
    days: int = Query(default=7),
    page: int = Query(default=1, ge=1, le=100000),
    _: int = Depends(require_admin),
):
    """전체·기간별 이용 시간과 인기 게시판을 관리자에게만 제공합니다."""
    if days not in (7, 30):
        raise HTTPException(status_code=422, detail="7일 또는 30일만 선택할 수 있습니다.")
    return activity_service.get_usage(days, page)
