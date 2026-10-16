"""모임 참여·취소·인원 조회와 모집 정원에 관한 비즈니스 로직."""

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.app.models.recruit import RecruitMember
from backend.app.repositories import recruit as recruit_repo

import time

def ensure_capacity_not_below_joined(
    db: Session,
    recruit_id: int,
    new_capacity: int,
) -> None:
    """변경할 모집 정원이 현재 참여 인원보다 작은지 검사함.

    호출 측은 먼저 get_recruit_for_update()로 모임 행을 잠가야 함.
    다른 참여 요청과 정원 변경의 순서를 보장하기 위함임.
    """
    joined_count = recruit_repo.count_joined_members(db, recruit_id)
    if new_capacity < joined_count:
        raise HTTPException(
            status_code=400,
            detail="모집 인원을 현재 참여 인원보다 적게 설정할 수 없습니다.",
        )


def join_recruit(
    db: Session,
    recruit_id: int,
    member_id: int = -1,
) -> dict[str, str]:
    """모임 행 잠금 후 정원을 확인하고 회원 참여를 저장함.

    모든 참여 요청이 같은 Recruit 행에 대한 FOR UPDATE 잠금을 먼저 얻음.
    따라서 동시에 요청하더라도 최신 참여 인원을 확인한 후 등록함.

    member_id의 -1 기본값은 기존 Router와의 임시 호환용임.
    Discord 회원 인증 연결 시 이 인자를 필수값으로 바꿔야 함.
    """
    try:
        # 이 트랜잭션이 끝날 때까지 같은 모임의 다른 참여 요청은 기다림.
        recruit = recruit_repo.get_recruit_for_update(db, recruit_id)
        if recruit is None or recruit.state != "OPEN":
            raise HTTPException(400, "참여할 수 없는 모임입니다.")

        post = recruit_repo.get_post(db, recruit.post_id)
        if post is None or post.post_status == "DELETED":
            raise HTTPException(400, "삭제된 모임입니다.")

        member = recruit_repo.find_member(db, recruit_id, member_id)
        if member is not None and member.status == "JOINED":
            raise HTTPException(400, "이미 참여한 모임입니다.")

        joined_count = recruit_repo.count_joined_members(db, recruit_id)
        if joined_count >= recruit.capacity:
            raise HTTPException(400, "모집 인원이 가득 찼습니다.")

        if member is not None:
            # 이전에 참여를 취소했던 회원은 기존 기록을 재사용함.
            member.status = "JOINED"
            member.canceled_at = None
            member.joined_at = datetime.now()
        else:
            new_member = RecruitMember(
                recruit_id=recruit_id,
                member_id=member_id,
                role="MEMBER",
                status="JOINED",
                joined_at=datetime.now(),
            )
            recruit_repo.add_member(db, new_member)

        db.commit()
        return {"message": "모임 참여 완료"}

    except Exception:
        # 오류가 나도 잠금·변경사항이 남지 않도록 트랜잭션 종료.
        db.rollback()
        raise


def cancel_join(db: Session, recruit_id: int):
    """참여 중인 회원의 상태를 CANCELED로 바꾸고 취소 시간을 기록함.

    TODO: 임시 회원 ID -1을 실제 로그인 ID로 바꾸는 것은 후속 단계에서 처리함.
    """
    member_id = -1
    member = recruit_repo.find_member(db, recruit_id, member_id)
    if member is None or member.status != "JOINED":
        raise HTTPException(status_code=400, detail="참여 중인 모임이 아닙니다.")

    member.status = "CANCELED"
    member.canceled_at = datetime.now()
    db.commit()
    return {"message": "모임 참여 취소 완료"}


def get_recruit_members(db: Session, recruit_id: int):
    """존재하는 모임의 참여자만 조회하고 기존 응답 필드를 반환함."""
    if recruit_repo.get_recruit(db, recruit_id) is None:
        raise HTTPException(status_code=404, detail="모임이 없습니다.")

    members = recruit_repo.list_joined_members(db, recruit_id)
    return [
        {
            "member_id": member.member_id,
            "role": member.role,
            "joined_at": member.joined_at,
        }
        for member in members
    ]


def get_recruit_count(db: Session, recruit_id: int):
    """모임 참여 인원과 남은 자리를 조회함."""

    start = time.perf_counter()

    result = recruit_repo.get_recruit_capacity_and_count(
        db, recruit_id
    )

    elapsed = (time.perf_counter() - start) * 1000
    print(f"[성능 측정] DB 조회: {elapsed:.2f}ms", flush=True)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="모임이 없습니다.",
        )

    count = result.current_members
    capacity = result.capacity

    return {
        "recruit_id": recruit_id,
        "current_members": count,
        "capacity": capacity,
        "remaining": max(0, capacity - count),
    }