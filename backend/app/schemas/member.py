"""회원가입 입력 스키마 및 닉네임 검증."""
from pydantic import BaseModel, ConfigDict, Field, field_validator

NICKNAME_MIN_LENGTH = 2
NICKNAME_MAX_LENGTH = 20
RESERVED_NICKNAMES = {
    "관리자", "운영자", "운영진", "익명", "탈퇴한사용자",
    "admin", "administrator", "playmate",
}


def normalize_nickname(value: str) -> str:
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


class MemberSignup(BaseModel):
    """Discord 인증 후 등록된 기수를 하나 선택하여 즉시 가입합니다."""

    model_config = ConfigDict(extra="forbid")

    nickname: str = Field(min_length=2, max_length=20)
    cohort_id: int = Field(gt=0, strict=True)

    @field_validator("nickname")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return normalize_nickname(value)
