# 모임의 생성, 조회, 수정, 삭제 및 참여 관리 API를 연결하는 Router
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


# 1. 모임 상세 조회
# GET /api/recruits/{recruit_id}
@router.get("/{recruit_id}")
def get_recruit(recruit_id: int, request: Request, db: Session = Depends(get_db)):
    """모임 상세 조회. 로그인했으면 좋아요·스크랩 여부도 계산함."""
    # recruit_id : 조회할 모임 고유 번호 (URL 경로에서 전달)
    # Depends(get_db) : 요청에서 사용할 DB 세션을 주입받음
    return recruit_service.get_recruit(db, recruit_id, _optional_member_id(request))


# 2. 모임 생성
# POST /api/recruits
@router.post("", status_code=201)
def add_recruit(
    request: Request,
    data: RecruitCreate,
    db: Session = Depends(get_db),
):
    """로그인한 회원의 ID를 확인한 뒤 새 모임을 생성함."""
    # Request : 클라이언트의 요청 및 로그인 세션 정보를 가져오는 객체
    # RecruitCreate : 모임 생성 시 전달받는 요청 데이터의 형식을 정의함
    # 세션에서 현재 로그인한 회원의 member_id를 가져옴
    member_id = request.session.get("member_id")

    # 로그인한 회원 정보가 없으면 모임 생성을 허용하지 않음
    # HTTP 401 : 인증이 필요함을 의미함
    if member_id is None:
        raise HTTPException(
            status_code=401,
            detail="로그인이 필요합니다.",
        )

    # DB 세션, 모임 입력 정보, 회원 ID를 Service에 전달함
    # 실제 모임 생성 및 저장 규칙은 Service에서 처리함
    return recruit_service.create_recruit(
        db=db,
        data=data,
        member_id=int(member_id),
    )


# 3. 모임 목록 조회
# GET /api/recruits
@router.get("")
def get_recruits(db: Session = Depends(get_db)):
    """등록된 모임 목록을 조회함."""
    # 목록 조회에 필요한 DB 작업은 recruit_service에서 수행함
    return recruit_service.get_recruits(db)


# 4. 모임 정보 수정
# PATCH /api/recruits/{recruit_id}
@router.patch("/{recruit_id}")
def update_recruit(
    recruit_id: int,
    data: RecruitUpdate,
    db: Session = Depends(get_db),
):
    """모임 ID에 해당하는 모임 정보를 수정함."""
    # RecruitUpdate : 수정할 모임 정보의 요청 데이터 형식을 정의함
    # 수정 가능 여부 및 실제 수정 처리는 recruit_service에 위임함
    return recruit_service.update_recruit(db, recruit_id, data)


# 5. 모임 삭제
# DELETE /api/recruits/{recruit_id}
@router.delete("/{recruit_id}")
def delete_recruit(recruit_id: int, db: Session = Depends(get_db)):
    """모임을 논리 삭제함."""
    # 논리 삭제 : DB 행을 물리적으로 지우는 대신 삭제 상태로 관리하는 방식
    # 구체적인 삭제 처리는 recruit_service에서 수행함
    return recruit_service.delete_recruit(db, recruit_id)


# 6. 모임 참여 신청
# POST /api/recruits/{recruit_id}/join
@router.post("/{recruit_id}/join")
def join_recruit(recruit_id: int, db: Session = Depends(get_db)):
    """모임 참여를 요청함. 회원 인증 연결은 후속 작업임."""
    # 참여 인원, 중복 참여 등 실제 처리 규칙은 member_service에서 판단함
    # 현재 Router는 로그인 회원 ID를 Service에 전달하지 않음
    return member_service.join_recruit(db, recruit_id)


# 7. 모임 참여 취소
# DELETE /api/recruits/{recruit_id}/join
@router.delete("/{recruit_id}/join")
def cancel_join(recruit_id: int, db: Session = Depends(get_db)):
    """모임 참여를 취소함."""
    # 모임 참여 기록의 취소 처리를 member_service에 위임함
    # 현재 Router는 로그인 회원 ID를 Service에 전달하지 않음
    return member_service.cancel_join(db, recruit_id)


# 8. 모임 참여자 목록 조회
# GET /api/recruits/{recruit_id}/members
@router.get("/{recruit_id}/members")
def get_recruit_members(recruit_id: int, db: Session = Depends(get_db)):
    """특정 모임에 속한 참여자 목록을 조회함."""
    # recruit_id로 모임을 지정하여 참여자 목록을 조회함
    return member_service.get_recruit_members(db, recruit_id)


# 9. 모임 인원 현황 조회
# GET /api/recruits/{recruit_id}/count
@router.get("/{recruit_id}/count")
def get_recruit_count(recruit_id: int, db: Session = Depends(get_db)):
    """현재 참여 인원 및 잔여 모집 인원을 조회함."""
    # 모임의 정원과 현재 참여 인원을 바탕으로 인원 현황을 조회함
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
