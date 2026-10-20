from typing import Literal
from pydantic import BaseModel, Field, field_validator


# 회원가입 요청 데이터
class MemberSignup(BaseModel):

    # 1. 닉네임
    nickname: str = Field(
        min_length=2,
        max_length=20,
        description="PlayMate에서 사용할 닉네임"
    )

    # 2. 기수
    cohort: int = Field(
        ge=1,
        description="수강 기수"
    )

    # 3. 수강 트랙
    track: Literal[
        "family-ai",
        "multi-agent",
        "data-engineering",
        "data-ml",
    ]

    # 공백 문자열 검사 및 제거
    @field_validator("nickname")
    @classmethod
    def validate_text(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("빈 문자열은 입력할 수 없습니다.")

        return value
