
# 댓글 및 대댓글 정보를 관리하는 SQLAlchemy 모델
from sqlalchemy import Column, BigInteger, Text, DateTime, ForeignKey, text
from backend.app.core.database import Base


class Comment(Base):
    __tablename__ = "comments"

    # 댓글 고유 번호 (PK)
    comment_id = Column(
        BigInteger,
        primary_key=True
    )

    # 댓글이 속한 게시글
    post_id = Column(
        BigInteger,
        ForeignKey("posts.post_id"),
        nullable=False
    )

    # 댓글 작성자
    author_member_id = Column(
        BigInteger,
        ForeignKey("members.member_id"),
        nullable=False
    )

    # 댓글 내용
    body = Column(
        Text,
        nullable=False
    )

    # 댓글 작성 시간
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP")
    )

    # 댓글 수정 시간
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP")
    )

    # 논리삭제 시간
    deleted_at = Column(
        DateTime,
        nullable=True
    )

    # 부모 댓글 ID (일반 댓글이면 NULL)
    parent_comment_id = Column(
        BigInteger,
        ForeignKey("comments.comment_id"),
        nullable=True
    )
