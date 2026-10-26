"""신규 모임 저장 모델. 기존 모임/회원 테이블과 외래키로 연결하며 DDL은 실행하지 않는다."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)

from backend.app.core.database import Base


class ProgramRecord(Base):
    __tablename__ = "recruit_programs"
    recruit_id = Column(BigInteger, ForeignKey("recruits.recruit_id"), primary_key=True)
    starts_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ends_at = Column(DateTime(timezone=True), nullable=False)
    schedule_version = Column(Integer, nullable=False)
    lifecycle_status = Column(String, nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    details = Column(JSON, nullable=False, default=dict)
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="program_period_valid"),
        CheckConstraint("schedule_version >= 1", name="program_version_positive"),
        CheckConstraint(
            "lifecycle_status IN "
            "('RECRUITING','READY','IN_PROGRESS','COMPLETED','CANCELED','ABORTED')",
            name="program_lifecycle_valid",
        ),
    )


class ApplicationRecord(Base):
    __tablename__ = "recruit_applications"
    application_id = Column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    recruit_id = Column(
        BigInteger, ForeignKey("recruit_programs.recruit_id"), nullable=False
    )
    member_id = Column(BigInteger, ForeignKey("members.member_id"), nullable=False)
    sequence = Column(Integer, nullable=False)
    submitted_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="program_application_order_positive"),
        CheckConstraint(
            "status IN ('ACCEPTED','WAITING','CANCELED','LEFT')",
            name="program_application_status_valid",
        ),
        UniqueConstraint(
            "recruit_id", "sequence", name="program_application_sequence_unique"
        ),
        Index(
            "program_waiting_order", "recruit_id", "status", "submitted_at", "sequence"
        ),
        Index(
            "program_active_member_unique",
            "recruit_id",
            "member_id",
            unique=True,
            postgresql_where=status.in_(["ACCEPTED", "WAITING"]),
            sqlite_where=status.in_(["ACCEPTED", "WAITING"]),
        ),
    )


class EligibilityRecord(Base):
    __tablename__ = "recruit_eligibility"
    member_id = Column(BigInteger, ForeignKey("members.member_id"), primary_key=True)
    withdrawal_count = Column(Integer, nullable=False, default=0)
    restricted_at = Column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("withdrawal_count >= 0", name="program_withdrawal_nonnegative"),
    )


class WithdrawalRecord(Base):
    __tablename__ = "recruit_withdrawals"
    event_key = Column(String(180), primary_key=True)
    member_id = Column(BigInteger, ForeignKey("members.member_id"), nullable=False)
    recruit_id = Column(BigInteger, ForeignKey("recruits.recruit_id"), nullable=False)
    occurred_at = Column(DateTime(timezone=True), nullable=False)


class CurriculumRecord(Base):
    __tablename__ = "recruit_curricula"
    recruit_id = Column(
        BigInteger, ForeignKey("recruit_programs.recruit_id"), primary_key=True
    )
    version = Column(Integer, nullable=False, default=1)
    items = Column(JSON, nullable=False, default=list)


class ActivityRecord(Base):
    __tablename__ = "recruit_activities"
    activity_id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    recruit_id = Column(
        BigInteger,
        ForeignKey("recruit_programs.recruit_id"),
        nullable=False,
        index=True,
    )
    author_member_id = Column(
        BigInteger, ForeignKey("members.member_id"), nullable=False
    )
    created_at = Column(DateTime(timezone=True), nullable=False)
    payload = Column(JSON, nullable=False)


class RecognitionRecord(Base):
    """개인별 인정 근거. 운영 종료와 자동으로 동일시하지 않는다."""

    __tablename__ = "recruit_recognitions"
    recognition_key = Column(String(180), primary_key=True)
    recruit_id = Column(
        BigInteger, ForeignKey("recruit_programs.recruit_id"), nullable=False
    )
    member_id = Column(BigInteger, ForeignKey("members.member_id"), nullable=False)
    activity_id = Column(
        BigInteger, ForeignKey("recruit_activities.activity_id"), nullable=False
    )
    payload = Column(JSON, nullable=False)


class OutboxRecord(Base):
    """활동/일정과 함께 저장하는 전달 요청. 실제 전송과 영속 기록을 분리한다."""

    __tablename__ = "recruit_outbox"
    event_key = Column(String(240), primary_key=True)
    recruit_id = Column(
        BigInteger, ForeignKey("recruit_programs.recruit_id"), nullable=False
    )
    kind = Column(String(50), nullable=False)
    schedule_version = Column(Integer)
    status = Column(String(30), nullable=False, default="PENDING")
    attempts = Column(Integer, nullable=False, default=0)
    payload = Column(JSON, nullable=False)
    __table_args__ = (Index("program_outbox_status", "status", "kind"),)


class CommandRecord(Base):
    """같은 연장 요청의 재시도와 다른 내용의 키 재사용을 구분한다."""

    __tablename__ = "recruit_program_commands"
    recruit_id = Column(
        BigInteger, ForeignKey("recruit_programs.recruit_id"), primary_key=True
    )
    request_key = Column(String(100), primary_key=True)
    member_id = Column(BigInteger, nullable=False)
    request = Column(JSON, nullable=False)
    response = Column(JSON, nullable=False)
