from datetime import datetime, date, time
from typing import Literal
from pydantic import BaseModel, Field, model_validator, field_validator

class RecruitCreate(BaseModel):
    title: str
    body: str
    recruit_mode: Literal["regular", "short"]
    category: str
    capacity: int = Field(gt=0)
    deadline_at: datetime

    regular_days: list[str] | None = None
    regular_time: time | None = None
    meeting_start: datetime | None = None
    meeting_end: datetime | None = None

    place: str | None = None
    is_online: bool = False
    contact_method: str | None = None

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
        if self.recruit_mode == "regular":
            if not self.regular_days or self.regular_time is None:
                raise ValueError("정기 모임은 요일과 시간이 필요합니다.")

            if self.regular_start_date is None:
                raise ValueError("정기 모임 시작 날짜가 필요합니다.")

            weekdays = ["월", "화", "수", "목", "금", "토", "일"]
            start_day = weekdays[self.regular_start_date.weekday()]

            if start_day not in self.regular_days:
                raise ValueError("시작 날짜의 요일이 모임 요일에 포함되어야 합니다.")

            first_meeting = datetime.combine(
                self.regular_start_date, self.regular_time
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
    def check_days(cls, days):
        if days is not None:
            valid_days = ["월", "화", "수", "목", "금", "토", "일"]

            if not days or len(days) != len(set(days)):
                raise ValueError("요일은 중복 없이 1개 이상 선택해야 합니다.")

            if any(day not in valid_days for day in days):
                raise ValueError("요일은 월~일 중에서 선택해야 합니다.")

        return days


class RecruitUpdate(BaseModel):
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
    def check_days(cls, days):
        if days is not None:
            valid_days = ["월", "화", "수", "목", "금", "토", "일"]
            if not days or len(days) != len(set(days)):
                raise ValueError("요일은 중복 없이 1개 이상 선택해야 합니다.")
            if any(day not in valid_days for day in days):
                raise ValueError("요일은 월~일 중에서 선택해야 합니다.")
        return days


class RecruitResponse(RecruitCreate):
    recruit_id: int
    post_id: int
    state: str
