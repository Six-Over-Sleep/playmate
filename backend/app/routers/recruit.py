"""모임 API 주소와 요청·응답을 연결하는 Router."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.schemas.recruit import RecruitCreate, RecruitUpdate
from backend.app.services import recruit as recruit_service
from backend.app.services import recruit_member as member_service


router = APIRouter(prefix="/api/recruits", tags=["모임"])


@router.get("/{recruit_id}") 
def get_recruit(recruit_id: int, db: Session = Depends(get_db)):
    """모임 상세 조회."""
    return recruit_service.get_recruit(db, recruit_id)


@router.post("", status_code=201)
def add_recruit(data: RecruitCreate, db: Session = Depends(get_db)):
    """모임 생성."""
    return recruit_service.create_recruit(db, data)


@router.get("")
def get_recruits(db: Session = Depends(get_db)):
    """모임 목록 조회."""
    return recruit_service.get_recruits(db)


@router.patch("/{recruit_id}")
def update_recruit(
    recruit_id: int,
    data: RecruitUpdate,
    db: Session = Depends(get_db),
):
    """모임 정보 수정."""
    return recruit_service.update_recruit(db, recruit_id, data)


@router.delete("/{recruit_id}")
def delete_recruit(recruit_id: int, db: Session = Depends(get_db)):
    """모임 논리 삭제."""
    return recruit_service.delete_recruit(db, recruit_id)


@router.post("/{recruit_id}/join")
def join_recruit(recruit_id: int, db: Session = Depends(get_db)):
    """모임 참여 (회원 인증 연결은 후속 작업)."""
    return member_service.join_recruit(db, recruit_id)


@router.delete("/{recruit_id}/join")
def cancel_join(recruit_id: int, db: Session = Depends(get_db)):
    """모임 참여 취소."""
    return member_service.cancel_join(db, recruit_id)


@router.get("/{recruit_id}/members")
def get_recruit_members(recruit_id: int, db: Session = Depends(get_db)):
    """참여자 목록 조회."""
    return member_service.get_recruit_members(db, recruit_id)


@router.get("/{recruit_id}/count")
def get_recruit_count(recruit_id: int, db: Session = Depends(get_db)):
    """현재 인원 및 잔여 인원 조회."""
    return member_service.get_recruit_count(db, recruit_id)
