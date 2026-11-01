"""신규 계약 검증용 라우터. 기존 모임 라우터를 덮어쓰거나 자동 등록하지 않는다."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from backend.app.core.auth import get_current_member_id
from backend.app.core.database import get_db
from backend.app.core.recruit_config import programs_enabled
from backend.app.domain.recruit_program import PolicyError
from backend.app.repositories.recruit_program_repository import ProgramRepository
from backend.app.schemas.recruit_program import (
    ActivityCreate,
    CurriculumUpdate,
    DecisionRequest,
    ExtensionRequest,
    ProgramApplication,
    ProgramCreate,
    ProgramEdit,
    ReasonRequest,
)
from backend.app.services.recruit_program_service import ProgramService

router = APIRouter(prefix="/api/recruits", tags=["recruit-programs"])
features_router = APIRouter(prefix="/api/recruits", tags=["recruit-programs"])


def build_program_service(db=Depends(get_db)):
    """실제 DB 세션으로 서비스를 구성한다. 기술 사전 어댑터는 별도 연결 지점이다."""
    return ProgramService(ProgramRepository(db))


def get_service(service: ProgramService = Depends(build_program_service)):
    """실제 공통 기술 사전 어댑터 연결 전 프로젝트 생성은 명시적 503을 반환한다."""
    if not programs_enabled():
        raise HTTPException(
            503, "신규 모임 API를 활성화하지 않았습니다. 배포 설정을 확인해주세요."
        )
    if not service.repository.schema_available():
        raise HTTPException(503, "신규 모임 마이그레이션을 먼저 적용해주세요.")
    return service


def invoke(method, *args):
    """업무 오류만 기존 HTTP detail 문자열 계약으로 변환한다."""
    try:
        return method(*args)
    except PolicyError as error:
        raise HTTPException(error.status, detail=str(error)) from error
    except ValidationError as error:
        errors = [{**item, "loc": ("body", *item["loc"])} for item in error.errors()]
        raise RequestValidationError(errors) from error


@router.get("")
def list_programs(
    category: str | None = None,
    member_id=Depends(get_current_member_id),
    service=Depends(get_service),
):
    """프로젝트·스터디 목록과 본인의 신청/버튼 상태를 조회한다."""
    return invoke(service.list, member_id, category)


@router.post("", status_code=201)
def create(
    data: ProgramCreate,
    member_id=Depends(get_current_member_id),
    service=Depends(get_service),
):
    """로그인한 개설자의 모임과 자동 참여 정책을 적용해 생성한다."""
    return invoke(service.create, member_id, data)


@router.get("/{recruit_id}")
def detail(
    recruit_id: int,
    member_id=Depends(get_current_member_id),
    service=Depends(get_service),
):
    """해당 모임 상세를 조회하며 타인의 신청 자료는 반환하지 않는다."""
    return invoke(service.detail, recruit_id, member_id)


@router.patch("/{recruit_id}")
def edit(
    recruit_id: int,
    data: ProgramEdit,
    member_id=Depends(get_current_member_id),
    service=Depends(get_service),
):
    """개설자가 보낸 필드만 수정하고 핵심 조건 잠금을 검사한다."""
    return invoke(service.edit, recruit_id, member_id, data)


@router.get("/{recruit_id}/members")
def members(
    recruit_id: int,
    member_id=Depends(get_current_member_id),
    service=Depends(get_service),
):
    """대기자를 제외한 확정 참여자와 팀장 표시를 조회한다."""
    return invoke(service.members, recruit_id, member_id)


@router.get("/{recruit_id}/count")
def count(
    recruit_id: int,
    member_id=Depends(get_current_member_id),
    service=Depends(get_service),
):
    """확정 인원·대기 인원·남은 자리를 구분해 반환한다."""
    return invoke(service.count, recruit_id, member_id)


@router.post("/{recruit_id}/join")
def apply(
    recruit_id: int,
    data: ProgramApplication | None = None,
    member_id=Depends(get_current_member_id),
    service=Depends(get_service),
):
    """프로젝트 신청서 또는 본문 없는 스터디 신청을 확정/대기로 접수한다."""
    return invoke(service.apply, recruit_id, member_id, data or ProgramApplication())


@router.delete("/{recruit_id}/join")
def cancel_application(
    recruit_id: int,
    member_id=Depends(get_current_member_id),
    service=Depends(get_service),
):
    """본인의 신청 취소 또는 진행 중 이탈을 처리한다."""
    return invoke(service.cancel_application, recruit_id, member_id)


@features_router.post("/{recruit_id}/extension")
@router.post("/{recruit_id}/extension")
def extend(
    recruit_id: int,
    data: ExtensionRequest,
    member_id=Depends(get_current_member_id),
    service=Depends(get_service),
):
    """선정 팀장이 일정 버전과 중복 방지 키를 보내 최대 2회 연장한다."""
    return invoke(service.decide, recruit_id, member_id, "extend", data)


@features_router.post("/{recruit_id}/exception-start")
@router.post("/{recruit_id}/exception-start")
def exception_start(
    recruit_id: int,
    data: DecisionRequest,
    member_id=Depends(get_current_member_id),
    service=Depends(get_service),
):
    """최종 연장 후 최소 2명인 프로젝트의 예정일 예외 시작을 선택한다."""
    return invoke(service.decide, recruit_id, member_id, "exception-start", data)


@features_router.post("/{recruit_id}/cancel")
@router.post("/{recruit_id}/cancel")
def cancel(
    recruit_id: int,
    data: ReasonRequest,
    member_id=Depends(get_current_member_id),
    service=Depends(get_service),
):
    """팀장의 시작 전 모임 취소 사유와 상태를 보존한다."""
    return invoke(service.decide, recruit_id, member_id, "cancel", data)


@features_router.post("/{recruit_id}/abort")
@router.post("/{recruit_id}/abort")
def abort(
    recruit_id: int,
    data: ReasonRequest,
    member_id=Depends(get_current_member_id),
    service=Depends(get_service),
):
    """프로젝트에 홀로 남은 참여자가 중도 종료를 선택한다."""
    return invoke(service.decide, recruit_id, member_id, "abort", data)


@features_router.get("/{recruit_id}/curriculum")
@router.get("/{recruit_id}/curriculum")
def curriculum(
    recruit_id: int,
    member_id=Depends(get_current_member_id),
    service=Depends(get_service),
):
    """스터디 커리큘럼의 현재 버전과 주차별 초안을 조회한다."""
    return invoke(service.curriculum, recruit_id, member_id)


@features_router.put("/{recruit_id}/curriculum")
@router.put("/{recruit_id}/curriculum")
def update_curriculum(
    recruit_id: int,
    data: CurriculumUpdate,
    member_id=Depends(get_current_member_id),
    service=Depends(get_service),
):
    """편집 정책과 개설자 권한을 확인해 커리큘럼을 다음 버전으로 저장한다."""
    return invoke(service.curriculum, recruit_id, member_id, data)


@features_router.get("/{recruit_id}/activities")
@router.get("/{recruit_id}/activities")
def activities(
    recruit_id: int,
    member_id=Depends(get_current_member_id),
    service=Depends(get_service),
):
    """모임의 주간 인증·결과물·후기 기록을 조회한다."""
    return invoke(service.activities, recruit_id, member_id)


@features_router.post("/{recruit_id}/activities", status_code=201)
@router.post("/{recruit_id}/activities", status_code=201)
def add_activity(
    recruit_id: int,
    data: ActivityCreate,
    member_id=Depends(get_current_member_id),
    service=Depends(get_service),
):
    """활동 기록을 저장한다. 저장 자체로 개인 완료나 XP를 확정하지 않는다."""
    return invoke(service.activities, recruit_id, member_id, data)


# === PLAYMATE 모임 개인 XP 승인 / 회수 (기존 API 변경 없음) ===
from backend.app.schemas.meetup_xp import MeetupXPApprove, MeetupXPRevoke
from backend.app.services.meetup_xp_service import MeetupXPService

@features_router.post('/{recruit_id}/xp/approve', tags=['모임 XP'])
def approve_meetup_xp(
    recruit_id: int,
    data: MeetupXPApprove,
    reviewer_id: int = Depends(get_current_member_id),
    service: ProgramService = Depends(get_service),
):
    return invoke(
        MeetupXPService(service).approve,
        reviewer_id, recruit_id, data.activity_id, data.member_id,
        data.reward_type, data.week,
    )


@features_router.post('/{recruit_id}/xp/revoke', tags=['모임 XP'])
def revoke_meetup_xp(
    recruit_id: int,
    data: MeetupXPRevoke,
    reviewer_id: int = Depends(get_current_member_id),
    service: ProgramService = Depends(get_service),
):
    return invoke(
        MeetupXPService(service).revoke,
        reviewer_id, recruit_id, data.member_id, data.reward_type,
        data.reason, data.week,
    )
