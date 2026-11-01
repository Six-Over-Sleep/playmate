"""신규 모임 계약. 기존 모임 스키마를 교체하지 않고 연결 단계까지 격리한다."""

from datetime import date, datetime, time
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

from backend.app.domain.recruit_program import aware


class DirectCareer(BaseModel):
    """신청 시점의 자기신고 자료. 마이페이지 원본과 별도로 저장한다."""

    model_config = ConfigDict(extra="forbid")
    skills: list[str] = Field(default_factory=list)
    education: str | None = None
    certificates: str | None = None
    experience: str | None = None
    awards: str | None = None
    portfolio_url: HttpUrl | None = None


class ProgramApplication(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_ids: list[int] = Field(default_factory=list)
    career_item_ids: list[str] = Field(default_factory=list)
    direct_input: DirectCareer = Field(default_factory=DirectCareer)
    leader_volunteer: bool = False

    @field_validator("skill_ids")
    @classmethod
    def valid_skills(cls, value):
        """숫자 ID 형식을 검사한다. 실제 사전 존재 여부는 서비스에서 확인한다."""
        if any(item <= 0 for item in value) or len(value) != len(set(value)):
            raise ValueError("담당 기술 ID는 양수이며 중복될 수 없습니다.")
        return value

    @field_validator("career_item_ids")
    @classmethod
    def career_not_connected(cls, value):
        """아직 조회할 수 없는 마이페이지 자료를 조용히 무시하지 않고 거절한다."""
        if value:
            raise ValueError(
                "마이페이지 커리어 연동은 후속 작업입니다. 직접 입력을 사용해주세요."
            )
        return value


class ProgramCreate(BaseModel):
    """프로그램 기본 일정은 시간대 포함 전체 운영 기간으로 정의한다."""

    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    category: Literal["project", "study"]
    recruit_mode: Literal["short", "regular"] = "short"
    capacity: int = Field(ge=2, le=5)
    starts_at: datetime
    ends_at: datetime
    meeting_start: datetime | None = None
    meeting_end: datetime | None = None
    regular_days: list[str] | None = None
    regular_time: time | None = None
    regular_start_date: date | None = None
    deadline_at: datetime | None = None
    required_skill_ids: list[int] = Field(default_factory=list)
    creator_application: ProgramApplication | None = None
    study_type: Literal["TECHNOLOGY", "CERTIFICATE"] | None = None
    difficulty: Literal["BEGINNER", "ADVANCED"] | None = None
    study_topic: str | None = None
    study_period: str | None = None
    study_method: str | None = None
    place: str | None = None
    is_online: bool = False
    contact_method: str | None = None

    @model_validator(mode="after")
    def schedule_and_category(self):
        """시간대·기존 일정 필드·종류별 필수 입력을 한 요청 안에서 대조한다."""
        start, end = aware(self.starts_at), aware(self.ends_at)
        if end <= start:
            raise ValueError("종료일은 시작일 이후여야 합니다.")
        if self.meeting_start is not None and aware(self.meeting_start) != start:
            raise ValueError("meeting_start와 starts_at이 다릅니다.")
        if self.meeting_end is not None and aware(self.meeting_end) != end:
            raise ValueError("meeting_end와 ends_at이 다릅니다.")
        if self.recruit_mode == "regular" and not (
            self.regular_days and self.regular_time and self.regular_start_date
        ):
            raise ValueError("정기 모임은 요일·시간·첫 날짜가 필요합니다.")
        if self.recruit_mode == "regular":
            from zoneinfo import ZoneInfo

            local_start = start.astimezone(ZoneInfo("Asia/Seoul"))
            if (
                local_start.date() != self.regular_start_date
                or local_start.time().replace(tzinfo=None) != self.regular_time
            ):
                raise ValueError("정기 첫 날짜·시간과 starts_at이 다릅니다.")
            if len(set(self.regular_days)) != len(self.regular_days) or not set(
                self.regular_days
            ).issubset({"월", "화", "수", "목", "금", "토", "일"}):
                raise ValueError("정기 요일이 잘못되었습니다.")
        if self.deadline_at is not None:
            from datetime import timedelta

            if aware(self.deadline_at) != start - timedelta(hours=24):
                raise ValueError("모집 마감은 시작 정확히 24시간 전입니다.")
        if len(self.required_skill_ids) != len(set(self.required_skill_ids)) or any(
            item <= 0 for item in self.required_skill_ids
        ):
            raise ValueError("필수 기술 ID가 잘못되었습니다.")
        if self.category == "project" and not self.required_skill_ids:
            raise ValueError("프로젝트 필수 기술이 필요합니다.")
        if self.category == "study":
            if self.required_skill_ids:
                raise ValueError("스터디는 필수 기술 배정을 사용하지 않습니다.")
            if not self.study_topic or self.study_type is None:
                raise ValueError("스터디 주제와 종류가 필요합니다.")
            if self.study_type == "TECHNOLOGY" and self.difficulty is None:
                raise ValueError("기술 공부의 난이도가 필요합니다.")
            if self.study_type == "CERTIFICATE" and self.difficulty is not None:
                raise ValueError("자격증은 난이도 대신 시험 범위를 사용합니다.")
        return self


class ProgramEdit(BaseModel):
    """핵심 조건 잠금 이후에도 허용되는 제목·본문·연락 안내만 편집한다."""

    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, min_length=1)
    body: str | None = Field(default=None, min_length=1)
    contact_method: str | None = None
    capacity: int | None = Field(default=None, ge=2, le=5)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    required_skill_ids: list[int] | None = None


class ExtensionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    starts_at: datetime
    ends_at: datetime
    schedule_version: int = Field(ge=1)
    request_key: str = Field(min_length=8, max_length=100)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schedule_version: int = Field(ge=1)


class ReasonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1)


class CurriculumItem(BaseModel):
    week: int = Field(ge=1)
    title: str = Field(min_length=1)
    content: str


class CurriculumUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    items: list[CurriculumItem]

    @field_validator("items")
    @classmethod
    def unique_weeks(cls, items):
        """중복 주차가 덮어쓰기처럼 보이지 않도록 입력 오류로 반환한다."""
        if len({item.week for item in items}) != len(items):
            raise ValueError("커리큘럼 주차가 중복되었습니다.")
        return items


class ActivityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    activity_type: Literal["WEEKLY_CHECK", "REVIEW", "OUTPUT", "PARTICIPATION_PROOF"]
    week: int | None = Field(default=None, ge=1)
    submission_stage: Literal["INTERIM", "FINAL"] | None = None
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    links: list[HttpUrl] = Field(default_factory=list)
    attachment_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def activity_fields(self):
        """활동별 주차/단계를 구분하고 미연결 스토리지 참조를 거절한다."""
        if self.activity_type == "WEEKLY_CHECK" and self.week is None:
            raise ValueError("주간 인증 주차가 필요합니다.")
        if self.activity_type != "WEEKLY_CHECK" and self.week is not None:
            raise ValueError("주차는 주간 인증에만 사용합니다.")
        if self.activity_type != "OUTPUT" and self.submission_stage is not None:
            raise ValueError("중간/최종 구분은 결과물에만 사용합니다.")
        if self.activity_type == "OUTPUT" and self.submission_stage is None:
            raise ValueError("결과물에는 INTERIM 또는 FINAL 단계가 필요합니다.")
        if self.attachment_ids:
            raise ValueError("스토리지 연결 전에는 텍스트·링크만 지원합니다.")
        return self
