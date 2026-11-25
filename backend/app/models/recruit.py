
# 모임 모집 정보, 참여 회원 및 카테고리별 상세 정보를 관리하는 모델
from sqlalchemy import (
    ARRAY, BigInteger, Boolean, Column, Date, DateTime,
    ForeignKey, Integer, String, Text, Time, JSON
)
from sqlalchemy.dialects.postgresql import JSONB
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
    recruit_mode = Column(String(20), nullable=False)
    category = Column(String(20), nullable=False)
    capacity = Column(Integer, nullable=False)
    # 042: 운동·게임·스터디·공동구매의 1:1 상세 자료를 JSONB 한 컬럼에 저장한다.
    # 내용이 없는 모임은 NULL, 상세 행이 있으면 dict(모든 필드가 NULL이어도 dict).
    # 하위 키 변경은 직접 수행하지 않고 매번 새 dict를 할당해 ORM 변경을 추적한다.
    details = Column(
        JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql"),
        nullable=True,
    )

    # meeting_datetime : 모임 진행 예정 일시
    # place : 모임 진행 장소
    # is_online : 온라인 모임 여부 (True : 온라인 / False : 오프라인)
    # contact_method : 모임 참여자 간 연락 방법
    meeting_datetime = Column(DateTime)
    place = Column(String(255))
    is_online = Column(Boolean)
    contact_method = Column(String(255))

    # deadline_at : 모임 모집 마감 일시
    # state : 모임 모집 상태 (OPEN, CLOSE 등)
    # close_reason : 모임 모집 종료 사유
    deadline_at = Column(DateTime)
    state = Column(String(20), nullable=False)
    close_reason = Column(String(30))

    # created_at : 모임 최초 생성 시간
    # updated_at : 모임 정보 마지막 수정 시간
    created_at = Column(DateTime)
    updated_at = Column(DateTime)

    # regular_days : 정기 모임 진행 요일 목록 (PostgreSQL 배열)
    # regular_time : 정기 모임 진행 시간
    # regular_start_date : 정기 모임 시작 날짜
    regular_days = Column(ARRAY(Text))
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
    role = Column(String(20))
    status = Column(String(20))

    # joined_at : 모임 참여 시간
    # canceled_at : 모임 참여 취소 시간
    # updated_at : 참여 정보 마지막 수정 시간
    joined_at = Column(DateTime)
    canceled_at = Column(DateTime)
    updated_at = Column(DateTime)
