
from sqlalchemy import (
    Column, BigInteger, Integer, String,
    DateTime, Text, ForeignKey,
    CheckConstraint, Index, Identity, text, func
)

from backend.app.core.database import Base


class Notification(Base):
    __tablename__ = "notifications"

    notification_id = Column(
        BigInteger, Identity(), primary_key=True
    )

    receiver_member_id = Column(
        BigInteger, ForeignKey("members.member_id"),
        nullable=False
    )

    actor_member_id = Column(
        BigInteger, ForeignKey("members.member_id"),
        nullable=False
    )

    notification_type = Column(
        String(30), nullable=False
    )

    post_id = Column(
        BigInteger, ForeignKey("posts.post_id")
    )

    comment_id = Column(
        BigInteger, ForeignKey("comments.comment_id")
    )

    status = Column(
        String(20),
        nullable=False,
        server_default=text("'PENDING'")
    )

    sent_at = Column(DateTime)
    error_message = Column(Text)

    retry_count = Column(
        Integer,
        nullable=False,
        server_default=text("0")
    )

    last_attempt_at = Column(DateTime)

    created_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp()
    )

    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp()
    )

    __table_args__ = (
        CheckConstraint(
            "notification_type IN ('COMMENT', 'REPLY', 'REACTION')",
            name="chk_notifications_type"
        ),
        CheckConstraint(
            "status IN ('PENDING', 'SENT', 'SKIPPED', 'FAILED')",
            name="chk_notifications_status"
        ),
        CheckConstraint(
            "retry_count >= 0",
            name="chk_notifications_retry"
        ),
        Index(
            "idx_notifications_pending",
            "created_at",
            "notification_id",
            postgresql_where=text("status = 'PENDING'")
        ),
    )
