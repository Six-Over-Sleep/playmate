"""관리자 전용 모임 XP 검토 요청. 보상액은 클라이언트에서 받지 않는다."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

RewardType = Literal[
    'PARTICIPATION', 'STUDY_WEEKLY', 'PROJECT_INTERIM',
    'STUDY_COMPLETE', 'PROJECT_COMPLETE', 'REVIEW', 'PROJECT_LEADER',
]


class MeetupXPApprove(BaseModel):
    model_config = ConfigDict(extra='forbid')
    activity_id: int = Field(gt=0)
    member_id: int = Field(gt=0)
    reward_type: RewardType
    week: int | None = Field(default=None, gt=0)


class MeetupXPRevoke(BaseModel):
    model_config = ConfigDict(extra='forbid')
    member_id: int = Field(gt=0)
    reward_type: RewardType
    reason: str = Field(min_length=1, max_length=500)
    week: int | None = Field(default=None, gt=0)
