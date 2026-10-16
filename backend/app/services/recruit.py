"""모임 생성·조회·수정·삭제에 관한 비즈니스 로직."""

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.app.models.post import Post
from backend.app.models.recruit import (
    Recruit,
    RecruitGameDetail,
    RecruitGroupBuyDetail,
    RecruitSportsDetail,
    RecruitStudyDetail,
)
from backend.app.repositories import recruit as recruit_repo
from backend.app.schemas.recruit import RecruitCreate, RecruitUpdate
from backend.app.services.recruit_member import ensure_capacity_not_below_joined


# 카테고리별 상세 정보 모델. 응답을 구성할 때 사용함.
DETAIL_MODELS = {
    "sports": RecruitSportsDetail,
    "game": RecruitGameDetail,
    "study": RecruitStudyDetail,
    "group_buy": RecruitGroupBuyDetail,
}


def _get_detail_model_and_values(data: RecruitCreate):
    """모임 카테고리에 맞는 상세 테이블 모델과 저장할 값을 반환함."""
    if data.category == "sports":
        return RecruitSportsDetail, {
            "sport_name": data.sport_name,
        }

    if data.category == "game":
        return RecruitGameDetail, {
            "game_name": data.game_name,
        }

    if data.category == "study":
        return RecruitStudyDetail, {
            "study_topic": data.study_topic,
            "study_period": data.study_period,
            "study_method": data.study_method,
        }

    if data.category == "group_buy":
        return RecruitGroupBuyDetail, {
            "product_name": data.product_name,
            "purchase_url": data.purchase_url,
            "estimated_price_per_person": data.estimated_price_per_person,
            "pickup_method": data.pickup_method,
        }

    raise ValueError("지원하지 않는 모임 카테고리입니다.")


def create_recruit(
    db: Session,
    data: RecruitCreate,
    member_id: int = -1,
) -> dict[str, int]:
    """모임 게시글, 모집 정보, 카테고리 상세를 하나의 트랜잭션으로 생성함.

    Args:
        db: 요청에서 전달된 SQLAlchemy DB 세션.
        data: schemas/recruit.py에서 검증한 모임 생성 요청 데이터.
        member_id: 게시글 작성자 ID. 현재 Router는 이 인자를 전달하지 않으므로
            기존 임시값(-1)을 유지하며, 인증 연결 후 실제 회원 ID를 전달해야 함.

    Returns:
        생성된 모임 ID와 게시글 ID를 담은 딕셔너리.

    Raises:
        ValueError: 지원하지 않는 모임 카테고리를 받은 경우.
        Exception: DB 저장 중 오류가 나면 rollback 후 원래 예외를 전달함.
    """
    try:
        # 카테고리를 먼저 검사해 잘못된 요청은 DB에 쓰기 전에 차단함.
        detail_model, detail_values = _get_detail_model_and_values(data)

        post = Post(
            author_member_id=member_id,
            title=data.title,
            body=data.body,
            post_type="RECRUIT",
        )
        recruit_repo.add_post(db, post)  # post_id를 확보함.

        recruit = Recruit(
            post_id=post.post_id,
            recruit_mode=data.recruit_mode,
            category=data.category,
            capacity=data.capacity,
            regular_days=data.regular_days,
            regular_time=data.regular_time,
            regular_start_date=data.regular_start_date,
            meeting_start=data.meeting_start,
            meeting_end=data.meeting_end,
            place=data.place,
            is_online=data.is_online,
            contact_method=data.contact_method,
            deadline_at=data.deadline_at,
            state="OPEN",
        )
        recruit_repo.add_recruit(db, recruit)  # recruit_id를 확보함.

        detail = detail_model(
            recruit_id=recruit.recruit_id,
            **detail_values,
        )
        recruit_repo.add_category_detail(db, detail)

        # commit 후 ORM 객체가 만료되더라도 응답에 추가 SELECT가 발생하지 않게 함.
        result = {
            "recruit_id": recruit.recruit_id,
            "post_id": post.post_id,
        }

        # 세 테이블의 변경을 한꺼번에 확정함.
        db.commit()
        return result

    except Exception:
        # 어느 단계에서 오류가 발생해도 세 테이블 변경이 함께 취소됨.
        db.rollback()
        raise


def get_recruit(db: Session, recruit_id: int):
    """게시글·모임·카테고리 상세를 조회한 후 기존 응답 형태로 구성함."""
    result = recruit_repo.find_recruit_with_post(db, recruit_id)
    if result is None:
        raise HTTPException(status_code=404, detail="모임이 없습니다.")

    post, recruit = result
    detail_model = DETAIL_MODELS.get(recruit.category)
    if detail_model is None:
        raise HTTPException(
            status_code=400,
            detail="지원하지 않는 모임 카테고리입니다.",
        )

    detail = recruit_repo.get_category_detail(db, detail_model, recruit_id)

    return {
        "recruit_id": recruit.recruit_id,
        "title": post.title,
        "body": post.body,
        "category": recruit.category,
        "capacity": recruit.capacity,
        "state": recruit.state,
        "recruit_mode": recruit.recruit_mode,
        "deadline_at": recruit.deadline_at,
        "regular_days": recruit.regular_days,
        "regular_time": recruit.regular_time,
        "meeting_start": recruit.meeting_start,
        "regular_start_date": recruit.regular_start_date,
        "meeting_end": recruit.meeting_end,
        "place": recruit.place,
        "is_online": recruit.is_online,
        "contact_method": recruit.contact_method,
        "detail": _serialize_category_detail(detail),
    }


def _serialize_category_detail(detail):
    """카테고리 모델의 컬럼을 사전으로 변환하고 연결용 recruit_id는 제외함."""
    if detail is None:
        return {}

    return {
        column.name: getattr(detail, column.name)
        for column in detail.__table__.columns
        if column.name != "recruit_id"
    }


def get_recruits(db: Session):
    """삭제되지 않은 모임을 읽고 목록 화면용 필드를 반환함."""
    results = recruit_repo.list_recruits_with_posts(db)

    return [
        {
            "recruit_id": recruit.recruit_id,
            "title": post.title,
            "body": post.body,
            "category": recruit.category,
            "capacity": recruit.capacity,
            "state": recruit.state,
            "view_count": post.view_count,
            "recruit_mode": recruit.recruit_mode,
            "deadline_at": recruit.deadline_at,
            "regular_days": recruit.regular_days,
            "regular_time": recruit.regular_time,
            "regular_start_date": recruit.regular_start_date,
            "meeting_start": recruit.meeting_start,
            "meeting_end": recruit.meeting_end,
        }
        for post, recruit in results
    ]


def update_recruit(db: Session, recruit_id: int, data: RecruitUpdate):
    """기존 값과 수정 값을 합쳐 검증한 뒤 게시글·모임을 함께 저장함.

    입력: 모임 ID, 부분 수정 스키마. 출력: 기존 성공 메시지.
    모임이 없으면 404, 일정 또는 모집 인원이 잘못되면 400을 반환함.
    """
    changes = data.model_dump(exclude_unset=True)

    # 정원 변경은 참여 처리와 동일한 모임 행 잠금을 사용함.
    # 다른 필드만 수정하는 요청에는 기존 조회를 그대로 사용함.
    if "capacity" in changes:
        recruit = recruit_repo.get_recruit_for_update(db, recruit_id)
    else:
        recruit = recruit_repo.get_recruit(db, recruit_id)

    if recruit is None:
        raise HTTPException(status_code=404, detail="모임이 없습니다.")

    post = recruit_repo.get_post(db, recruit.post_id)
    if post is None or post.post_status == "DELETED":
        raise HTTPException(status_code=404, detail="모임이 없습니다.")

    updated_values = {
        "recruit_mode": recruit.recruit_mode,
        "regular_days": recruit.regular_days,
        "regular_time": recruit.regular_time,
        "regular_start_date": recruit.regular_start_date,
        "meeting_start": recruit.meeting_start,
        "meeting_end": recruit.meeting_end,
        "deadline_at": recruit.deadline_at,
        "capacity": recruit.capacity,
    }
    updated_values.update(changes)
    _validate_recruit_update(updated_values)

    if "capacity" in changes:
        # 락이 유지되는 동안 현재 인원과 새 정원을 비교함.
        ensure_capacity_not_below_joined(db, recruit_id, updated_values["capacity"])

    for field_name, value in changes.items():
        if field_name in ("title", "body"):
            setattr(post, field_name, value)
        else:
            setattr(recruit, field_name, value)

    # 일정 유형이 바뀌면 사용하지 않는 방식의 이전 일정 정보를 비움.
    if recruit.recruit_mode == "regular":
        recruit.meeting_start = None
        recruit.meeting_end = None
    elif recruit.recruit_mode == "short":
        recruit.regular_days = None
        recruit.regular_time = None
        recruit.regular_start_date = None

    # 기존에는 short 분기 안에 있어서 regular 수정이 저장되지 않았음.
    db.commit()
    return {"message": "모임 수정 완료"}


def _validate_recruit_update(values: dict):
    """기존 수정 API의 모집 인원·정기 일정 규칙을 검증함.

    단기 모임의 상세 일정 검증과 작성자 권한은 후속 Service 단계에서 정리함.
    """
    if values["capacity"] is None or values["capacity"] <= 0:
        raise HTTPException(status_code=400, detail="모집 인원은 1명 이상이어야 합니다.")

    if values["deadline_at"] is None:
        raise HTTPException(status_code=400, detail="모집 마감일은 필수입니다.")

    if values["recruit_mode"] == "regular":
        if not values["regular_days"] or values["regular_time"] is None:
            raise HTTPException(
                status_code=400,
                detail="정기 모임은 요일과 시간이 필요합니다.",
            )

        if values["regular_start_date"] is None:
            raise HTTPException(status_code=400, detail="정기 모임 시작 날짜가 필요합니다.")

        weekdays = ["월", "화", "수", "목", "금", "토", "일"]
        start_day = weekdays[values["regular_start_date"].weekday()]
        if start_day not in values["regular_days"]:
            raise HTTPException(
                status_code=400,
                detail="시작 날짜의 요일이 모임 요일에 포함되어야 합니다.",
            )

        first_meeting = datetime.combine(
            values["regular_start_date"],
            values["regular_time"],
        )
        if values["deadline_at"] > first_meeting:
            raise HTTPException(
                status_code=400,
                detail="모집 마감은 첫 모임 시작 이전이어야 합니다.",
            )


def delete_recruit(db: Session, recruit_id: int):
    """모임이 존재하면 Post는 삭제 상태로, Recruit는 종료 상태로 저장함."""
    result = recruit_repo.find_recruit_with_post(db, recruit_id)
    if result is None:
        raise HTTPException(status_code=404, detail="모임이 없습니다.")

    post, recruit = result
    post.post_status = "DELETED"
    post.deleted_at = datetime.now()
    recruit.state = "CLOSED"

    db.commit()
    return {"message": "모임 삭제 완료"}
