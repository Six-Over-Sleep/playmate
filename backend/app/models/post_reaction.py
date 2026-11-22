"""게시글 반응(좋아요·스크랩·신고) 모델 — post_reactions 한 테이블 (045, #159).

PostLike·PostScrap은 reaction_type 값이 고정된 단일 테이블 상속 하위 클래스다.
db.query(PostLike), select(PostLike...)는 SQLAlchemy가 reaction_type = 'LIKE' 조건을 자동으로 붙인다.
기본키는 (post_id, reaction_type, member_id)이므로 session.get에는 세 값을 넘긴다.
신고(REPORT)는 원시 SQL(routers/board_moderation.py)에서만 다루므로 하위 클래스를 두지 않는다.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base

LIKE = "LIKE"
SCRAP = "SCRAP"
REPORT = "REPORT"


class PostReaction(Base):
    __tablename__ = "post_reactions"

    post_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("posts.post_id"), primary_key=True
    )
    reaction_type: Mapped[str] = mapped_column(String(10), primary_key=True)
    member_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("members.member_id"), primary_key=True
    )
    reason: Mapped[str | None] = mapped_column(String(20), nullable=True)
    details: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __mapper_args__ = {"polymorphic_on": "reaction_type"}


class PostLike(PostReaction):
    __mapper_args__ = {"polymorphic_identity": LIKE}


class PostScrap(PostReaction):
    __mapper_args__ = {"polymorphic_identity": SCRAP}
