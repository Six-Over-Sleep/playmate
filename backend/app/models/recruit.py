"""모임의 공통 정보, 참여자, 카테고리별 상세 정보를 정의하는 ORM 모델."""

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Time,
)

from backend.app.core.database import Base


class Recruit(Base):
    """모임의 모집 조건과 일정을 저장하는 테이블."""

    __tablename__ = "recruits"

    # 하나의 게시글(post_id)에는 하나의 모임만 연결할 수 있음.
    recruit_id = Column(BigInteger, primary_key=True)
    post_id = Column(
        BigInteger, ForeignKey("posts.post_id"), unique=True, nullable=False
    )

    # 모임 유형, 카테고리, 모집 인원 및 일정 정보
    recruit_mode = Column(String, nullable=False)
    category = Column(String, nullable=False)
    capacity = Column(Integer, nullable=False)
    meeting_datetime = Column(DateTime)
    place = Column(String)
    is_online = Column(Boolean)
    contact_method = Column(String)
    deadline_at = Column(DateTime)
    state = Column(String, nullable=False)
    close_reason = Column(String)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    # 정기 모임의 요일 목록은 PostgreSQL 배열로 저장함.
    regular_days = Column(ARRAY(String))
    regular_time = Column(Time)
    regular_start_date = Column(Date)
    meeting_start = Column(DateTime)
    meeting_end = Column(DateTime)


class RecruitMember(Base):
    """모임에 참여한 회원과 참여 상태를 관리하는 테이블."""

    __tablename__ = "recruit_members"

    # 두 컬럼을 합쳐 기본키로 사용하므로 같은 회원의 중복 참여 기록을 만들지 않음.
    recruit_id = Column(BigInteger, ForeignKey("recruits.recruit_id"), primary_key=True)
    member_id = Column(BigInteger, ForeignKey("members.member_id"), primary_key=True)

    role = Column(String)
    status = Column(String)
    joined_at = Column(DateTime)
    canceled_at = Column(DateTime)
    updated_at = Column(DateTime)


class RecruitSportsDetail(Base):
    """운동 모임에만 필요한 정보를 저장하는 테이블."""

    __tablename__ = "recruit_sports_details"

    # 상세 정보는 모임 ID를 기본키 겸 외래키로 사용해 1:1로 연결함.
    recruit_id = Column(BigInteger, ForeignKey("recruits.recruit_id"), primary_key=True)
    sport_name = Column(String)


class RecruitGameDetail(Base):
    """게임 모임에만 필요한 정보를 저장하는 테이블."""

    __tablename__ = "recruit_game_details"

    recruit_id = Column(BigInteger, ForeignKey("recruits.recruit_id"), primary_key=True)
    game_name = Column(String)


class RecruitStudyDetail(Base):
    """스터디 모임에만 필요한 정보를 저장하는 테이블."""

    __tablename__ = "recruit_study_details"

    recruit_id = Column(BigInteger, ForeignKey("recruits.recruit_id"), primary_key=True)
    study_topic = Column(String)
    study_period = Column(String)
    study_method = Column(String)


class RecruitGroupBuyDetail(Base):
    """공동구매 모임에만 필요한 정보를 저장하는 테이블."""

    __tablename__ = "recruit_group_buy_details"

    recruit_id = Column(BigInteger, ForeignKey("recruits.recruit_id"), primary_key=True)
    product_name = Column(String)
    purchase_url = Column(String)
    estimated_price_per_person = Column(Numeric)
    pickup_method = Column(String)
