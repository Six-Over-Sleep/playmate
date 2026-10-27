
# 마이페이지 프로필 응답 스키마
from pydantic import BaseModel, ConfigDict


class MyProfileResponse(BaseModel):
    member_id: int
    nickname: str
    profile_image_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


from pydantic import Field, field_validator


class MyProfileUpdate(BaseModel):
    nickname: str = Field(min_length=1)

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, value):
        value = value.strip()

        if not value:
            raise ValueError("닉네임을 입력해주세요.")

        return value


# 회원 종합 레벨 응답

class MyLevelResponse(BaseModel):
    level: int
    total_xp: int
    next_level_xp: int | None
    remaining_xp: int
    progress_percent: float



from datetime import date, datetime


class MyXPHistoryResponse(BaseModel):
    history_id: int
    activity_type: str
    xp_change: int
    activity_date: date
    created_at: datetime



# 연속 출석 현황 응답
class MyAttendanceResponse(BaseModel):
    attended_today: bool
    streak_days: int
    achieved_7_days: bool
    achieved_30_days: bool


# 회원 스킬 레벨 응답
class MySkillResponse(BaseModel):
    skill_code: str
    skill_name: str
    level: int
    total_xp: int



class MySkillResponse(BaseModel):
    skill_code: str
    skill_name: str
    level: int
    total_xp: int

    # 추가할 필드
    next_level_xp: int | None
    remaining_xp: int
    progress_percent: float


# 스킬별 세부 학습 영역 조회
class MySkillTopicResponse(BaseModel):
    skill_code: str
    topic_code: str
    solved_count: int
    earned_xp: int



# 스킬별 세부 학습 영역 정답률
class MySkillAccuracyResponse(BaseModel):
    skill_code: str
    topic_code: str
    total_attempts: int
    correct_count: int
    incorrect_count: int
    accuracy_percent: float



class MyPostResponse(BaseModel):
    post_id: int
    board_id: int | None = None
    board_name: str | None = None
    post_type: str | None = None
    title: str
    created_at: datetime | None = None


# 내 게시글 페이지네이션 응답
class MyPostPageResponse(BaseModel):
    items: list[MyPostResponse]
    total: int
    page: int
    page_size: int
    career_category: str | None = None


# 내가 작성한 댓글 및 대댓글 응답
class MyCommentResponse(BaseModel):
    comment_id: int
    post_id: int
    board_id: int | None = None
    post_type: str | None = None
    post_title: str
    body: str
    parent_comment_id: int | None = None
    created_at: datetime | None = None
    career_category: str | None = None
    recruit_id: int | None = None



# 내가 스크랩한 게시글 응답
class MyScrapResponse(BaseModel):
    post_id: int
    board_id: int | None = None
    post_type: str | None = None
    title: str
    scrapped_at: datetime
    career_category: str | None = None
    recruit_id: int | None = None


# 내가 생성하거나 참여한 모임
class MyMeetupResponse(BaseModel):
    recruit_id: int
    post_id: int
    title: str
    role: str
    status: str
    category: str | None = None
    recruit_mode: str | None = None
    state: str | None = None
    created_at: datetime | None = None


class MyCommentPageResponse(BaseModel):
    items: list[MyCommentResponse]
    total: int
    page: int
    page_size: int

# =========================================================
# 취업 스펙 등록 및 수정
# =========================================================

class MyCareerSpecUpdate(BaseModel):
    """내 취업 스펙 등록·수정 요청"""

    model_config = ConfigDict(extra="forbid")

    desired_job: str | None = Field(default=None, max_length=100)
    education: str | None = Field(default=None, max_length=200)
    certifications: str | None = None
    language_scores: str | None = None
    tech_stack: str | None = None
    projects: str | None = None
    introduction: str | None = None

    @field_validator(
        "desired_job",
        "education",
        "certifications",
        "language_scores",
        "tech_stack",
        "projects",
        "introduction",
    )
    @classmethod
    def strip_text(cls, value):
        if isinstance(value, str):
            return value.strip()
        return value


# =========================================================
# 취업 스펙 조회 응답
# =========================================================

class MyCareerSpecResponse(BaseModel):
    """내 취업 스펙 조회 응답"""

    member_id: int

    desired_job: str | None = None
    education: str | None = None
    certifications: str | None = None
    language_scores: str | None = None
    tech_stack: str | None = None
    projects: str | None = None
    introduction: str | None = None

    is_public: bool = False
    first_published_at: datetime | None = None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# =========================================================
# 취업 스펙 공개 여부 변경
# =========================================================

from pydantic import StrictBool


class MyCareerSpecVisibilityUpdate(BaseModel):
    """취업 스펙 공개·비공개 변경 요청"""

    model_config = ConfigDict(extra="forbid")

    # True: 공개 / False: 비공개
    is_public: StrictBool