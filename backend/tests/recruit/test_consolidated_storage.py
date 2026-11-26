"""042/043 신규 저장 경로의 회귀: 테스트 전용 SQLite 환경에서만 실행."""

from datetime import timedelta

import pytest
from backend.app.domain.recruit_program import PolicyError
from backend.app.models.recruit import Recruit
from backend.app.models.recruit_program import ProgramRecord
from backend.app.schemas.recruit import RecruitCreate, RecruitUpdate
from backend.app.schemas.recruit_program import ProgramCreate
from backend.app.services import recruit as legacy


@pytest.mark.parametrize("category,field,before,after", [
    ("sports", "sport_name", "러닝", "축구"),
    ("game", "game_name", "체스", "보드게임"),
    ("study", "study_topic", "Python", "SQL"),
    ("group_buy", "product_name", "책", "노트"),
])
def test_legacy_category_detail_is_stored_in_recruits_json(service, payload, category, field, before, after):
    info = RecruitCreate(
        title="모임", body="함께해요", recruit_mode="short", category=category,
        capacity=3, deadline_at=payload["starts_at"] - timedelta(hours=24),
        meeting_start=payload["starts_at"], meeting_end=payload["ends_at"],
        **{field: before},
    )
    db = service.repository.session
    recruit_id = legacy.create_recruit(db, info, 1)["recruit_id"]
    original = dict(db.get(Recruit, recruit_id).details)
    assert original[field] == before
    assert legacy.get_recruit(db, recruit_id)["detail"][field] == before
    legacy.update_recruit(db, recruit_id, RecruitUpdate(**{field: after}))
    db.expire_all()
    assert db.get(Recruit, recruit_id).details == {**original, field: after}
    assert legacy.get_recruit(db, recruit_id)["detail"][field] == after


def test_program_study_details_and_curriculum_stored_on_parent(service, payload):
    db = service.repository.session
    recruit_id = service.create(1, ProgramCreate(**payload))["recruit_id"]
    recruit = db.get(Recruit, recruit_id)
    assert recruit.details["study_topic"] == payload["study_topic"]
    program = db.get(ProgramRecord, recruit_id)
    assert program.meetup_curriculum_version is None
    assert service.repository.curriculum(recruit_id) == {"version": 1, "items": []}
    saved = service.repository.save_curriculum(recruit_id, 1, [{"name": "1주차"}])
    db.commit()
    db.expire_all()
    assert saved == {"version": 2, "items": [{"name": "1주차"}]}
    assert db.get(ProgramRecord, recruit_id).meetup_curriculum_items == [{"name": "1주차"}]
    assert service.repository.curriculum(recruit_id) == saved
    with pytest.raises(PolicyError):
        service.repository.save_curriculum(recruit_id, 1, [])


def test_absent_details_store_sql_null_not_json_null(service, payload):
    """호환 뷰의 `details IS NOT NULL` 의미 보존: Python None -> SQL NULL."""
    from sqlalchemy import text
    db = service.repository.session
    info = RecruitCreate(
        title="운동", body="운동합니다", recruit_mode="short", category="sports",
        capacity=3, deadline_at=payload["starts_at"] - timedelta(hours=24),
        meeting_start=payload["starts_at"], meeting_end=payload["ends_at"],
        sport_name="러닝",
    )
    recruit_id = legacy.create_recruit(db, info, 1)["recruit_id"]
    row = db.get(Recruit, recruit_id)
    row.details = None
    db.commit()
    assert db.execute(
        text("SELECT details IS NULL FROM recruits WHERE recruit_id=:rid"),
        {"rid": recruit_id},
    ).scalar_one() == 1
