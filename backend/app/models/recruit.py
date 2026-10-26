
# 모임 모집 정보, 참여 회원 및 카테고리별 상세 정보를 관리하는 모델
from sqlalchemy import (
    ARRAY, BigInteger, Boolean, Column, Date, DateTime,
    ForeignKey, Integer, Numeric, String, Time
)
from backend.app.core.database import Base


# 모임의 모집 조건, 일정 및 운영 상태를 관리하는 모델
class Recruit(Base):
    __tablename__ = "recruits"

    # recruit_id : 모임 고유 번호 (기본키)
    # post_id : 모임과 연결된 게시글 번호 (중복 연결 불가)
    recruit_id = Column(BigInteger, primary_key=True)
    post_id = Column(
        BigInteger, ForeignKey("posts.post_id"), unique=True, nullable=False
    )

    # recruit_mode : 모임 운영 유형 (일회성, 정기, 상시 등)
    # category : 모임 카테고리 (운동, 게임, 스터디, 공동구매)
    # capacity : 모임 최대 모집 인원
    recruit_mode = Column(String, nullable=False)
    category = Column(String, nullable=False)
    capacity = Column(Integer, nullable=False)

    # meeting_datetime : 모임 진행 예정 일시
    # place : 모임 진행 장소
    # is_online : 온라인 모임 여부 (True : 온라인 / False : 오프라인)
    # contact_method : 모임 참여자 간 연락 방법
    meeting_datetime = Column(DateTime)
    place = Column(String)
    is_online = Column(Boolean)
    contact_method = Column(String)

    # deadline_at : 모임 모집 마감 일시
    # state : 모임 모집 상태 (OPEN, CLOSE 등)
    # close_reason : 모임 모집 종료 사유
    deadline_at = Column(DateTime)
    state = Column(String, nullable=False)
    close_reason = Column(String)

    # created_at : 모임 최초 생성 시간
    # updated_at : 모임 정보 마지막 수정 시간
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    # regular_days : 정기 모임 진행 요일 목록 (PostgreSQL 배열)
    # regular_time : 정기 모임 진행 시간
    # regular_start_date : 정기 모임 시작 날짜
    regular_days = Column(ARRAY(String))
    regular_time = Column(Time)
    regular_start_date = Column(Date)

    # meeting_start : 모임 운영 시작 일시
    # meeting_end : 모임 운영 종료 일시
    meeting_start = Column(DateTime)
    meeting_end = Column(DateTime)


# 모임 참여 회원, 역할 및 참여 상태를 관리하는 모델
class RecruitMember(Base):
    __tablename__ = "recruit_members"

    # recruit_id : 참여한 모임 번호
    # member_id : 모임에 참여한 회원 번호
    # 두 컬럼을 묶어 복합 기본키(PK)로 사용
    recruit_id = Column(BigInteger, ForeignKey("recruits.recruit_id"), primary_key=True)
    member_id = Column(BigInteger, ForeignKey("members.member_id"), primary_key=True)

    # role : 모임 내 역할 (HOST : 모임장 / MEMBER : 일반 참여자)
    # status : 모임 참여 상태 (JOINED 등)
    role = Column(String)
    status = Column(String)

    # joined_at : 모임 참여 시간
    # canceled_at : 모임 참여 취소 시간
    # updated_at : 참여 정보 마지막 수정 시간
    joined_at = Column(DateTime)
    canceled_at = Column(DateTime)
    updated_at = Column(DateTime)


# 운동 모임의 상세 정보를 관리하는 모델
class RecruitSportsDetail(Base):
    __tablename__ = "recruit_sports_details"

    # recruit_id : 운동 모임 고유 번호 (기본키 + 외래키)
    # sport_name : 운동 종목 (러닝, 헬스, 축구 등)
    recruit_id = Column(BigInteger, ForeignKey("recruits.recruit_id"), primary_key=True)
    sport_name = Column(String)


# 게임 모임의 상세 정보를 관리하는 모델
class RecruitGameDetail(Base):
    __tablename__ = "recruit_game_details"

    # recruit_id : 게임 모임 고유 번호 (기본키 + 외래키)
    # game_name : 게임 이름 (LoL, 발로란트, 보드게임 등)
    recruit_id = Column(BigInteger, ForeignKey("recruits.recruit_id"), primary_key=True)
    game_name = Column(String)


# 스터디 모임의 상세 정보를 관리하는 모델
class RecruitStudyDetail(Base):
    __tablename__ = "recruit_study_details"

    # recruit_id : 스터디 모임 고유 번호 (기본키 + 외래키)
    # study_topic : 스터디 주제 (알고리즘, 자격증, 프로젝트 등)
    # study_period : 스터디 진행 기간
    # study_method : 스터디 진행 방식 (온라인, 오프라인 등)
    recruit_id = Column(BigInteger, ForeignKey("recruits.recruit_id"), primary_key=True)
    study_topic = Column(String)
    study_period = Column(String)
    study_method = Column(String)


# 공동구매 모임의 상세 정보를 관리하는 모델
class RecruitGroupBuyDetail(Base):
    __tablename__ = "recruit_group_buy_details"

    # recruit_id : 공동구매 모임 고유 번호 (기본키 + 외래키)
    # product_name : 공동구매 상품 이름
    # purchase_url : 상품 구매 페이지 주소
    recruit_id = Column(BigInteger, ForeignKey("recruits.recruit_id"), primary_key=True)
    product_name = Column(String)
    purchase_url = Column(String)

    # estimated_price_per_person : 1인당 예상 구매 금액
    # pickup_method : 상품 수령 방법 (직접 수령, 배송 등)
    estimated_price_per_person = Column(Numeric)
    pickup_method = Column(String)
