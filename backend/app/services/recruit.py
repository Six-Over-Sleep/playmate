"""모임 생성·조회·수정·삭제에 관한 비즈니스 로직.

Router에서 요청을 전달받아 처리 순서와 검증 규칙을 결정함.
실제 DB 조회·등록은 Repository에 위임하고, 여기서 commit/rollback을 수행함.
"""

# 생성·삭제 시각을 기록하고 정기 모임의 날짜와 시간을 결합할 때 사용함.
from datetime import datetime

# HTTPException : API 요청을 처리할 수 없을 때 HTTP 오류를 반환함.
from fastapi import HTTPException
# Session : SQLAlchemy DB 연결과 트랜잭션을 관리하는 객체임.
from sqlalchemy.orm import Session

# Post : 모임에 연결되는 게시글 모델
from backend.app.models.post import Post
# Recruit / RecruitMember : 모임 기본 정보 / 참여자 정보 모델
# Recruit*Detail : 운동·게임·스터디·공동구매별 상세 정보 모델
from backend.app.models.recruit import (
    Recruit,
    RecruitGameDetail,
    RecruitMember,
    RecruitGroupBuyDetail,
    RecruitSportsDetail,
    RecruitStudyDetail,
)
# recruit_repo : 모임 데이터의 조회와 DB 세션 등록을 담당함.
from backend.app.repositories import recruit as recruit_repo
# RecruitCreate / RecruitUpdate : 요청 데이터를 검증하는 Pydantic 스키마
from backend.app.schemas.recruit import RecruitCreate, RecruitUpdate
# 변경할 정원이 현재 참여 인원보다 적은지 검사하는 함수
from backend.app.services.recruit_member import ensure_capacity_not_below_joined


# 카테고리 이름을 실제 SQLAlchemy 상세 모델과 연결하는 딕셔너리임.
# 상세 조회 시 카테고리에 맞는 테이블을 선택하는 데 사용함.
DETAIL_MODELS = {
    "sports": RecruitSportsDetail,
    "game": RecruitGameDetail,
    "study": RecruitStudyDetail,
    "group_buy": RecruitGroupBuyDetail,
}


def _get_detail_model_and_values(data: RecruitCreate):
    """모임 카테고리에 맞는 상세 테이블 모델과 저장할 값을 반환함."""
    # 카테고리별로 저장해야 하는 컬럼이 달라 각각 별도로 매핑함.
    # 운동 모임 : 운동 종목 정보를 사용함.
    if data.category == "sports":
        return RecruitSportsDetail, {
            "sport_name": data.sport_name,
        }

    # 게임 모임 : 게임 이름을 사용함.
    if data.category == "game":
        return RecruitGameDetail, {
            "game_name": data.game_name,
        }

    # 스터디 모임 : 주제·기간·진행 방식을 사용함.
    if data.category == "study":
        return RecruitStudyDetail, {
            "study_topic": data.study_topic,
            "study_period": data.study_period,
            "study_method": data.study_method,
        }

    # 공동구매 모임 : 상품·구매 주소·예상 가격·수령 방법을 사용함.
    if data.category == "group_buy":
        return RecruitGroupBuyDetail, {
            "product_name": data.product_name,
            "purchase_url": data.purchase_url,
            "estimated_price_per_person": data.estimated_price_per_person,
            "pickup_method": data.pickup_method,
        }

    # 허용하지 않은 카테고리는 저장하지 않고 오류 처리함.
    raise ValueError("지원하지 않는 모임 카테고리입니다.")


def create_recruit(
    db: Session,
    data: RecruitCreate,
    member_id: int,
) -> dict[str, int]:
    """모임 게시글, 모집 정보, 카테고리 상세를 하나의 트랜잭션으로 생성함.

    Args:
        db: 요청에서 전달된 SQLAlchemy DB 세션.
        data: schemas/recruit.py에서 검증한 모임 생성 요청 데이터.
        member_id: 로그인한 모임 생성자의 회원 ID. Router에서 세션을 통해 전달받음.

    Returns:
        생성된 모임 ID와 게시글 ID를 담은 딕셔너리.

    Raises:
        ValueError: 지원하지 않는 모임 카테고리를 받은 경우.
        Exception: DB 저장 중 오류가 나면 rollback 후 원래 예외를 전달함.
    """
    try:
        # 카테고리를 먼저 검사해 잘못된 요청은 DB에 쓰기 전에 차단함.
        detail_model, detail_values = _get_detail_model_and_values(data)

        # 1단계 : 모임과 연결할 게시글 객체를 먼저 생성함.
        # post_type="RECRUIT"로 일반 게시판 글과 모임 모집 글을 구분함.
        post = Post(
            author_member_id=member_id,
            title=data.title,
            body=data.body,
            post_type="RECRUIT",
        )
        # add_post() 내부의 flush()로 post_id를 확보함. commit은 아직 수행하지 않음.
        recruit_repo.add_post(db, post)  # post_id를 확보함.

        # 2단계 : 생성된 post_id를 사용하여 모임 모집 정보를 연결함.
        # state="OPEN"은 새 모임이 모집 중임을 나타냄.
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
        # add_recruit() 내부의 flush()로 상세 테이블에서 사용할 recruit_id를 확보함.
        recruit_repo.add_recruit(db, recruit)  # recruit_id를 확보함.

        # 3단계 : 카테고리에 맞는 상세 테이블 객체를 생성함.
        # **detail_values는 딕셔너리 값을 해당 모델의 키워드 인자로 펼치는 문법임.
        detail = detail_model(
            recruit_id=recruit.recruit_id,
            **detail_values,
        )
        # 상세 정보도 동일한 DB 세션에 등록해 함께 저장되도록 함.
        recruit_repo.add_category_detail(db, detail)

        # 4단계 : 모임 생성자를 참여자 테이블에 HOST(모임장)로 자동 등록함.
        # status="JOINED"이므로 현재 참여 인원 집계에도 포함됨.
        host = RecruitMember(
            recruit_id=recruit.recruit_id,
            member_id=member_id,
            role="HOST",
            status="JOINED",
            joined_at=datetime.now(),
        )

        # recruit_members 테이블에 모임장 참여 기록을 등록함.
        recruit_repo.add_member(db, host)

        # commit 후 ORM 객체가 만료되더라도 응답에 추가 SELECT가 발생하지 않게 함.
        result = {
            "recruit_id": recruit.recruit_id,
            "post_id": post.post_id,
        }

        # 게시글·모임·상세 정보·참여자 기록을 하나의 트랜잭션으로 확정함.
        db.commit()
        return result

    except Exception:
        # 어느 단계에서 오류가 발생해도 미확정된 모든 DB 변경을 함께 취소함.
        db.rollback()
        raise


def get_recruit_post(db: Session, recruit_id: int) -> Post:
    """삭제되지 않은 모임의 게시글을 반환함. 없거나 삭제되었으면 404.

    좋아요·스크랩·댓글 테이블은 모임 ID가 아니라 게시글 ID(post_id)를 사용하므로
    모임 ID를 게시글로 바꿀 때 사용함.
    """
    result = recruit_repo.find_recruit_with_post(db, recruit_id)
    if result is None:
        raise HTTPException(status_code=404, detail="모임이 없습니다.")
    post, _ = result
    return post


def get_recruit(db: Session, recruit_id: int, member_id: int | None = None):
    """게시글·모임·카테고리 상세를 조회한 후 기존 응답 형태로 구성함.

    member_id는 로그인한 경우에만 전달되며, 좋아요·스크랩 여부 계산에 사용함.
    로그인하지 않았으면 두 값 모두 False임.
    """
    # 삭제되지 않은 게시글과 모임 정보를 JOIN하여 함께 조회함.
    result = recruit_repo.find_recruit_with_post(db, recruit_id)
    if result is None:
        raise HTTPException(status_code=404, detail="모임이 없습니다.")

    # 반환된 (게시글, 모임) 결과를 각각의 변수로 분리함.
    post, recruit = result
    # 저장된 카테고리에 맞는 상세 모델을 선택함.
    detail_model = DETAIL_MODELS.get(recruit.category)
    if detail_model is None:
        raise HTTPException(
            status_code=400,
            detail="지원하지 않는 모임 카테고리입니다.",
        )

    # 운동·게임·스터디·공동구매 중 해당 상세 정보를 조회함.
    detail = recruit_repo.get_category_detail(db, detail_model, recruit_id)

    # 게시글 정보 + 모임 정보 + 카테고리 상세 정보를 한 응답으로 합침.
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
        "like_count": recruit_repo.count_post_likes(db, post.post_id),
        "liked_by_me": member_id is not None
        and recruit_repo.has_post_like(db, post.post_id, member_id),
        "scrapped_by_me": member_id is not None
        and recruit_repo.has_post_scrap(db, post.post_id, member_id),
    }


def _serialize_category_detail(detail):
    """카테고리 모델의 컬럼을 사전으로 변환하고 연결용 recruit_id는 제외함."""
    # 카테고리 상세 정보가 등록되어 있지 않으면 빈 딕셔너리를 반환함.
    if detail is None:
        return {}

    # __table__.columns : ORM 모델에 정의된 DB 컬럼 목록
    # getattr() : 각 컬럼 이름에 해당하는 실제 객체 값 조회
    # recruit_id는 연결용 키이므로 API 응답의 상세 필드에서 제외함.
    return {
        column.name: getattr(detail, column.name)
        for column in detail.__table__.columns
        if column.name != "recruit_id"
    }


def get_recruits(db: Session):
    """삭제되지 않은 모임을 읽고 목록 화면용 필드를 반환함."""
    # Repository에서 모임 게시글과 JOINED 참여 인원 집계 결과를 함께 조회함.
    results = recruit_repo.list_recruits_with_posts(db)

    # SQLAlchemy 조회 결과를 프론트엔드에서 사용하기 쉬운 딕셔너리 목록으로 변환함.
    return [
        {
            "recruit_id": recruit.recruit_id,
            "title": post.title,
            "body": post.body,
            "category": recruit.category,
            "capacity": recruit.capacity,
            # 정원과 비교할 수 있도록 현재 참여 인원을 정수로 전달함.
            "participant_count": int(participant_count),
            "state": recruit.state,
            "view_count": post.view_count,
            "recruit_mode": recruit.recruit_mode,
            "deadline_at": recruit.deadline_at,
            "regular_days": recruit.regular_days,
            "regular_time": recruit.regular_time,
            "regular_start_date": recruit.regular_start_date,
            "meeting_start": recruit.meeting_start,
            "meeting_end": recruit.meeting_end,
            "like_count": int(like_count),
        }
        for post, recruit, participant_count, like_count in results
    ]


def update_recruit(db: Session, recruit_id: int, data: RecruitUpdate):
    """기존 값과 수정 값을 합쳐 검증한 뒤 게시글·모임을 함께 저장함.

    입력: 모임 ID, 부분 수정 스키마. 출력: 기존 성공 메시지.
    모임이 없으면 404, 일정 또는 모집 인원이 잘못되면 400을 반환함.
    """
    # model_dump(exclude_unset=True) : 요청에서 실제 전달한 필드만 추출함.
    # 전달하지 않은 기존 필드는 그대로 유지하여 부분 수정(PATCH)을 구현함.
    changes = data.model_dump(exclude_unset=True)

    # 정원 변경은 참여 처리와 동일한 모임 행 잠금을 사용함.
    # 다른 필드만 수정하는 요청에는 기존 조회를 그대로 사용함.
    if "capacity" in changes:
        # FOR UPDATE 행 잠금으로 다른 참여 요청과 정원 변경이 겹치지 않도록 함.
        recruit = recruit_repo.get_recruit_for_update(db, recruit_id)
    else:
        # 정원 변경이 없는 요청은 일반 조회를 사용함.
        recruit = recruit_repo.get_recruit(db, recruit_id)

    if recruit is None:
        raise HTTPException(status_code=404, detail="모임이 없습니다.")

    # 연결된 게시글이 삭제되어 있으면 모임 수정도 허용하지 않음.
    post = recruit_repo.get_post(db, recruit.post_id)
    if post is None or post.post_status == "DELETED":
        raise HTTPException(status_code=404, detail="모임이 없습니다.")

    # DB에 저장된 기존 일정·정원 정보를 먼저 딕셔너리에 담음.
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
    # 요청에서 받은 값으로 기존 값을 덮어쓴 뒤 최종 데이터가 유효한지 검사함.
    updated_values.update(changes)
    # 모집 인원·모집 마감일·정기 모임 일정에 대한 업무 규칙 확인
    _validate_recruit_update(updated_values)

    if "capacity" in changes:
        # 락이 유지되는 동안 현재 인원과 새 정원을 비교함.
        ensure_capacity_not_below_joined(db, recruit_id, updated_values["capacity"])

    # 변경 대상이 제목/본문이면 Post에, 그 외에는 Recruit에 반영함.
    # setattr(객체, 필드명, 값) : 지정한 객체 속성을 동적으로 수정함.
    for field_name, value in changes.items():
        if field_name in ("title", "body"):
            setattr(post, field_name, value)
        else:
            setattr(recruit, field_name, value)

    # 일정 유형이 바뀌면 사용하지 않는 방식의 이전 일정 정보를 비움.
    # 정기 모임은 단기 시작·종료 일시를, 단기 모임은 정기 요일·시간·시작 날짜를 제거함.
    if recruit.recruit_mode == "regular":
        recruit.meeting_start = None
        recruit.meeting_end = None
    elif recruit.recruit_mode == "short":
        recruit.regular_days = None
        recruit.regular_time = None
        recruit.regular_start_date = None

    # 수정한 Post와 Recruit 객체의 변경 내용을 DB에 확정함.
    db.commit()
    return {"message": "모임 수정 완료"}


def _validate_recruit_update(values: dict):
    """기존 수정 API의 모집 인원·정기 일정 규칙을 검증함.

    단기 모임의 상세 일정 검증과 작성자 권한은 후속 Service 단계에서 정리함.
    """
    # 모집 인원이 없거나 0명 이하이면 저장을 허용하지 않음.
    if values["capacity"] is None or values["capacity"] <= 0:
        raise HTTPException(status_code=400, detail="모집 인원은 1명 이상이어야 합니다.")

    # 모집 마감일은 필수로 지정해야 함.
    if values["deadline_at"] is None:
        raise HTTPException(status_code=400, detail="모집 마감일은 필수입니다.")

    # 정기 모임인 경우 요일·시간·시작 날짜와 모집 마감 시점을 검사함.
    if values["recruit_mode"] == "regular":
        if not values["regular_days"] or values["regular_time"] is None:
            raise HTTPException(
                status_code=400,
                detail="정기 모임은 요일과 시간이 필요합니다.",
            )

        if values["regular_start_date"] is None:
            raise HTTPException(status_code=400, detail="정기 모임 시작 날짜가 필요합니다.")

        # weekday() : 월요일=0, 일요일=6을 반환함.
        weekdays = ["월", "화", "수", "목", "금", "토", "일"]
        start_day = weekdays[values["regular_start_date"].weekday()]
        if start_day not in values["regular_days"]:
            raise HTTPException(
                status_code=400,
                detail="시작 날짜의 요일이 모임 요일에 포함되어야 합니다.",
            )

        # datetime.combine() : 시작 날짜와 정기 모임 시간을 하나의 일시로 결합함.
        first_meeting = datetime.combine(
            values["regular_start_date"],
            values["regular_time"],
        )
        # 첫 모임 시작 시각보다 모집 마감일이 늦으면 오류를 반환함.
        if values["deadline_at"] > first_meeting:
            raise HTTPException(
                status_code=400,
                detail="모집 마감은 첫 모임 시작 이전이어야 합니다.",
            )


def delete_recruit(db: Session, recruit_id: int):
    """모임이 존재하면 Post는 삭제 상태로, Recruit는 종료 상태로 저장함."""
    # 삭제되지 않은 모임과 게시글을 조회하여 존재 여부를 확인함.
    result = recruit_repo.find_recruit_with_post(db, recruit_id)
    if result is None:
        raise HTTPException(status_code=404, detail="모임이 없습니다.")

    post, recruit = result
    # DB에서 행을 제거하지 않고 삭제 상태만 기록하는 논리 삭제(Soft Delete)임.
    post.post_status = "DELETED"
    post.deleted_at = datetime.now()
    # 모집 정보는 종료 상태로 바꿔 추가 모집을 막는 데 활용함.
    recruit.state = "CLOSED"

    # 게시글 삭제 상태와 모임 종료 상태를 함께 DB에 반영함.
    db.commit()
    return {"message": "모임 삭제 완료"}  
