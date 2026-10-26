
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


# =========================================================
# 1. 마이페이지 프로필
# =========================================================

# 내 프로필 조회
class MyProfileResponse(BaseModel):
    member_id: int
    nickname: str
    profile_image_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


# 내 프로필 수정
class MyProfileUpdate(BaseModel):
    nickname: str = Field(min_length=1)

    @field_validator("nickname")
    @classmethod
    def validate_nickname(cls, value):
        value = value.strip()

        if not value:
            raise ValueError("닉네임을 입력해주세요.")

        return value


# =========================================================
# 2. 종합 레벨 및 경험치
# =========================================================

# 회원 종합 레벨
class MyLevelResponse(BaseModel):
    level: int
    total_xp: int
    next_level_xp: int | None
    remaining_xp: int
    progress_percent: float


# 경험치 획득 기록
class MyXPHistoryResponse(BaseModel):
    history_id: int
    activity_type: str
    xp_change: int
    activity_date: date
    created_at: datetime


# =========================================================
# 3. 출석 현황
# =========================================================

# 연속 출석 현황
class MyAttendanceResponse(BaseModel):
    attended_today: bool
    streak_days: int
    achieved_7_days: bool
    achieved_30_days: bool


# =========================================================
# 4. 스킬 레벨
# =========================================================

# 회원 스킬 레벨
class MySkillResponse(BaseModel):
    skill_code: str
    skill_name: str
    level: int
    total_xp: int

    next_level_xp: int | None
    remaining_xp: int
    progress_percent: float


# 스킬별 세부 학습 영역
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


# =========================================================
# 5. 내가 작성한 게시글
# =========================================================

# 게시글 목록 응답
class MyPostResponse(BaseModel):
    post_id: int

    # 게시글 이동을 위한 정보
    board_id: int | None = None
    board_name: str | None = None
    post_type: str | None = None
    career_category: str | None = None

    # 게시글 기본 정보
    title: str
    created_at: datetime | None = None


# 게시글 페이지네이션 응답
class MyPostPageResponse(BaseModel):
    items: list[MyPostResponse]
    total: int
    page: int
    page_size: int


# =========================================================
# 6. 내가 작성한 댓글 및 대댓글
# =========================================================

# 댓글 목록 응답
class MyCommentResponse(BaseModel):
    comment_id: int
    post_id: int

    # 원본 게시글 이동을 위한 정보
    board_id: int | None = None
    post_type: str | None = None
    career_category: str | None = None
    board_name: str | None = None

    # 댓글 기본 정보
    post_title: str
    body: str
    parent_comment_id: int | None = None
    created_at: datetime | None = None


# 댓글 페이지네이션 응답
# 반드시 MyCommentResponse 아래에 선언
class MyCommentPageResponse(BaseModel):
    items: list[MyCommentResponse]
    total: int
    page: int
    page_size: int


# =========================================================
# 7. 내가 스크랩한 게시글
# =========================================================

# 스크랩 목록 응답
class MyScrapResponse(BaseModel):
    post_id: int

    # 원본 게시글 이동을 위한 정보
    board_id: int | None = None
    post_type: str | None = None
    career_category: str | None = None

    # 스크랩 기본 정보
    title: str
    scrapped_at: datetime


# =========================================================
# 8. 내가 참여하거나 생성한 모임
# =========================================================

# 모임 목록 응답
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
