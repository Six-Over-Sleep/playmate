"""모임 참여·취소·인원 조회와 모집 정원에 관한 비즈니스 로직."""

from datetime import datetime, timedelta, timezone
import time

# HTTPException : 참여 불가, 권한 부족 등 API 오류를 전달함.
from fastapi import HTTPException

# Session : SQLAlchemy를 이용한 DB 조회 및 변경 작업에 사용함.
from sqlalchemy.orm import Session

# RecruitMember : 모임 참여 회원 정보를 저장하는 ORM 모델
from backend.app.models.recruit import RecruitMember

# recruit_repo : 모임·참여자 조회 및 등록을 담당하는 Repository
from backend.app.repositories import recruit as recruit_repo


KST = timezone(timedelta(hours=9))


def kst_now() -> datetime:
    """현재 한국 시각을 timezone 없는 datetime 값으로 반환함.

    deadline_at은 프론트의 datetime-local 입력값을 기준으로
    한국 시각을 timezone 없이 저장하고 있음.

    서버가 UTC 환경에서 실행되더라도 모집 마감 시각을
    동일한 한국 시각 기준으로 비교하기 위해 사용함.

    Discord Bot 역시 동일한 KST 기준으로 마감을 판단함.
    """
    return datetime.now(KST).replace(tzinfo=None)


# =========================================================
# 1. 모집 정원 변경 가능 여부 확인
# =========================================================
def ensure_capacity_not_below_joined(
    db: Session,
    recruit_id: int,
    new_capacity: int,
) -> None:
    """변경할 모집 정원이 현재 참여 인원보다 작은지 검사함.

    호출 측은 먼저 get_recruit_for_update()로 모임 행을 잠가야 함.
    다른 참여 요청과 정원 변경의 순서를 보장하기 위함임.
    """
    # JOINED 상태인 회원 수를 조회함.
    # HOST도 JOINED 상태라면 참여 인원에 포함됨.
    joined_count = recruit_repo.count_joined_members(db, recruit_id)

    # 이미 참여한 인원보다 모집 정원을 작게 변경할 수 없음.
    if new_capacity < joined_count:
        raise HTTPException(
            status_code=400,
            detail="모집 인원을 현재 참여 인원보다 적게 설정할 수 없습니다.",
        )


# =========================================================
# 2. 모임 참여
# =========================================================
def join_recruit(
    db: Session,
    recruit_id: int,
    member_id: int = -1,
) -> dict[str, str]:
    """모임 행을 잠근 뒤 참여 가능 여부를 확인하고 회원 참여를 저장함.

    모든 참여 요청은 동일한 Recruit 행에 대해 FOR UPDATE 잠금을 먼저 획득함.
    따라서 동시에 참여 요청이 들어오더라도 최신 참여 인원을 기준으로
    모집 정원 초과 여부를 확인할 수 있음.

    웹 API(Router)는 항상 로그인 세션의 실제 member_id를 전달함.
    기본값 -1은 테스트 호환용이며 실제 웹 참여 요청에서는 사용되지 않음.
    모임 생성 시 HOST로 등록된 회원은 일반 참여자로 다시 참여할 수 없음.
    """
    try:
        # 모임 행을 잠그고 조회함.
        # 이 트랜잭션이 끝날 때까지 동일 모임에 대한 다른 참여 요청은 대기함.
        recruit = recruit_repo.get_recruit_for_update(db, recruit_id)

        # 모임이 존재하지 않거나 모집 상태가 OPEN이 아니면 참여 불가
        if recruit is None or recruit.state != "OPEN":
            raise HTTPException(
                status_code=400,
                detail="참여할 수 없는 모임입니다.",
            )

        # 모집 마감 시각 이후에는 참여할 수 없음.
        # Discord Bot이 마감 시각 기준 최종 참여자를 바탕으로 채널을 생성하므로,
        # 마감 이후 참여를 허용하면 Discord 참여자와 DB 참여자가 달라질 수 있음.
        if (
            recruit.deadline_at is not None
            and recruit.deadline_at <= kst_now()
        ):
            raise HTTPException(
                status_code=400,
                detail="모집이 마감된 모임입니다.",
            )

        # 모임과 연결된 게시글이 존재하고 삭제되지 않았는지 확인함.
        post = recruit_repo.get_post(db, recruit.post_id)

        if post is None or post.post_status == "DELETED":
            raise HTTPException(
                status_code=400,
                detail="삭제된 모임입니다.",
            )

        # 해당 회원의 기존 참여 기록을 조회함.
        member = recruit_repo.find_member(
            db,
            recruit_id,
            member_id,
        )

        # 모임장은 생성 시 HOST로 이미 참여 중이므로 일반 참여를 허용하지 않음.
        if member is not None and member.role == "HOST":
            raise HTTPException(
                status_code=403,
                detail="모임장은 이미 참여 중입니다.",
            )

        # 이미 JOINED 상태라면 중복 참여를 막음.
        if member is not None and member.status == "JOINED":
            raise HTTPException(
                status_code=400,
                detail="이미 참여한 모임입니다.",
            )

        # 현재 참여 인원과 최대 모집 인원을 비교함.
        joined_count = recruit_repo.count_joined_members(
            db,
            recruit_id,
        )

        if joined_count >= recruit.capacity:
            raise HTTPException(
                status_code=400,
                detail="모집 인원이 가득 찼습니다.",
            )

        if member is not None:
            # 이전에 참여를 취소했던 회원은 기존 기록을 재사용함.
            member.status = "JOINED"
            member.canceled_at = None
            member.joined_at = datetime.now()

        else:
            # 처음 참여하는 회원은 MEMBER 역할로 새로운 참여 기록을 생성함.
            new_member = RecruitMember(
                recruit_id=recruit_id,
                member_id=member_id,
                role="MEMBER",
                status="JOINED",
                joined_at=datetime.now(),
            )

            # 신규 참여 객체를 현재 DB 세션에 등록함.
            recruit_repo.add_member(
                db,
                new_member,
            )

        # 검증 및 참여 정보 저장이 성공하면 DB에 변경사항을 확정함.
        db.commit()

        return {
            "message": "모임 참여 완료",
        }

    except Exception:
        # 오류 발생 시 잠금 및 DB 변경사항이 남지 않도록 롤백함.
        db.rollback()
        raise


# =========================================================
# 3. 모임 참여 취소
# =========================================================
def cancel_join(
    db: Session,
    recruit_id: int,
    member_id: int,
):
    """로그인 회원 본인의 모임 참여 취소 처리.

    일반 참여자(MEMBER)만 취소할 수 있음.
    모임장(HOST)은 참여를 취소할 수 없음.
    """
    # 해당 모임과 로그인 회원 ID로 본인 참여 기록만 조회함.
    member = recruit_repo.find_member(
        db,
        recruit_id,
        member_id,
    )

    # 회원 기록이 없거나 JOINED 상태가 아니면 취소할 수 없음.
    if member is None or member.status != "JOINED":
        raise HTTPException(
            status_code=400,
            detail="참여 중인 모임이 아닙니다.",
        )

    # HOST는 모임 운영자이므로 일반 참여 취소를 허용하지 않음.
    if member.role == "HOST":
        raise HTTPException(
            status_code=403,
            detail="모임장은 참여를 취소할 수 없습니다.",
        )

    # 참여 상태를 CANCELED로 바꾸고 취소 시간을 기록함.
    member.status = "CANCELED"
    member.canceled_at = datetime.now()

    # 참여 취소 내용을 DB에 최종 저장함.
    db.commit()

    return {
        "message": "모임 참여 취소 완료",
    }


# =========================================================
# 4. 모임 참여자 목록 조회
# =========================================================
def get_recruit_members(
    db: Session,
    recruit_id: int,
):
    """존재하는 모임의 참여자만 조회하고 기존 응답 필드를 반환함."""

    # 조회할 모임이 존재하지 않으면 404 오류를 발생시킴.
    if recruit_repo.get_recruit(db, recruit_id) is None:
        raise HTTPException(
            status_code=404,
            detail="모임이 없습니다.",
        )

    # 참여 상태가 JOINED인 회원 목록만 조회함.
    members = recruit_repo.list_joined_members(
        db,
        recruit_id,
    )

    # 회원별 ID, 역할, 참여 시간을 딕셔너리로 만들어 반환함.
    return [
        {
            "member_id": member.member_id,
            "role": member.role,
            "joined_at": member.joined_at,
        }
        for member in members
    ]


# =========================================================
# 5. 현재 참여 인원 및 잔여 인원 조회
# =========================================================
def get_recruit_count(
    db: Session,
    recruit_id: int,
):
    """모임 참여 인원과 남은 자리를 조회함."""

    # DB 조회 직전 시간을 기록해 성능을 측정함.
    start = time.perf_counter()

    # 모집 정원과 현재 JOINED 참여 인원을 한 번의 조회로 가져옴.
    result = recruit_repo.get_recruit_capacity_and_count(
        db,
        recruit_id,
    )

    # 조회 소요 시간을 밀리초(ms)로 계산하여 콘솔에 출력함.
    elapsed = (time.perf_counter() - start) * 1000

    print(
        f"[성능 측정] DB 조회: {elapsed:.2f}ms",
        flush=True,
    )

    # 조회 결과가 없으면 해당 모임이 없다는 오류를 반환함.
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="모임이 없습니다.",
        )

    # 현재 참여 인원 및 모집 정원을 조회 결과에서 꺼냄.
    count = result.current_members
    capacity = result.capacity

    # 남은 인원은 정원 - 현재 인원으로 계산함.
    # max(0, ...)은 잔여 인원이 음수로 표시되지 않도록 함.
    return {
        "recruit_id": recruit_id,
        "current_members": count,
        "capacity": capacity,
        "remaining": max(0, capacity - count),
    }