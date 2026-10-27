"""PLAYMATE 취준 도감 후기 요청·응답 데이터 검증 스키마.

현재 STEP 11-7에서는 후기 작성과 상세 응답 형식만 정의한다.
DB 저장과 권한 검사는 추후 career_service.py에서 처리한다.
"""

from datetime import date, datetime
from typing import Literal

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

    # 좋아요·스크랩 (게시판 공통 post_likes·post_scraps 기준, 스크랩 수는 제공하지 않음)
    like_count: int = 0
    liked_by_me: bool = False
    scrapped_by_me: bool = False
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

    # 목록 카드용 좋아요 수·댓글 수 (삭제된 댓글 자리표시는 제외)
    like_count: int = 0
    comment_count: int = 0
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



# =========================================
# 커리어 톡톡 - 공통 코드
# =========================================

# 커리어 톡톡 하위 카테고리
TalkSubcategory = Literal[
    "JOB_SEARCH",
    "JOB_CHANGE",
    "CAREER_PATH",
    "DAILY",
    "UPDATE",
    "SALARY",
]

# 현재 취업 상태
TalkStatus = Literal[
    "PREPARING",
    "NEW",
    "EXPERIENCED",
    "JOB_CHANGE",
    "OTHER",
]


# =========================================
# 1. 커리어 톡톡 - 게시글 등록
# =========================================

class CareerTalkCreate(BaseModel):
    """커리어 톡톡 게시글 작성 요청."""

    model_config = {"extra": "forbid"}

    title: str = Field(
        min_length=1,
        max_length=100,
    )

    body: str = Field(
        min_length=1,
        max_length=20000,
    )

    subcategory_code: TalkSubcategory

    job_category_code: str | None = Field(
        default=None,
        max_length=50,
    )

    current_status: TalkStatus | None = None

    is_anonymous: bool = True

    @field_validator("title", "body", mode="before")
    @classmethod
    def strip_required_text(cls, value):
        if isinstance(value, str):
            return value.strip()

        return value
    
    @field_validator("job_category_code", mode="before")
    @classmethod
    def strip_optional_text(cls, value):
        """선택 입력값의 빈 문자열을 NULL로 변환한다."""

        if isinstance(value, str):
            return value.strip() or None

        return value


# =========================================
# 2. 커리어 톡톡 - 게시글 수정
# =========================================

class CareerTalkUpdate(BaseModel):
    """커리어 톡톡 게시글 수정 요청."""

    model_config = {"extra": "forbid"}

    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )

    body: str | None = Field(
        default=None,
        min_length=1,
        max_length=20000,
    )

    subcategory_code: TalkSubcategory | None = None

    job_category_code: str | None = Field(
        default=None,
        max_length=50,
    )

    current_status: TalkStatus | None = None

    is_anonymous: bool | None = None

    @field_validator("title", "body", mode="before")
    @classmethod
    def strip_required_text(cls, value):
        """수정할 제목과 본문의 공백을 제거한다."""

        if isinstance(value, str):
            return value.strip()

        return value

    @field_validator("job_category_code", mode="before")
    @classmethod
    def strip_optional_text(cls, value):
        """빈 문자열을 NULL로 변환한다."""

        if isinstance(value, str):
            return value.strip() or None

        return value

    @model_validator(mode="after")
    def validate_update(self):
        """빈 요청과 필수 항목의 NULL 변경을 차단한다."""

        if not self.model_fields_set:
            raise ValueError(
                "수정할 항목을 하나 이상 입력해주세요."
            )

        required_fields = {
            "title",
            "body",
            "subcategory_code",
            "is_anonymous",
        }

        for field in required_fields & self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(
                    f"{field}에는 null을 입력할 수 없습니다."
                )

        return self


# =========================================
# 3. 커리어 톡톡 - 게시글 상세 응답
# =========================================

class CareerTalkResponse(BaseModel):
    """커리어 톡톡 게시글 상세 응답."""

    id: int
    title: str
    body: str

    author_name: str
    is_owner: bool

    # 좋아요·스크랩 (게시판 공통 post_likes·post_scraps 기준, 스크랩 수는 제공하지 않음)
    like_count: int = 0
    liked_by_me: bool = False
    scrapped_by_me: bool = False
    is_anonymous: bool

    category_code: Literal["talk"]
    subcategory_code: TalkSubcategory

    job_category_code: str | None = None
    current_status: TalkStatus | None = None

    created_at: datetime
    updated_at: datetime | None = None


# =========================================
# 4. 커리어 톡톡 - 게시글 목록 항목
# =========================================

class CareerTalkListItem(BaseModel):
    """커리어 톡톡 목록에 표시하는 게시글."""

    id: int
    title: str
    body_preview: str

    author_name: str
    is_owner: bool

    # 목록 카드용 좋아요 수·댓글 수 (삭제된 댓글 자리표시는 제외)
    like_count: int = 0
    comment_count: int = 0
    is_anonymous: bool

    subcategory_code: TalkSubcategory

    job_category_code: str | None = None
    current_status: TalkStatus | None = None

    created_at: datetime


# =========================================
# 5. 커리어 톡톡 - 목록 응답
# =========================================

class CareerTalkListResponse(BaseModel):
    """페이지네이션을 적용한 게시글 목록."""

    items: list[CareerTalkListItem]

    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)


# =========================================================
# 현직자 라운지 - 공통 코드
# =========================================================

LoungeSubcategory = Literal[
    "DAILY_WORK",
    "WORK_SKILLS",
    "COMPANY_LIFE",
    "JOB_QNA",
    "JUNIOR_TIPS",
    "ALUMNI_INTERVIEW",
]


# =========================================================
# 1. 현직자 라운지 - 게시글 등록
# =========================================================

class CareerLoungeCreate(BaseModel):
    """현직자 라운지 게시글 등록 요청."""

    model_config = {"extra": "forbid"}

    title: str = Field(
        min_length=1,
        max_length=100,
    )

    body: str = Field(
        min_length=1,
        max_length=20000,
    )

    subcategory_code: LoungeSubcategory

    job_category_code: str | None = Field(
        default=None,
        max_length=50,
    )

    experience_years: int | None = Field(
        default=None,
        ge=0,
        le=32767,
    )

    company_name: str | None = Field(
        default=None,
        max_length=150,
    )

    is_anonymous: bool = True

    @field_validator("title", "body", mode="before")
    @classmethod
    def strip_required_text(cls, value):
        if isinstance(value, str):
            return value.strip()

        return value

    @field_validator(
        "job_category_code",
        "company_name",
        mode="before",
    )
    @classmethod
    def strip_optional_text(cls, value):
        if isinstance(value, str):
            return value.strip() or None

        return value


# =========================================================
# 2. 현직자 라운지 - 게시글 수정
# =========================================================

class CareerLoungeUpdate(BaseModel):
    """현직자 라운지 게시글 수정 요청."""

    model_config = {"extra": "forbid"}

    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )

    body: str | None = Field(
        default=None,
        min_length=1,
        max_length=20000,
    )

    subcategory_code: LoungeSubcategory | None = None

    job_category_code: str | None = Field(
        default=None,
        max_length=50,
    )

    experience_years: int | None = Field(
        default=None,
        ge=0,
        le=32767,
    )

    company_name: str | None = Field(
        default=None,
        max_length=150,
    )

    is_anonymous: bool | None = None

    @field_validator("title", "body", mode="before")
    @classmethod
    def strip_required_text(cls, value):
        if isinstance(value, str):
            return value.strip()

        return value

    @field_validator(
        "job_category_code",
        "company_name",
        mode="before",
    )
    @classmethod
    def strip_optional_text(cls, value):
        if isinstance(value, str):
            return value.strip() or None

        return value

    @model_validator(mode="after")
    def validate_update(self):
        """빈 수정 요청 및 필수값 NULL 입력 방지."""

        if not self.model_fields_set:
            raise ValueError(
                "수정할 항목을 하나 이상 입력해주세요."
            )

        required_fields = {
            "title",
            "body",
            "subcategory_code",
            "is_anonymous",
        }

        for field in required_fields & self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(
                    f"{field}에는 null을 입력할 수 없습니다."
                )

        return self


# =========================================================
# 3. 현직자 라운지 - 상세 조회 응답
# =========================================================

class CareerLoungeResponse(BaseModel):
    """현직자 라운지 게시글 상세 정보."""

    id: int
    title: str
    body: str

    author_name: str
    is_owner: bool

    # 좋아요·스크랩 (게시판 공통 post_likes·post_scraps 기준, 스크랩 수는 제공하지 않음)
    like_count: int = 0
    liked_by_me: bool = False
    scrapped_by_me: bool = False
    is_anonymous: bool

    category_code: Literal["lounge"]
    subcategory_code: LoungeSubcategory

    job_category_code: str | None = None
    experience_years: int | None = None
    company_name: str | None = None

    created_at: datetime
    updated_at: datetime | None = None


# =========================================================
# 4. 현직자 라운지 - 목록 항목
# =========================================================

class CareerLoungeListItem(BaseModel):
    """현직자 라운지 게시글 목록 항목."""

    id: int
    title: str
    body_preview: str

    author_name: str
    is_owner: bool

    # 목록 카드용 좋아요 수·댓글 수 (삭제된 댓글 자리표시는 제외)
    like_count: int = 0
    comment_count: int = 0
    is_anonymous: bool

    subcategory_code: LoungeSubcategory

    job_category_code: str | None = None
    experience_years: int | None = None
    company_name: str | None = None

    created_at: datetime


# =========================================================
# 5. 현직자 라운지 - 목록 응답
# =========================================================

class CareerLoungeListResponse(BaseModel):
    """페이지네이션이 적용된 게시글 목록."""

    items: list[CareerLoungeListItem]

    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)


# =========================================================
# 커리어 연구소 - Pydantic Schema
# =========================================================


# =========================================================
# 1. 커리어 연구소 공통 코드
# =========================================================

# 하위 카테고리
LabSubcategory = Literal[
    "JOB_STRATEGY",
    "PORTFOLIO_FEEDBACK",
    "RESUME",
    "TECH_INTERVIEW",
    "CERTIFICATION",
    "JOB_COMPARISON",
]

# 게시글 유형
LabPostType = Literal[
    "QUESTION",
    "DISCUSSION",
    "GUIDE",
]


# =========================================================
# 2. 게시글 등록
# =========================================================

class CareerLabCreate(BaseModel):
    """커리어 연구소 게시글 등록 요청."""

    model_config = {"extra": "forbid"}

    title: str = Field(
        min_length=1,
        max_length=100,
    )

    body: str = Field(
        min_length=1,
        max_length=20000,
    )

    subcategory_code: LabSubcategory

    post_type: LabPostType

    is_anonymous: bool = True

    # 커리어 가이드 필수 항목
    guide_experience: str | None = Field(
        default=None,
        min_length=100,
        max_length=10000,
    )

    guide_advice: str | None = Field(
        default=None,
        min_length=100,
        max_length=10000,
    )

    @field_validator(
        "guide_experience",
        "guide_advice",
        mode="before",
    )
    @classmethod
    def strip_guide_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    # 토론 게시글에 사용할 투표 선택지
    # 투표가 없는 토론도 허용
    poll_options: list[str] = Field(
        default_factory=list,
        max_length=10,
    )

    @field_validator("title", "body", mode="before")
    @classmethod
    def strip_required_text(cls, value):
        """제목과 본문 앞뒤 공백 제거."""

        if isinstance(value, str):
            return value.strip()

        return value

    @field_validator("poll_options")
    @classmethod
    def validate_poll_options(cls, value):
        """투표 선택지 중복 및 길이 확인."""

        cleaned = []

        for option in value:
            if not isinstance(option, str):
                raise ValueError(
                    "투표 선택지는 문자열이어야 합니다."
                )

            option = option.strip()

            if not option:
                raise ValueError(
                    "빈 투표 선택지는 등록할 수 없습니다."
                )

            if len(option) > 200:
                raise ValueError(
                    "투표 선택지는 200자 이하로 입력해주세요."
                )

            cleaned.append(option)

        if len(set(cleaned)) != len(cleaned):
            raise ValueError(
                "중복된 투표 선택지는 등록할 수 없습니다."
            )

        return cleaned

    @model_validator(mode="after")
    def validate_post_type(self):
        """게시글 유형과 투표 선택지의 관계를 검증한다."""

        # 질문에는 투표 기능을 제공하지 않음
        if self.post_type == "QUESTION" and self.poll_options:
            raise ValueError(
                "질문 게시글에는 투표를 추가할 수 없습니다."
            )

        # 토론은 투표 없이 등록 가능
        # 투표를 추가한다면 최소 2개 선택지 필요
        if self.post_type == "DISCUSSION":
            if len(self.poll_options) == 1:
                raise ValueError(
                    "투표를 추가하려면 선택지가 최소 2개 필요합니다."
                )
        # 커리어 가이드 작성 조건
        if self.post_type == "GUIDE":

            # 본문 최소 500자
            if len(self.body.strip()) < 500:
                raise ValueError(
                    "커리어 가이드는 본문을 500자 이상 작성해야 합니다."
                )

            # 경험 및 근거
            if not self.guide_experience:
                raise ValueError(
                    "경험 및 근거를 입력해주세요."
                )

            # 실질적인 조언
            if not self.guide_advice:
                raise ValueError(
                    "실질적인 조언을 입력해주세요."
                )

            # 가이드에는 투표 불가
            if self.poll_options:
                raise ValueError(
                    "커리어 가이드에는 투표를 추가할 수 없습니다."
                )

        else:
            # 다른 게시글 유형에는 가이드 전용 항목 사용 불가
            if self.guide_experience is not None or self.guide_advice is not None:
                raise ValueError(
                    "가이드 전용 항목은 GUIDE 유형에서만 사용할 수 있습니다."
                )
    
        return self


# =========================================================
# 3. 게시글 수정
# =========================================================

class CareerLabUpdate(BaseModel):
    """커리어 연구소 게시글 수정 요청."""

    model_config = {"extra": "forbid"}

    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
    )

    body: str | None = Field(
        default=None,
        min_length=1,
        max_length=20000,
    )

    subcategory_code: LabSubcategory | None = None

    is_anonymous: bool | None = None

    # 커리어 가이드 수정 항목
    guide_experience: str | None = Field(
        default=None,
        min_length=100,
        max_length=10000,
    )

    guide_advice: str | None = Field(
        default=None,
        min_length=100,
        max_length=10000,
    )

    @field_validator("title", "body", mode="before")
    @classmethod
    def strip_required_text(cls, value):
        if isinstance(value, str):
            return value.strip()

        return value

    @model_validator(mode="after")
    def validate_update(self):
        """빈 수정 요청과 필수 항목의 NULL 입력을 방지한다."""

        if not self.model_fields_set:
            raise ValueError(
                "수정할 항목을 하나 이상 입력해주세요."
            )

        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(
                    f"{field}에는 null을 입력할 수 없습니다."
                )

        return self


# =========================================================
# 4. 투표 선택지 응답
# =========================================================

class CareerLabPollOption(BaseModel):
    """토론 게시글의 투표 선택지."""

    option_id: int

    option_text: str

    display_order: int

    vote_count: int = Field(
        default=0,
        ge=0,
    )


# =========================================================
# 5. 게시글 상세 조회 응답
# =========================================================

class CareerLabResponse(BaseModel):
    """커리어 연구소 게시글 상세 정보."""

    id: int

    title: str

    body: str

    author_name: str

    is_owner: bool

    # 좋아요·스크랩 (게시판 공통 post_likes·post_scraps 기준, 스크랩 수는 제공하지 않음)
    like_count: int = 0
    liked_by_me: bool = False
    scrapped_by_me: bool = False

    is_anonymous: bool

    category_code: Literal["lab"]

    subcategory_code: LabSubcategory

    post_type: LabPostType

    # 커리어 가이드 전용 항목
    guide_experience: str | None = None
    guide_advice: str | None = None

    # 질문 해결 여부
    is_resolved: bool

    # 투표 선택지 및 투표 수
    poll_options: list[CareerLabPollOption] = Field(
        default_factory=list
    )

    total_votes: int = Field(
        default=0,
        ge=0,
    )

    # 현재 로그인 회원이 선택한 항목
    my_vote_option_id: int | None = None

    created_at: datetime

    updated_at: datetime | None = None


# =========================================================
# 6. 게시글 목록 항목
# =========================================================

class CareerLabListItem(BaseModel):
    """목록 화면에 표시할 게시글."""

    id: int

    title: str

    body_preview: str

    author_name: str

    is_owner: bool

    # 목록 카드용 좋아요 수·댓글 수 (삭제된 댓글 자리표시는 제외)
    like_count: int = 0
    comment_count: int = 0

    is_anonymous: bool

    subcategory_code: LabSubcategory

    post_type: LabPostType

    is_resolved: bool

    created_at: datetime


# =========================================================
# 7. 게시글 목록 응답
# =========================================================

class CareerLabListResponse(BaseModel):
    """페이지네이션을 적용한 게시글 목록."""

    items: list[CareerLabListItem]

    total: int = Field(ge=0)

    page: int = Field(ge=1)

    page_size: int = Field(ge=1)


# =========================================================
# 8. 질문 해결 상태 변경 요청
# =========================================================

class CareerLabResolveUpdate(BaseModel):
    """질문 게시글의 해결 여부 변경."""

    is_resolved: bool


# =========================================================
# 9. 투표 요청
# =========================================================

class CareerLabVoteCreate(BaseModel):
    """토론 게시글 투표 요청."""

    option_id: int = Field(gt=0)
