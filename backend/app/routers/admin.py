"""관리자 전용 API. 모든 엔드포인트에서 서버 측 역할 검증."""

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from app.core.auth import get_current_member_id
from app.services import admin_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


class NoticeWrite(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    title: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=20000)


class VisibilityWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hidden: bool


def require_admin(member_id: int = Depends(get_current_member_id)) -> int:
    admin_service.assert_admin(member_id)
    return member_id


@router.get("/dashboard")
def dashboard(_: int = Depends(require_admin)):
    return admin_service.dashboard()


@router.get("/notices")
def list_notices(_: int = Depends(require_admin)):
    return admin_service.notices()


@router.post("/notices", status_code=status.HTTP_201_CREATED)
def create_notice(data: NoticeWrite, member_id: int = Depends(require_admin)):
    return admin_service.create_notice(member_id, data.title, data.body)


@router.patch("/notices/{post_id}")
def update_notice(post_id: int, data: NoticeWrite, _: int = Depends(require_admin)):
    return admin_service.update_notice(post_id, data.title, data.body)


@router.delete("/notices/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_notice(post_id: int, _: int = Depends(require_admin)):
    admin_service.delete_notice(post_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/posts")
def list_posts(q: str = Query(default="", max_length=100), _: int = Depends(require_admin)):
    return admin_service.board_posts(q.strip())


@router.patch("/posts/{post_id}/visibility", status_code=status.HTTP_204_NO_CONTENT)
def set_visibility(post_id: int, data: VisibilityWrite, _: int = Depends(require_admin)):
    admin_service.change_post_visibility(post_id, data.hidden)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/members")
def list_members(_: int = Depends(require_admin)):
    return admin_service.members()
