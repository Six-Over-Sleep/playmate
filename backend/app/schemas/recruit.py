"""모임 생성·수정 요청과 응답에 사용하는 Pydantic 스키마."""

# 날짜, 날짜와 시간, 시간만을 각각 표현하는 자료형
from datetime import date, datetime, time
# Literal : 지정된 값만 입력받도록 제한하는 타입
from typing import Literal

# BaseModel : 요청/응답 데이터 구조 정의
# Field : 필드별 입력 조건 설정
# field_validator / model_validator : 필드 또는 모델 전체를 검증
from pydantic import BaseModel, Field, field_validator, model_validator


# WEEKDAYS : 정기 모임에서 선택할 수 있는 요일 목록
# datetime.weekday()의 반환값(월요일=0 ~ 일요일=6)과 순서를 맞춤
WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")


def validate_regular_days(days: list[str] | None) -> list[str] | None:
    """요일 목록을 검사하고 그대로 반환함. 비어 있거나 중복·잘못된 요일이면 오류 발생."""
    # 입력값이 None이면 검증 없이 반환함
    if days is None:
        return days

    # 빈 목록을 허용하지 않으며 set()으로 중복된 요일이 있는지 확인함
    if not days or len(days) != len(set(days)):
        raise ValueError("요일은 중복 없이 1개 이상 선택해야 합니다.")

    # 입력된 모든 요일이 WEEKDAYS에 포함되어야 함
    if any(day not in WEEKDAYS for day in days):
        raise ValueError("요일은 월~일 중에서 선택해야 합니다.")

    return days


# 모임 생성 요청 데이터를 검증하는 모델
class RecruitCreate(BaseModel):
    """모임 생성 요청 데이터와 일정 검증 규칙."""

    # title : 모임 게시글 제목
    # body : 모임 게시글 본문
    # recruit_mode : 모임 방식 (regular : 정기 / short : 단기)
    # category : 모임 카테고리 (운동, 게임, 스터디, 공동구매 등)
    # capacity : 최대 모집 인원 (0보다 커야 함)
    # deadline_at : 모집 마감 일시
    title: str
    body: str
    recruit_mode: Literal["regular", "short"]
    category: str
    capacity: int = Field(gt=0)
    deadline_at: datetime

    # regular_days : 정기 모임 요일 목록 (예: ["월", "수"])
    # regular_time : 정기 모임 진행 시간
    # meeting_start : 단기 모임 시작 일시
    # meeting_end : 단기 모임 종료 일시
    # str | None, time | None 등은 값이 없을 때 None을 허용함
    regular_days: list[str] | None = None
    regular_time: time | None = None
    meeting_start: datetime | None = None
    meeting_end: datetime | None = None

    # place : 모임 장소
    # is_online : 온라인 여부 (True : 온라인 / False : 오프라인)
    # contact_method : 참여자 간 연락 방법
    place: str | None = None
    is_online: bool = False
    contact_method: str | None = None

    # 카테고리별 상세 정보 : 해당 카테고리에서 사용하는 값만 입력받음
    # sport_name : 운동 종목
    # game_name : 게임 이름
    # study_topic : 스터디 주제
    # study_period : 스터디 기간
    # study_method : 스터디 진행 방식
    # product_name : 공동구매 상품 이름
    # purchase_url : 상품 구매 주소
    # estimated_price_per_person : 1인당 예상 금액
    # pickup_method : 공동구매 상품 수령 방식
    # regular_start_date : 정기 모임 시작 날짜
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

    # @model_validator(mode="after") : 개별 필드 검증이 끝난 뒤 전체 요청 데이터의 관계를 검사함
    @model_validator(mode="after")
    def check_schedule(self):
        """모임 방식에 맞는 필수 일정과 모집 마감일을 검사함.

        조건이 맞지 않으면 ValueError를 발생시키고,
        정상이라면 검증된 객체(self)를 반환함.
        """
        # 정기 모임은 요일, 시간, 시작 날짜가 모두 필요함
        if self.recruit_mode == "regular":
            if not self.regular_days or self.regular_time is None:
                raise ValueError("정기 모임은 요일과 시간이 필요합니다.")

            if self.regular_start_date is None:
                raise ValueError("정기 모임 시작 날짜가 필요합니다.")

            # 시작 날짜의 요일이 선택한 정기 모임 요일에 포함되는지 확인함
            start_day = WEEKDAYS[self.regular_start_date.weekday()]
            if start_day not in self.regular_days:
                raise ValueError("시작 날짜의 요일이 모임 요일에 포함되어야 합니다.")

            # date와 time을 하나의 datetime으로 합쳐 첫 모임 시작 일시를 만듦
            first_meeting = datetime.combine(
                self.regular_start_date,
                self.regular_time,
            )
            # 모집 마감일이 첫 모임 시작일보다 늦으면 오류 발생
            if self.deadline_at > first_meeting:
                raise ValueError("모집 마감은 첫 모임 시작 이전이어야 합니다.")

        # 단기 모임은 시작·종료 일시를 모두 입력해야 함
        if self.recruit_mode == "short":
            if self.meeting_start is None or self.meeting_end is None:
                raise ValueError("단기 모임은 시작과 종료 시간이 필요합니다.")

            # 종료 일시가 시작 일시보다 늦어야 함
            if self.meeting_end <= self.meeting_start:
                raise ValueError("종료 시간은 시작 시간보다 늦어야 합니다.")

            # 모집 마감일이 모임 시작일보다 늦으면 오류 발생
            if self.deadline_at > self.meeting_start:
                raise ValueError("모집 마감은 모임 시작 이전이어야 합니다.")

        # 모든 검증을 통과한 요청 객체 반환
        return self

    # @field_validator("regular_days") : 요일 목록에만 별도 검증 적용
    @field_validator("regular_days")
    @classmethod
    def check_days(cls, days: list[str] | None) -> list[str] | None:
        """입력된 요일의 중복 여부와 허용 값을 검사함."""
        return validate_regular_days(days)


# 모임 수정 요청 데이터를 검증하는 모델
class RecruitUpdate(BaseModel):
    """모임 수정 요청 데이터. 전달된 필드만 변경할 수 있도록 모두 선택 값으로 둠."""

    # 수정할 필드만 전달할 수 있도록 기본값을 None으로 설정함
    # title / body : 게시글 제목과 본문
    # recruit_mode : 모임 방식 (정기 / 단기)
    # capacity : 최대 모집 인원 (전달한 경우 0보다 커야 함)
    title: str | None = None
    body: str | None = None
    recruit_mode: Literal["regular", "short"] | None = None
    capacity: int | None = Field(default=None, gt=0)

    # regular_days / regular_time : 정기 모임 요일과 시간
    # meeting_start / meeting_end : 단기 모임 시작·종료 일시
    # deadline_at : 모집 마감 일시
    # place : 모임 장소
    # regular_start_date : 정기 모임 시작 날짜
    regular_days: list[str] | None = None
    regular_time: time | None = None
    meeting_start: datetime | None = None
    meeting_end: datetime | None = None
    deadline_at: datetime | None = None
    place: str | None = None
    regular_start_date: date | None = None

    # 수정 요청에서 regular_days가 전달되면 생성 요청과 동일한 검증을 적용함
    @field_validator("regular_days")
    @classmethod
    def check_days(cls, days: list[str] | None) -> list[str] | None:
        """생성 요청과 동일한 요일 규칙을 적용함."""
        return validate_regular_days(days)


def validate_comment_body(body: str) -> str:
    """댓글 본문의 앞뒤 공백을 제거하고, 공백만 있으면 오류를 발생시킴."""
    body = body.strip()
    if not body:
        raise ValueError("댓글 내용은 공백일 수 없습니다.")
    return body


class RecruitCommentCreate(BaseModel):
    """모임 댓글 작성 요청. parent_comment_id가 있으면 그 댓글의 대댓글로 저장함."""

    body: str = Field(min_length=1, max_length=2000)
    parent_comment_id: int | None = None

    @field_validator("body")
    @classmethod
    def check_body(cls, body: str) -> str:
        return validate_comment_body(body)


class RecruitCommentUpdate(BaseModel):
    """모임 댓글 수정 요청. 본문만 바꿀 수 있고 부모 댓글은 바꿀 수 없음."""

    body: str = Field(min_length=1, max_length=2000)

    @field_validator("body")
    @classmethod
    def check_body(cls, body: str) -> str:
        return validate_comment_body(body)


# 모임 생성 결과를 반환할 때 사용하는 응답 모델
class RecruitResponse(RecruitCreate):
    """모임 생성 응답 등에 사용할 수 있는 형태. 생성 필드와 검증 규칙을 상속함."""

    # RecruitCreate의 필드와 검증 규칙을 상속함
    # recruit_id : 생성된 모임 고유 번호
    # post_id : 연결된 게시글 고유 번호
    # state : 모임 모집 상태
    recruit_id: int
    post_id: int
    state: str
