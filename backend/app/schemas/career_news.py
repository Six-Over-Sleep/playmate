"""커리어 브리핑 뉴스 조회·스크랩 응답 형식 (Issue #74).

뉴스 데이터는 database/sql/017_career_news.sql의 career_news / career_news_fields / career_news_scraps를 쓴다.
현재 링크는 Google News RSS 링크(link_type=GOOGLE_NEWS_RSS)이며 언론사 원문 주소로 검증된 값이 아니므로
original_url은 비워 두고 link_url / link_type으로 따로 전달한다.
요약·해설·키워드 필드는 화면 호환과 향후 AI 기능을 위해 유지하며, 값을 만들어 넣지 않는다.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# 채용 트렌드(job_trends_catalog.FIELDS)와 같은 8개 직무 분야 코드
CareerNewsFieldCode = Literal[
    "data_ai", "backend", "frontend", "mobile",
    "cloud_infra", "security", "qa_test", "it_product",
]

# 분야 표시 순서와 이름 (크롤러 config.CATEGORIES의 이름과 같음)
FIELD_NAMES: dict[str, str] = {
    "data_ai": "데이터·AI",
    "backend": "백엔드·서버",
    "frontend": "프론트엔드·웹",
    "mobile": "모바일 개발",
    "cloud_infra": "클라우드·인프라",
    "security": "정보보안",
    "qa_test": "QA·테스트",
    "it_product": "IT기획·디자인",
}

# GOOGLE_NEWS_RSS: news.google.com 기사 링크 (언론사 원문으로 이동하는지 검증 전)
# UNVERIFIED     : 그 밖의 링크 (언론사 직접 주소인지 확인하지 않음)
CareerNewsLinkType = Literal["GOOGLE_NEWS_RSS", "UNVERIFIED"]


class CareerNewsItem(BaseModel):
    """커리어 브리핑 목록·상세 화면 한 건. 기존 React 화면이 읽는 필드를 모두 포함한다."""

    id: int  # 화면 key·스크랩 대상 (= news_id)
    news_id: int

    title: str
    publisher: str  # 언론사 이름 (없으면 빈 문자열)

    # 한국 시간 기준 발행일 'YYYY-MM-DD' (없으면 null). 정밀 시각은 published_datetime(UTC)
    published_at: str | None
    published_datetime: datetime | None

    # 대표 분야 이름(분야 필터를 쓰면 그 분야)과 전체 분야
    category: str
    field_code: CareerNewsFieldCode
    categories: list[str]
    field_codes: list[CareerNewsFieldCode]

    # 기사 링크: 아직 언론사 원문 주소로 검증된 링크가 없으므로 original_url은 항상 null
    link_url: str
    link_type: CareerNewsLinkType
    original_url: str | None = None

    # 향후 AI 요약·분류용 (현재 데이터 없음, 가짜 값을 만들지 않음)
    summary: str | None = None
    news_type: str | None = None
    why_it_matters: str | None = None
    keywords: list[str] = Field(default_factory=list)
    study_keywords: list[str] = Field(default_factory=list)

    scrapped_by_me: bool


class CareerNewsListResponse(BaseModel):
    """최근 뉴스 목록. 결과가 없으면 items는 빈 목록이다."""

    items: list[CareerNewsItem]
    count: int = Field(ge=0)
    field_code: CareerNewsFieldCode | None
    days: int = Field(ge=1)
    limit: int = Field(ge=1)


class CareerNewsScrapResponse(BaseModel):
    news_id: int
    scrapped_by_me: bool


class CareerNewsDetailResponse(CareerNewsItem):
    """뉴스 상세 한 건. 숨긴 뉴스는 내가 스크랩한 경우에만 조회되며 is_hidden=true다."""

    is_hidden: bool = False


class CareerNewsMyScrapItem(BaseModel):
    """마이페이지 내 스크랩 목록의 뉴스 한 건. 게시글 스크랩(post_id)과 구분하도록 item_type을 둔다."""

    item_type: Literal["NEWS"] = "NEWS"
    news_id: int
    title: str
    publisher: str
    category: str  # 대표 분야 이름 (분야가 없으면 빈 문자열)
    field_code: CareerNewsFieldCode | None
    published_at: str | None  # 한국 시간 기준 발행일 'YYYY-MM-DD'
    # 스크랩 시각: 게시글 스크랩(post_scraps.created_at)과 같은 DB 기본값(CURRENT_TIMESTAMP)을 그대로 보낸다
    scrapped_at: datetime
    is_hidden: bool  # 운영자가 숨긴 뉴스 (브리핑 목록에는 없고, 스크랩 해제만 가능)


class CareerNewsMyScrapListResponse(BaseModel):
    """내가 스크랩한 뉴스 중 최근 limit건 (전체 목록이 아님). 스크랩이 없으면 items는 빈 목록이다."""

    items: list[CareerNewsMyScrapItem]
    count: int = Field(ge=0)
    limit: int = Field(ge=1)
