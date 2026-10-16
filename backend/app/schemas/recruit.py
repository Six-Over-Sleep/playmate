"""모임 생성·수정 요청과 응답에 사용하는 Pydantic 스키마."""

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")


def validate_regular_days(days: list[str] | None) -> list[str] | None:
    """요일 목록을 검사하고 그대로 반환함. 비어 있거나 중복·잘못된 요일이면 오류 발생."""
    if days is None:
        return days

    if not days or len(days) != len(set(days)):
        raise ValueError("요일은 중복 없이 1개 이상 선택해야 합니다.")

    if any(day not in WEEKDAYS for day in days):
        raise ValueError("요일은 월~일 중에서 선택해야 합니다.")

    return days


class RecruitCreate(BaseModel):
    """모임 생성 요청 데이터와 일정 검증 규칙."""

    # 게시글 및 모임 기본 정보
    title: str
    body: str
    recruit_mode: Literal["regular", "short"]
    category: str
    capacity: int = Field(gt=0)
    deadline_at: datetime

    # 정기 모임 / 단기 모임 일정
    regular_days: list[str] | None = None
    regular_time: time | None = None
    meeting_start: datetime | None = None
    meeting_end: datetime | None = None

    # 장소 및 연락 방법
    place: str | None = None
    is_online: bool = False
    contact_method: str | None = None

    # 카테고리별 상세 정보
    sport_name: str | None = None
    game_name: str | None = None
    study_topic: str | None = None
    study_period: str | None = None
    study_method: str | None = None
    product_name: str | None = None
    purchase_url: str | None = None
    estimated_price_per_person: float | None = None
    pickup_method: str | None = None
    regular_start_date: date | None = None

    @model_validator(mode="after")
    def check_schedule(self):
        """모임 방식에 맞는 필수 일정과 모집 마감일을 검사함.

        조건이 맞지 않으면 ValueError를 발생시키고,
        정상이라면 검증된 객체(self)를 반환함.
        """
        if self.recruit_mode == "regular":
            if not self.regular_days or self.regular_time is None:
                raise ValueError("정기 모임은 요일과 시간이 필요합니다.")

            if self.regular_start_date is None:
                raise ValueError("정기 모임 시작 날짜가 필요합니다.")

            start_day = WEEKDAYS[self.regular_start_date.weekday()]
            if start_day not in self.regular_days:
                raise ValueError("시작 날짜의 요일이 모임 요일에 포함되어야 합니다.")

            first_meeting = datetime.combine(
                self.regular_start_date,
                self.regular_time,
            )
            if self.deadline_at > first_meeting:
                raise ValueError("모집 마감은 첫 모임 시작 이전이어야 합니다.")

        if self.recruit_mode == "short":
            if self.meeting_start is None or self.meeting_end is None:
                raise ValueError("단기 모임은 시작과 종료 시간이 필요합니다.")

            if self.meeting_end <= self.meeting_start:
                raise ValueError("종료 시간은 시작 시간보다 늦어야 합니다.")

            if self.deadline_at > self.meeting_start:
                raise ValueError("모집 마감은 모임 시작 이전이어야 합니다.")

        return self

    @field_validator("regular_days")
    @classmethod
    def check_days(cls, days: list[str] | None) -> list[str] | None:
        """입력된 요일의 중복 여부와 허용 값을 검사함."""
        return validate_regular_days(days)


class RecruitUpdate(BaseModel):
    """모임 수정 요청 데이터. 전달된 필드만 변경할 수 있도록 모두 선택 값으로 둠."""

    title: str | None = None
    body: str | None = None
    recruit_mode: Literal["regular", "short"] | None = None
    capacity: int | None = Field(default=None, gt=0)
    regular_days: list[str] | None = None
    regular_time: time | None = None
    meeting_start: datetime | None = None
    meeting_end: datetime | None = None
    deadline_at: datetime | None = None
    place: str | None = None
    regular_start_date: date | None = None

    @field_validator("regular_days")
    @classmethod
    def check_days(cls, days: list[str] | None) -> list[str] | None:
        """생성 요청과 동일한 요일 규칙을 적용함."""
        return validate_regular_days(days)


class RecruitResponse(RecruitCreate):
    """모임 생성 응답 등에 사용할 수 있는 형태. 생성 필드와 검증 규칙을 상속함."""

    recruit_id: int
    post_id: int
    state: str
