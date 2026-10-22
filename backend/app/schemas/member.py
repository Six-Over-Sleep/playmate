# 회원가입 요청 데이터와 입력값 검증 규칙을 정의하는 Schema
from typing import Literal
from pydantic import BaseModel, Field, field_validator


# Discord 인증 후 추가 회원가입에 필요한 정보를 검증하는 모델
class MemberSignup(BaseModel):

    # nickname : PLAYMATE에서 사용할 닉네임
    # Field() : 입력값의 길이 및 설명을 설정함
    # min_length / max_length : 2자 이상, 20자 이하로 제한함
    nickname: str = Field(
        min_length=2,
        max_length=20,
        description="PlayMate에서 사용할 닉네임"
    )

    # cohort : 부트캠프 수강 기수
    # ge=1 : 1 이상의 정수만 허용함
    cohort: int = Field(
        ge=1,
        description="수강 기수"
    )

    # track : 수강 트랙
    # Literal : 아래에 지정된 네 가지 문자열 중 하나만 허용함
    track: Literal[
        "family-ai",
        "multi-agent",
        "data-engineering",
        "data-ml",
    ]

    # field_validator("nickname") : 닉네임 값에 사용자 정의 검증을 적용함
    # @classmethod : Pydantic 검증 메서드를 클래스 메서드로 정의함
    @field_validator("nickname")
    @classmethod
    def validate_text(cls, value: str) -> str:
        # strip() : 닉네임 앞뒤의 공백을 제거함
        value = value.strip()

        # 공백 제거 후 값이 비어 있으면 오류 발생
        if not value:
            raise ValueError("빈 문자열은 입력할 수 없습니다.")

        # 검증 및 공백 제거가 완료된 닉네임을 반환함
        return value
