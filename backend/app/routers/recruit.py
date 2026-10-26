# 모임의 생성, 조회, 수정, 삭제 및 참여 관리 API를 연결하는 Router
from fastapi import APIRouter, Body, Depends, Header
from sqlalchemy.orm import Session
from fastapi import Request, HTTPException
from backend.app.core.database import get_db
from backend.app.core.auth import get_current_member_id
from backend.app.core.recruit_config import programs_enabled
from backend.app.schemas.recruit_dispatch import RecruitCreation
from backend.app.services.recruit_dispatch_service import RecruitDispatchService
from backend.app.services.recruit_program_service import ProgramService
from backend.app.routers.recruit_program import build_program_service, invoke
from backend.app.schemas.recruit import (
    RecruitCommentCreate,
    RecruitCommentUpdate,
)
from backend.app.services import recruit_comment as comment_service
from backend.app.services import recruit_reaction as reaction_service


# prefix : 모든 API 주소 앞에 공통으로 붙는 경로
# tags : API 문서(Swagger UI)에서 표시할 그룹 이름
router = APIRouter(prefix="/api/recruits", tags=["모임"])


def _login_member_id(request: Request) -> int:
    """로그인 세션의 회원 ID를 반환함. 없으면 401. (add_recruit와 같은 방식)"""
    member_id = request.session.get("member_id")

    if member_id is None:
        raise HTTPException(
            status_code=401,
            detail="로그인이 필요합니다.",
        )

    return int(member_id)


def _optional_member_id(request: Request) -> int | None:
    """로그인했으면 회원 ID, 아니면 None. 로그인 없이도 열리는 조회 API에서 사용함."""
    member_id = request.session.get("member_id")
    return None if member_id is None else int(member_id)


def get_dispatch_service(
    request: Request,
    program_service: ProgramService = Depends(build_program_service),
    x_dev_member_id: int | None = Header(default=None),
):
    """기존 동작을 유지하고 신규 요청에만 검증된 공통 인증을 적용하도록 의존성을 구성한다."""

    def verified():
        return get_current_member_id(request, x_dev_member_id)

    def optional_verified():
        if request.session.get("member_id") is None and x_dev_member_id is None:
            return None
        return verified()

    return RecruitDispatchService(
        program_service,
        programs_enabled(),
        verified,
        optional_verified,
        lambda: _login_member_id(request),
        lambda: _optional_member_id(request),
    )


# 1. 모임 상세 조회
# GET /api/recruits/{recruit_id}
@router.get("/{recruit_id}")
def get_recruit(recruit_id: int, dispatch=Depends(get_dispatch_service)):
    """기존 모임과 신규 프로그램을 구분해 공개 상세/본인 상태를 반환한다."""
    return invoke(dispatch.detail, recruit_id)


# 2. 모임 생성
# POST /api/recruits
@router.post("", status_code=201)
def add_recruit(
    data: RecruitCreation = Body(...), dispatch=Depends(get_dispatch_service)
):
    """기존 생성 계약과 신규 일정/신청서 계약을 구분해 검증 후 생성한다."""
    return invoke(dispatch.create, data)


# 3. 모임 목록 조회
# GET /api/recruits
@router.get("")
def get_recruits(category: str | None = None, dispatch=Depends(get_dispatch_service)):
    """기존 배열/순서를 유지하면서 신규 행의 일정·권한·신청 상태를 확장한다."""
    return invoke(dispatch.list, category)


# 4. 모임 정보 수정
# PATCH /api/recruits/{recruit_id}
@router.patch("/{recruit_id}")
def update_recruit(recruit_id: int, data: dict, dispatch=Depends(get_dispatch_service)):
    """저장된 모임의 계약에 맞춰 부분 수정 필드와 권한을 검증한다."""
    return invoke(dispatch.update, recruit_id, data)


# 5. 모임 삭제
# DELETE /api/recruits/{recruit_id}
@router.delete("/{recruit_id}")
def delete_recruit(recruit_id: int, dispatch=Depends(get_dispatch_service)):
    """기존 논리 삭제와 신규 모임 초안 삭제를 구분한다. 단체 취소로 재사용하지 않는다."""
    return invoke(dispatch.delete, recruit_id)


# 6. 모임 참여 신청
# POST /api/recruits/{recruit_id}/join
@router.post("/{recruit_id}/join")
def join_recruit(
    recruit_id: int, data: dict | None = None, dispatch=Depends(get_dispatch_service)
):
    """기존 본문 없는 참여와 신규 신청서 접수를 구분한다."""
    return invoke(dispatch.apply, recruit_id, data)


# 7. 모임 참여 취소
# DELETE /api/recruits/{recruit_id}/join
@router.delete("/{recruit_id}/join")
def cancel_join(recruit_id: int, dispatch=Depends(get_dispatch_service)):
    """신규 신청은 로그인 회원의 취소/이탈 규칙으로, 기존 신청은 기존 경로로 처리한다."""
    return invoke(dispatch.cancel_application, recruit_id)


# 8. 모임 참여자 목록 조회
# GET /api/recruits/{recruit_id}/members
@router.get("/{recruit_id}/members")
def get_recruit_members(recruit_id: int, dispatch=Depends(get_dispatch_service)):
    """확정 참여자만 반환하고 신규 대기/커리어 자료를 공개하지 않는다."""
    return invoke(dispatch.members, recruit_id)


# 9. 모임 인원 현황 조회
# GET /api/recruits/{recruit_id}/count
@router.get("/{recruit_id}/count")
def get_recruit_count(recruit_id: int, dispatch=Depends(get_dispatch_service)):
    """기존 인원 응답을 유지하고 신규 모임은 확정/대기 인원을 구분한다."""
    return invoke(dispatch.count, recruit_id)


@router.put("/{recruit_id}/like")
def like_recruit(recruit_id: int, request: Request, db: Session = Depends(get_db)):
    """모임 좋아요. 이미 좋아요했으면 상태만 반환함."""
    return reaction_service.like_recruit(db, recruit_id, _login_member_id(request))


@router.delete("/{recruit_id}/like")
def unlike_recruit(recruit_id: int, request: Request, db: Session = Depends(get_db)):
    """모임 좋아요 취소. 좋아요가 없어도 성공함."""
    return reaction_service.unlike_recruit(db, recruit_id, _login_member_id(request))


@router.put("/{recruit_id}/scrap")
def scrap_recruit(recruit_id: int, request: Request, db: Session = Depends(get_db)):
    """모임 스크랩. 이미 스크랩했으면 상태만 반환함."""
    return reaction_service.scrap_recruit(db, recruit_id, _login_member_id(request))


@router.delete("/{recruit_id}/scrap")
def unscrap_recruit(recruit_id: int, request: Request, db: Session = Depends(get_db)):
    """모임 스크랩 취소. 스크랩이 없어도 성공함."""
    return reaction_service.unscrap_recruit(db, recruit_id, _login_member_id(request))


@router.get("/{recruit_id}/comments")
def get_comments(recruit_id: int, request: Request, db: Session = Depends(get_db)):
    """모임 댓글 목록 (부모 → 대댓글 순서)."""
    return comment_service.get_comments(db, recruit_id, _optional_member_id(request))


@router.post("/{recruit_id}/comments", status_code=201)
def create_comment(
    recruit_id: int,
    data: RecruitCommentCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """모임 댓글·대댓글 작성. parent_comment_id가 있으면 대댓글임."""
    return comment_service.create_comment(
        db, recruit_id, _login_member_id(request), data
    )


@router.patch("/{recruit_id}/comments/{comment_id}")
def update_comment(
    recruit_id: int,
    comment_id: int,
    data: RecruitCommentUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """모임 댓글 수정 (작성자만)."""
    return comment_service.update_comment(
        db, recruit_id, comment_id, _login_member_id(request), data
    )


@router.delete("/{recruit_id}/comments/{comment_id}")
def delete_comment(
    recruit_id: int,
    comment_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """모임 댓글 논리삭제 (작성자만). 대댓글은 남음."""
    return comment_service.delete_comment(
        db, recruit_id, comment_id, _login_member_id(request)
    )
