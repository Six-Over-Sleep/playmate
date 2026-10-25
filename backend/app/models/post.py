
# 게시글의 제목, 본문, 작성자, 조회수 및 게시 상태 등을 관리하는 모델
from sqlalchemy import Column, BigInteger, Integer, String, Text, DateTime, ForeignKey
from backend.app.core.database import Base


class Post(Base):
    __tablename__ = "posts"

    # post_id : 게시글 고유 번호 (기본키)
    # board_id : 게시글이 속한 게시판 번호
    post_id = Column(BigInteger, primary_key=True)
    board_id = Column(BigInteger)

    # author_member_id : 게시글 작성자 회원 번호
    # ForeignKey() : members 테이블의 member_id와 연결
    # post_type : 게시글 유형 (일반 게시글, 모임 게시글 등)
    author_member_id = Column(BigInteger, ForeignKey("members.member_id"), nullable=False)
    post_type = Column(String)

    # title : 게시글 제목 (필수 입력)
    # body : 게시글 본문
    # tag_name : 게시글 분류 및 검색용 태그
    title = Column(String, nullable=False)
    body = Column(Text)
    tag_name = Column(String)

    # source_type : 게시글 작성 또는 수집 출처 구분
    # post_status : 게시글 상태 (게시, 숨김, 삭제 등)
    source_type = Column(String)
    post_status = Column(String)

    # view_count : 게시글 조회수
    view_count = Column(Integer)

    # published_at : 게시글 공개 시간
    # created_at : 게시글 최초 생성 시간
    # updated_at : 게시글 마지막 수정 시간
    # deleted_at : 게시글 삭제 처리 시간
    published_at = Column(DateTime)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    deleted_at = Column(DateTime)
