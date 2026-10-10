# 모임 게시글의 제목, 본문, 작성자, 조회수 등을 관리하는 모델
from sqlalchemy import Column, BigInteger, Integer, String, Text, DateTime, ForeignKey
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
