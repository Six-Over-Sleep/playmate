
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column


from backend.app.core.database import Base


class PostLike(Base):
    __tablename__ = "post_likes"

    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.post_id"), primary_key=True
    )

    member_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("members.member_id"), primary_key=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        Index("idx_post_likes_member_id", "member_id"),
    )
