# 모임 모집, 참여자, 운동·게임·스터디·공동구매 상세 정보를 관리하는 모델
from sqlalchemy import Column, BigInteger, Integer, String, DateTime, Boolean, Numeric, ForeignKey
from backend.app.core.database import Base

class Recruit(Base):
    __tablename__ = "recruits"

    recruit_id = Column(BigInteger, primary_key=True)
    post_id = Column(BigInteger, ForeignKey("posts.post_id"), unique=True, nullable=False)
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


class RecruitMember(Base):
    __tablename__ = "recruit_members"

    recruit_id = Column(BigInteger, ForeignKey("recruits.recruit_id"), primary_key=True)
    member_id = Column(BigInteger, ForeignKey("members.member_id"), primary_key=True)
    role = Column(String)
    status = Column(String)
    joined_at = Column(DateTime)
    canceled_at = Column(DateTime)
    updated_at = Column(DateTime)


class RecruitSportsDetail(Base):
    __tablename__ = "recruit_sports_details"

    recruit_id = Column(BigInteger, ForeignKey("recruits.recruit_id"), primary_key=True)
    sport_name = Column(String)


class RecruitGameDetail(Base):
    __tablename__ = "recruit_game_details"

    recruit_id = Column(BigInteger, ForeignKey("recruits.recruit_id"), primary_key=True)
    game_name = Column(String)


class RecruitStudyDetail(Base):
    __tablename__ = "recruit_study_details"

    recruit_id = Column(BigInteger, ForeignKey("recruits.recruit_id"), primary_key=True)
    study_topic = Column(String)
    study_period = Column(String)
    study_method = Column(String)


class RecruitGroupBuyDetail(Base):
    __tablename__ = "recruit_group_buy_details"

    recruit_id = Column(BigInteger, ForeignKey("recruits.recruit_id"), primary_key=True)
    product_name = Column(String)
    purchase_url = Column(String)
    estimated_price_per_person = Column(Numeric)
    pickup_method = Column(String)
