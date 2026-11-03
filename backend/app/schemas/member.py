# 회원가입 요청 데이터와 입력값 검증 규칙을 정의하는 Schema
from typing import Literal
from pydantic import BaseModel, Field, field_validator


# 닉네임 공통 정책 (회원가입·마이페이지 변경에 동일하게 적용)
NICKNAME_MIN_LENGTH = 2
NICKNAME_MAX_LENGTH = 20

# 운영자·시스템 표시 문구로 오인될 수 있는 닉네임 (공백 제거·소문자 기준으로 비교)
RESERVED_NICKNAMES = {
    "관리자",
    "운영자",
    "운영진",
    "익명",
    "탈퇴한사용자",
    "admin",
    "administrator",
    "playmate",
}


def normalize_nickname(value: str) -> str:
    """앞뒤 공백을 제거하고 길이·예약어 정책을 검사한 닉네임을 반환함.

    중복 여부는 DB 고유 제약(uq_members_nickname_normalized)이 판단함.
    """
    value = value.strip()
    if not value:
        raise ValueError("닉네임을 입력해주세요.")
    if not NICKNAME_MIN_LENGTH <= len(value) <= NICKNAME_MAX_LENGTH:
        raise ValueError(
            f"닉네임은 {NICKNAME_MIN_LENGTH}자 이상 {NICKNAME_MAX_LENGTH}자 이하로 입력해주세요."
        )
    if "".join(value.split()).lower() in RESERVED_NICKNAMES:
        raise ValueError("사용할 수 없는 닉네임입니다.")
    return value


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
        # 공백 제거 후 길이·예약어 공통 정책을 적용하고 정리된 닉네임을 반환함
        return normalize_nickname(value)
