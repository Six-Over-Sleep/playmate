
# Discord 개인 DM 알림 내역 및 전송 상태를 관리하는 모델
from sqlalchemy import (
    Column, BigInteger, Integer, String, Text, DateTime,
    ForeignKey, Identity, CheckConstraint, Index, text, func
)
from backend.app.core.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    # notification_id : 알림 고유 번호 (자동 증가)
    notification_id = Column(BigInteger, Identity(), primary_key=True)

    # receiver_member_id : 알림을 받을 회원
    # actor_member_id : 댓글, 답글, 반응 등의 행동을 한 회원
    receiver_member_id = Column(BigInteger, ForeignKey("members.member_id"), nullable=False)
    actor_member_id = Column(BigInteger, ForeignKey("members.member_id"), nullable=False)

    # notification_type : 알림 유형 (COMMENT, REPLY, REACTION)
    notification_type = Column(String(30), nullable=False)

    # post_id : 알림과 관련된 게시글 번호
    # comment_id : 알림과 관련된 댓글 번호
    post_id = Column(BigInteger, ForeignKey("posts.post_id"))
    comment_id = Column(BigInteger, ForeignKey("comments.comment_id"))

    # status : 알림 전송 상태 (PENDING, SENT, SKIPPED, FAILED)
    # 기본값 : PENDING (전송 대기)
    status = Column(String(20), nullable=False, server_default=text("'PENDING'"))

    # sent_at : 알림 전송 완료 시간
    # error_message : 전송 실패 시 오류 메시지
    sent_at = Column(DateTime)
    error_message = Column(Text)

    # retry_count : 알림 전송 재시도 횟수 (기본값 0)
    # last_attempt_at : 마지막 전송 시도 시간
    retry_count = Column(Integer, nullable=False, server_default=text("0"))
    last_attempt_at = Column(DateTime)

    # created_at : 알림 생성 시간
    # updated_at : 알림 정보 수정 시간
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at = Column(DateTime, nullable=False, server_default=func.current_timestamp(), onupdate=func.current_timestamp())

    # 데이터 제약조건 및 인덱스 설정
    __table_args__ = (
        # 알림 유형 제한
        CheckConstraint(
            "notification_type IN ('COMMENT', 'REPLY', 'REACTION')",
            name="chk_notifications_type"
        ),

        # 알림 전송 상태 제한
        CheckConstraint(
            "status IN ('PENDING', 'SENT', 'SKIPPED', 'FAILED')",
            name="chk_notifications_status"
        ),

        # 재시도 횟수는 0 이상
        CheckConstraint(
            "retry_count >= 0",
            name="chk_notifications_retry"
        ),

        # 전송 대기 중인 알림을 빠르게 조회하기 위한 인덱스
        Index(
            "idx_notifications_pending",
            "created_at",
            "notification_id",
            postgresql_where=text("status = 'PENDING'")
        ),
    )
