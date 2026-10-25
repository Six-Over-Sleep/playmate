# 게시판, 게시글, 댓글의 API 요청 및 응답 데이터 형식을 정의하는 Pydantic Schema
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


# 공통 요청 데이터 검증 모델
class StrictModel(BaseModel):
    # extra="forbid" : 정의되지 않은 추가 필드가 들어오면 오류 발생
    # str_strip_whitespace=True : 문자열 앞뒤 공백을 자동으로 제거
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# 게시판 생성 시 클라이언트에서 전달하는 데이터
class BoardCreate(StrictModel):
    # name : 게시판 이름 (1~40자)
    # description : 게시판 설명 (선택 입력, 최대 200자)
    # creation_reason : 게시판 생성 사유 (선택 입력, 최대 500자)
    name: str = Field(min_length=1, max_length=40)
    description: str | None = Field(default=None, max_length=200)
    creation_reason: str | None = Field(default=None, max_length=500)


# 게시판 조회 및 생성 결과를 반환할 때 사용하는 데이터
class BoardResponse(BaseModel):
    # id : 게시판 고유 번호
    # name : 게시판 이름
    # description : 게시판 설명 (없으면 None)
    # created_at : 게시판 생성 시간
    id: int
    name: str
    description: str | None = None
    created_at: datetime


# 게시글 작성 및 수정 시 전달하는 데이터
class PostWrite(StrictModel):
    # title : 게시글 제목 (1~100자)
    # body : 게시글 본문 (1~20,000자)
    title: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=20000)


# 게시글에 첨부된 이미지 정보를 반환하는 데이터
class PostImageResponse(BaseModel):
    # id : 이미지 고유 번호
    # url : 이미지 조회 주소
    # original_name : 사용자가 업로드한 원본 파일명
    id: int
    url: str
    original_name: str


# 게시글 상세 및 목록 조회 결과를 반환하는 데이터
class PostResponse(BaseModel):
    # id : 게시글 고유 번호
    # board_id : 게시글이 속한 게시판 번호
    # title : 게시글 제목
    # body : 게시글 본문
    id: int
    board_id: int
    title: str
    body: str

    # author_id : 게시글 작성자 회원 번호
    # author_name : 화면에 표시할 작성자 이름
    author_id: int
    author_name: str

    # created_at : 게시글 최초 작성 시간
    # updated_at : 게시글 마지막 수정 시간
    # comment_count : 댓글 수 (기본값 0)
    # is_owner : 현재 로그인한 회원이 작성자인지 여부 (기본값 False)
    created_at: datetime
    updated_at: datetime
    comment_count: int = 0
    is_owner: bool = False

    # like_count : 좋아요 수
    # liked_by_me : 현재 로그인한 회원의 좋아요 여부
    # scrapped_by_me : 현재 회원의 스크랩 여부 (목록에서는 None, 상세에서만 계산)
    like_count: int = 0
    liked_by_me: bool = False
    scrapped_by_me: bool | None = None

    # images : 게시글 이미지 목록
    # default_factory=list : 요청/응답 객체마다 새로운 빈 목록 생성
    images: list[PostImageResponse] = Field(default_factory=list)


# 좋아요 등록·취소 후 반환하는 데이터
class PostLikeResponse(BaseModel):
    post_id: int
    like_count: int
    liked_by_me: bool


# 스크랩 등록·취소 후 반환하는 데이터 (스크랩 수는 제공하지 않음)
class PostScrapResponse(BaseModel):
    post_id: int
    scrapped_by_me: bool


# 댓글 및 대댓글 작성 시 전달하는 데이터
class CommentWrite(StrictModel):
    body: str = Field(min_length=1, max_length=2000)

    # 일반 댓글이면 None, 대댓글이면 부모 댓글 ID
    parent_comment_id: int | None = Field(default=None, gt=0)


# 댓글 조회 및 작성 결과를 반환하는 데이터
class CommentResponse(BaseModel):
    id: int
    post_id: int

    # 대댓글 관계 (일반 댓글이면 None)
    parent_comment_id: int | None = None
    body: str

    # 삭제된 부모 댓글 자리표시는 작성자 정보를 숨기므로 None일 수 있음
    author_id: int | None
    author_name: str

    created_at: datetime
    updated_at: datetime
    is_owner: bool = False

    # 대댓글이 남아 있는 삭제된 부모 댓글 자리표시 여부
    is_deleted: bool = False
