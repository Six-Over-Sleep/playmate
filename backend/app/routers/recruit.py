"""모임 API 주소와 요청·응답을 연결하는 Router."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from fastapi import Request, HTTPException
from backend.app.core.database import get_db
from backend.app.schemas.recruit import (
    RecruitCommentCreate,
    RecruitCommentUpdate,
    RecruitCreate,
    RecruitUpdate,
)
from backend.app.services import recruit as recruit_service
from backend.app.services import recruit_comment as comment_service
from backend.app.services import recruit_member as member_service
from backend.app.services import recruit_reaction as reaction_service


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


@router.get("/{recruit_id}")
def get_recruit(recruit_id: int, request: Request, db: Session = Depends(get_db)):
    """모임 상세 조회. 로그인했으면 좋아요·스크랩 여부도 계산함."""
    return recruit_service.get_recruit(db, recruit_id, _optional_member_id(request))


@router.post("", status_code=201)
def add_recruit(
    request: Request,
    data: RecruitCreate,
    db: Session = Depends(get_db),
):
    member_id = request.session.get("member_id")

    if member_id is None:
        raise HTTPException(
            status_code=401,
            detail="로그인이 필요합니다.",
        )

    return recruit_service.create_recruit(
        db=db,
        data=data,
        member_id=int(member_id),
    )


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
