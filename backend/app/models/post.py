# 모임 게시글의 제목, 본문, 작성자, 조회수 등을 관리하는 모델
from sqlalchemy import Column, BigInteger, Integer, String, Text, DateTime, ForeignKey, func
from backend.app.core.database import Base

class Post(Base):
    __tablename__ = "posts"

    # post_id : 게시글 고유 번호
    post_id = Column(BigInteger, primary_key=True)
    board_id = Column(BigInteger)

    # author_member_id : 게시글 작성자
    # ForeignKey() : 다른 테이블과 연결하는 키
    author_member_id = Column(BigInteger, ForeignKey("members.member_id"), nullable=False)
    post_type = Column(String)

    # title, body : 제목과 본문
    title = Column(String, nullable=False)
    body = Column(Text)
    tag_name = Column(String)
    source_type = Column(String)
    post_status = Column(String)

    # view_count : 조회수
    view_count = Column(Integer)
    published_at = Column(DateTime)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    deleted_at = Column(DateTime)


class PostLike(Base):
    """게시글 좋아요. (post_id, member_id) 기본키로 같은 회원의 중복 좋아요를 막음."""

    __tablename__ = "post_likes"

    post_id = Column(BigInteger, ForeignKey("posts.post_id"), primary_key=True)
    member_id = Column(BigInteger, ForeignKey("members.member_id"), primary_key=True)
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())


class PostScrap(Base):
    """게시글 스크랩. 좋아요와 같은 구조로 회원별 한 번만 저장됨."""

    __tablename__ = "post_scraps"

    post_id = Column(BigInteger, ForeignKey("posts.post_id"), primary_key=True)
    member_id = Column(BigInteger, ForeignKey("members.member_id"), primary_key=True)
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())


class Comment(Base):
    """게시글 댓글. parent_comment_id가 있으면 그 댓글의 대댓글임.

    삭제는 deleted_at을 기록하는 논리삭제이며 행은 남겨 둠.
    """

    __tablename__ = "comments"

    comment_id = Column(BigInteger, primary_key=True)
    post_id = Column(BigInteger, ForeignKey("posts.post_id"), nullable=False)
    author_member_id = Column(BigInteger, ForeignKey("members.member_id"), nullable=False)
    parent_comment_id = Column(BigInteger, ForeignKey("comments.comment_id"))
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    updated_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    deleted_at = Column(DateTime)
