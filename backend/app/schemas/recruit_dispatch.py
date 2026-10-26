"""기존 모임 생성과 신규 프로젝트/스터디 생성을 명시적으로 구분하는 요청 계약."""

from typing import Annotated, Union

from pydantic import Discriminator, Tag

from backend.app.schemas.recruit import RecruitCreate
from backend.app.schemas.recruit_program import ProgramCreate


def creation_kind(value):
    """신규 요청의 검증 실패가 기존 스키마의 extra 무시로 성공하는 것을 방지한다."""
    if isinstance(value, ProgramCreate):
        return "program"
    if isinstance(value, RecruitCreate):
        return "legacy"
    if isinstance(value, dict):
        new_fields = {
            "starts_at",
            "ends_at",
            "required_skill_ids",
            "creator_application",
            "study_type",
            "difficulty",
        }
        if value.get("category") == "project" or new_fields.intersection(value):
            return "program"
    return "legacy"


RecruitCreation = Annotated[
    Union[
        Annotated[ProgramCreate, Tag("program")],
        Annotated[RecruitCreate, Tag("legacy")],
    ],
    Discriminator(creation_kind),
]
