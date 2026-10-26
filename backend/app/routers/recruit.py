# 모임의 생성, 조회, 수정, 삭제 및 참여 관리 API를 연결하는 Router

from fastapi import APIRouter, Body, Depends, Header, Request, HTTPException
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.auth import get_current_member_id
from backend.app.core.recruit_config import programs_enabled

from backend.app.schemas.recruit_dispatch import RecruitCreation
from backend.app.schemas.recruit import (
    RecruitCommentCreate,
    RecruitCommentUpdate,
)

from backend.app.services.recruit_dispatch_service import RecruitDispatchService
from backend.app.services.recruit_program_service import ProgramService

from backend.app.routers.recruit_program import (
    build_program_service,
    invoke,
)

from backend.app.services import recruit_comment as comment_service
from backend.app.services import recruit_reaction as reaction_service


# =========================================================
# Router 설정
# =========================================================

# prefix : 모든 API 주소 앞에 공통으로 붙는 경로
# tags : API 문서(Swagger UI)에서 표시할 그룹 이름
router = APIRouter(
    prefix="/api/recruits",
    tags=["모임"],
)


# =========================================================
# 로그인 회원 ID
# =========================================================

def _login_member_id(request: Request) -> int:
    """
    로그인 세션의 회원 ID를 반환함.
    로그인하지 않은 경우 401.
    """

    member_id = request.session.get("member_id")

    if member_id is None:
        raise HTTPException(
            status_code=401,
            detail="로그인이 필요합니다.",
        )

    return int(member_id)


def _optional_member_id(
    request: Request,
) -> int | None:
    """
    로그인한 경우 회원 ID를 반환하고,
    비로그인 사용자는 None을 반환함.

    로그인 없이도 사용할 수 있는 조회 API에서 사용함.
    """

    member_id = request.session.get("member_id")

    return (
        None
        if member_id is None
        else int(member_id)
    )


# =========================================================
# Recruit Dispatch Service
# =========================================================

def get_dispatch_service(
    request: Request,
    program_service: ProgramService = Depends(
        build_program_service
    ),
    x_dev_member_id: int | None = Header(
        default=None
    ),
):
    """
    기존 모임과 신규 프로젝트·스터디를 구분해 처리하는
    RecruitDispatchService 의존성을 구성함.

    신규 요청은 공통 인증을 사용하고,
    기존 모임도 실제 로그인 회원 ID를 전달함.
    """

    def verified():
        return get_current_member_id(
            request,
            x_dev_member_id,
        )

    def optional_verified():

        if (
            request.session.get("member_id") is None
            and x_dev_member_id is None
        ):
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


# =========================================================
# 1. 모임 상세 조회
# GET /api/recruits/{recruit_id}
# =========================================================

@router.get("/{recruit_id}")
def get_recruit(
    recruit_id: int,
    dispatch=Depends(get_dispatch_service),
):
    """
    기존 모임과 신규 프로그램을 구분해
    공개 상세 정보와 현재 로그인 회원 상태를 반환함.
    """

    return invoke(
        dispatch.detail,
        recruit_id,
    )


# =========================================================
# 2. 모임 생성
# POST /api/recruits
# =========================================================

@router.post(
    "",
    status_code=201,
)
def add_recruit(
    data: RecruitCreation = Body(...),
    dispatch=Depends(get_dispatch_service),
):
    """
    기존 모임 생성 계약과
    신규 프로젝트·스터디의 일정/신청서 계약을 구분해 생성함.
    """

    return invoke(
        dispatch.create,
        data,
    )


# =========================================================
# 3. 모임 목록 조회
# GET /api/recruits
# =========================================================

@router.get("")
def get_recruits(
    category: str | None = None,
    dispatch=Depends(get_dispatch_service),
):
    """
    기존 배열/정렬 구조를 유지하면서
    신규 프로그램의 일정·권한·신청 상태를 함께 반환함.
    """

    return invoke(
        dispatch.list,
        category,
    )


# =========================================================
# 4. 모임 정보 수정
# PATCH /api/recruits/{recruit_id}
# =========================================================

@router.patch("/{recruit_id}")
def update_recruit(
    recruit_id: int,
    data: dict,
    dispatch=Depends(get_dispatch_service),
):
    """
    저장된 모임 종류에 따라
    수정 가능 필드와 권한을 검증한 뒤 수정함.
    """

    return invoke(
        dispatch.update,
        recruit_id,
        data,
    )


# =========================================================
# 5. 모임 삭제
# DELETE /api/recruits/{recruit_id}
# =========================================================

@router.delete("/{recruit_id}")
def delete_recruit(
    recruit_id: int,
    dispatch=Depends(get_dispatch_service),
):
    """
    기존 모임의 논리 삭제와
    신규 모임의 초안 삭제를 구분함.

    프로젝트 운영 취소 API로 재사용하지 않음.
    """

    return invoke(
        dispatch.delete,
        recruit_id,
    )


# =========================================================
# 6. 모임 참여 신청
# POST /api/recruits/{recruit_id}/join
# =========================================================

@router.post("/{recruit_id}/join")
def join_recruit(
    recruit_id: int,
    data: dict | None = None,
    dispatch=Depends(get_dispatch_service),
):
    """
    기존 모임의 본문 없는 참여 요청과
    신규 프로젝트·스터디 신청서 접수를 구분함.

    로그인 회원 ID는 Dispatch 내부에서
    실제 인증 정보를 통해 전달됨.
    """

    return invoke(
        dispatch.apply,
        recruit_id,
        data,
    )


# =========================================================
# 7. 모임 참여 취소 / 중도 이탈
# DELETE /api/recruits/{recruit_id}/join
# =========================================================

@router.delete("/{recruit_id}/join")
def cancel_join(
    recruit_id: int,
    dispatch=Depends(get_dispatch_service),
):
    """
    신규 프로그램은 신청 취소/중도 이탈 규칙을 적용하고,
    기존 모임은 기존 참여 취소 로직으로 처리함.

    실제 로그인 회원의 참여 기록만 처리함.
    """

    return invoke(
        dispatch.cancel_application,
        recruit_id,
    )


# =========================================================
# 8. 모임 참여자 목록 조회
# GET /api/recruits/{recruit_id}/members
# =========================================================

@router.get("/{recruit_id}/members")
def get_recruit_members(
    recruit_id: int,
    dispatch=Depends(get_dispatch_service),
):
    """
    확정 참여자 목록을 반환함.

    신규 프로젝트·스터디의 WAITING 신청자는
    확정 참여자 목록에 포함하지 않음.
    """

    return invoke(
        dispatch.members,
        recruit_id,
    )


# =========================================================
# 9. 모임 인원 현황 조회
# GET /api/recruits/{recruit_id}/count
# =========================================================

@router.get("/{recruit_id}/count")
def get_recruit_count(
    recruit_id: int,
    dispatch=Depends(get_dispatch_service),
):
    """
    기존 인원 응답을 유지하며
    신규 프로그램은 확정/대기 인원을 구분함.
    """

    return invoke(
        dispatch.count,
        recruit_id,
    )


# =========================================================
# 좋아요
# =========================================================

@router.put("/{recruit_id}/like")
def like_recruit(
    recruit_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    모임 좋아요.

    이미 좋아요한 경우 현재 상태만 반환함.
    """

    return reaction_service.like_recruit(
        db,
        recruit_id,
        _login_member_id(request),
    )


@router.delete("/{recruit_id}/like")
def unlike_recruit(
    recruit_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    모임 좋아요 취소.

    좋아요 기록이 없어도 성공 처리함.
    """

    return reaction_service.unlike_recruit(
        db,
        recruit_id,
        _login_member_id(request),
    )


# =========================================================
# 스크랩
# =========================================================

@router.put("/{recruit_id}/scrap")
def scrap_recruit(
    recruit_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    모임 스크랩.

    이미 스크랩한 경우 현재 상태만 반환함.
    """

    return reaction_service.scrap_recruit(
        db,
        recruit_id,
        _login_member_id(request),
    )


@router.delete("/{recruit_id}/scrap")
def unscrap_recruit(
    recruit_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    모임 스크랩 취소.

    스크랩 기록이 없어도 성공 처리함.
    """

    return reaction_service.unscrap_recruit(
        db,
        recruit_id,
        _login_member_id(request),
    )


# =========================================================
# 댓글 조회
# =========================================================

@router.get("/{recruit_id}/comments")
def get_comments(
    recruit_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    모임 댓글 목록 조회.

    부모 댓글 → 대댓글 순서로 반환함.
    """

    return comment_service.get_comments(
        db,
        recruit_id,
        _optional_member_id(request),
    )


# =========================================================
# 댓글 / 대댓글 작성
# =========================================================

@router.post(
    "/{recruit_id}/comments",
    status_code=201,
)
def create_comment(
    recruit_id: int,
    data: RecruitCommentCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    모임 댓글 또는 대댓글 작성.

    parent_comment_id가 존재하면 대댓글로 처리함.
    """

    return comment_service.create_comment(
        db,
        recruit_id,
        _login_member_id(request),
        data,
    )


# =========================================================
# 댓글 수정
# =========================================================

@router.patch(
    "/{recruit_id}/comments/{comment_id}"
)
def update_comment(
    recruit_id: int,
    comment_id: int,
    data: RecruitCommentUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    모임 댓글 수정.

    작성자 본인만 수정 가능함.
    """

    return comment_service.update_comment(
        db,
        recruit_id,
        comment_id,
        _login_member_id(request),
        data,
    )


# =========================================================
# 댓글 삭제
# =========================================================

@router.delete(
    "/{recruit_id}/comments/{comment_id}"
)
def delete_comment(
    recruit_id: int,
    comment_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    모임 댓글 논리 삭제.

    작성자 본인만 삭제 가능하며,
    부모 댓글이 삭제돼도 대댓글은 유지됨.
    """

    return comment_service.delete_comment(
        db,
        recruit_id,
        comment_id,
        _login_member_id(request),
    )