# Pydantic이란? React에서 FastAPI로 보내는 데이터를 검사하는 도구
# 예를 들어 모임 생성 시 제목은 문자열, 모집 인원은 숫자인지 검사

'''
하단의 파일들을 사용함
backend/app/
├── core/
│   └── database.py       ✅
├── models/
│   ├── member.py         ✅
│   ├── post.py           ✅
│   └── recruit.py        ✅
└── schemas/
    └── recruit.py        ← 지금 작성
'''


from datetime import datetime
from pydantic import BaseModel, Field


class RecruitCreate(BaseModel):
    title: str
    body: str
    recruit_mode: str
    category: str
    capacity: int = Field(gt=0)
    meeting_datetime: datetime | None = None
    place: str | None = None
    is_online: bool = False
    contact_method: str | None = None
    deadline_at: datetime | None = None

    sport_name: str | None = None
    game_name: str | None = None
    study_topic: str | None = None
    study_period: str | None = None
    study_method: str | None = None
    product_name: str | None = None
    purchase_url: str | None = None
    estimated_price_per_person: float | None = None
    pickup_method: str | None = None


class RecruitUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    capacity: int | None = Field(default=None, gt=0)
    meeting_datetime: datetime | None = None
    place: str | None = None
    deadline_at: datetime | None = None


class RecruitResponse(RecruitCreate):
    recruit_id: int
    post_id: int
    state: str