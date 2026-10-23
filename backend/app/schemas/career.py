"""PLAYMATE 취준 도감 후기 요청·응답 데이터 검증 스키마.

현재 STEP 11-7에서는 후기 작성과 상세 응답 형식만 정의한다.
DB 저장과 권한 검사는 추후 career_service.py에서 처리한다.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic import BaseModel, Field, field_validator, model_validator


# 취준 도감 하위 메뉴 코드: 화면에 표시되는 한글 이름과 구분해서 관리한다.
ReviewSubcategory = Literal[
    "DOCUMENT", "CODING_ASSIGNMENT", "INTERVIEW", "FINAL", "SUCCESS"
]
ApplicationType = Literal["NEW", "EXPERIENCED"]
ProcessStage = Literal["DOCUMENT", "CODING_TEST", "ASSIGNMENT", "INTERVIEW", "FINAL"]
ProcessResult = Literal["PASS", "FAIL", "PENDING"]


class CareerReviewCreate(BaseModel):
    """취준 도감 후기 등록 요청 데이터."""

    title: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=500, max_length=20000)
    subcategory_code: ReviewSubcategory

    company_name: str | None = Field(default=None, max_length=150)
    is_company_private: bool = False
    job_category_code: str = Field(min_length=1, max_length=50)
    application_type: ApplicationType | None = None
    process_stage: ProcessStage
    process_result: ProcessResult
    process_date: date | None = None
    interview_format: str | None = Field(default=None, max_length=50)
    is_anonymous: bool = True

    @field_validator("title", "body", "job_category_code", mode="before")
    @classmethod
    def strip_required_text(cls, value):
        """앞뒤 공백 제거 후 필수값 및 글자 수를 검사하도록 한다."""
        return value.strip() if isinstance(value, str) else value

    @field_validator("company_name", "interview_format", mode="before")
    @classmethod
    def blank_to_none(cls, value):
        """선택 입력에 빈 문자열이 들어오면 DB의 NULL로 보낸다."""
        if isinstance(value, str):
            return value.strip() or None
        return value


class CareerReviewResponse(BaseModel):
    """취준 도감 후기 상세 조회 응답 데이터.

    익명 여부와 기업명 비공개 처리는 Repository 조회 결과를 사용한다.
    실제 작성자 member_id는 외부 응답에 포함하지 않는다.
    """

    id: int
    title: str
    body: str
    created_at: datetime
    updated_at: datetime | None = None
    is_owner: bool
    author_name: str

    category_code: Literal["reviews"]
    subcategory_code: ReviewSubcategory
    is_anonymous: bool

    company_name: str | None = None
    is_company_private: bool
    job_category_code: str
    application_type: ApplicationType | None = None
    process_stage: ProcessStage
    process_result: ProcessResult
    process_date: date | None = None
    interview_format: str | None = None

# =========================================
# 취준 도감 - 후기 목록 응답
# =========================================

class CareerReviewListItem(BaseModel):
    """목록 화면에 표시할 후기 정보."""

    id: int
    title: str
    body_preview: str
    created_at: datetime

    is_owner: bool
    author_name: str

    subcategory_code: ReviewSubcategory

    company_name: str | None = None
    job_category_code: str
    process_stage: ProcessStage
    process_result: ProcessResult


class CareerReviewListResponse(BaseModel):
    """페이지네이션을 적용한 후기 목록 응답."""

    items: list[CareerReviewListItem]

    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)


# =========================================
# 취준 도감 - 후기 수정 요청
# =========================================

class CareerReviewUpdate(BaseModel):
    """후기 수정 요청. 전달된 필드만 변경한다."""

    model_config = {"extra": "forbid"}

    title: str | None = Field(default=None, min_length=1, max_length=100)
    body: str | None = Field(default=None, min_length=500, max_length=20000)
    subcategory_code: ReviewSubcategory | None = None

    company_name: str | None = Field(default=None, max_length=150)
    is_company_private: bool | None = None
    job_category_code: str | None = Field(default=None, min_length=1, max_length=50)
    application_type: ApplicationType | None = None
    process_stage: ProcessStage | None = None
    process_result: ProcessResult | None = None
    process_date: date | None = None
    interview_format: str | None = Field(default=None, max_length=50)
    is_anonymous: bool | None = None

    @field_validator("title", "body", "job_category_code", mode="before")
    @classmethod
    def strip_required_text(cls, value):
        """앞뒤 공백을 제거한다."""
        return value.strip() if isinstance(value, str) else value

    @field_validator("company_name", "interview_format", mode="before")
    @classmethod
    def blank_to_none(cls, value):
        """선택 입력의 빈 문자열을 NULL로 변환한다."""
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def validate_changed_fields(self):
        """빈 요청과 필수 컬럼의 NULL 변경을 차단한다."""

        if not self.model_fields_set:
            raise ValueError("수정할 항목을 하나 이상 입력해주세요.")

        required_fields = {
            "title",
            "body",
            "subcategory_code",
            "is_anonymous",
            "is_company_private",
            "job_category_code",
            "process_stage",
            "process_result",
        }

        for field in required_fields & self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field}에는 null을 입력할 수 없습니다.")

        return self