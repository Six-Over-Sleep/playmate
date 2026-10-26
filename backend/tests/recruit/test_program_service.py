from datetime import timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from backend.app.domain.recruit_program import PolicyError
from backend.app.models.recruit_program import EligibilityRecord, OutboxRecord
from backend.app.schemas.recruit_program import (
    ActivityCreate,
    CurriculumUpdate,
    ExtensionRequest,
    ProgramApplication,
    ProgramCreate,
    ProgramEdit,
)


def create(service, payload, member=1):
    return service.create(member, ProgramCreate(**payload))["recruit_id"]


def test_round_trip_waiting_snapshot_and_no_xp_on_apply(service, payload):
    recruit = create(service, payload)
    result = service.apply(
        recruit, 2, ProgramApplication(direct_input={"experience": "원본"})
    )
    assert result["application_status"] == "ACCEPTED"
    assert (
        service.apply(recruit, 3, ProgramApplication())["application_status"]
        == "WAITING"
    )
    service.cancel_application(recruit, 2)
    assert (
        service.detail(recruit, 3)["my_application"]["application_status"] == "ACCEPTED"
    )
    assert (
        service.repository.session.scalar(
            select(func.count()).select_from(OutboxRecord)
        )
        == 0
    )


@pytest.mark.parametrize("value", [["career-1"], None])
def test_unconnected_career_is_rejected(value):
    with pytest.raises(ValidationError):
        ProgramApplication(career_item_ids=value)


def test_career_omitted_or_empty_allowed_and_invalid_link_rejected():
    assert ProgramApplication().career_item_ids == []
    assert ProgramApplication(career_item_ids=[]).career_item_ids == []
    with pytest.raises(ValidationError):
        ProgramApplication(direct_input={"portfolio_url": "javascript:alert(1)"})


def test_admin_capacity_and_no_auto_join(service, payload):
    payload["capacity"] = 5
    with pytest.raises(PolicyError):
        create(service, payload, 9)
    payload["capacity"] = 4
    recruit = create(service, payload, 9)
    assert service.detail(recruit, 9)["participant_count"] == 0


def test_core_edit_before_other_application_then_lock(service, payload):
    recruit = create(service, payload)
    service.edit(recruit, 1, ProgramEdit(capacity=3))
    assert service.detail(recruit, 1)["capacity"] == 3
    service.apply(recruit, 2, ProgramApplication())
    with pytest.raises(PolicyError):
        service.edit(recruit, 1, ProgramEdit(capacity=4))
    with pytest.raises(PolicyError):
        service.edit(recruit, 2, ProgramEdit(title="탈취"))
    service.edit(recruit, 1, ProgramEdit(title="변경"))
    assert service.detail(recruit, 1)["title"] == "변경"


def test_curriculum_owner_and_stale_version(service, payload):
    recruit = create(service, payload)
    update = CurriculumUpdate(
        version=1, items=[{"week": 1, "title": "시작", "content": "학습"}]
    )
    with pytest.raises(PolicyError) as error:
        service.curriculum(recruit, 2, update)
    assert error.value.status == 403
    assert service.curriculum(recruit, 1, update)["version"] == 2
    with pytest.raises(PolicyError) as error:
        service.curriculum(recruit, 1, update)
    assert error.value.status == 409


def test_restricted_member_existing_waiter_still_promotes(service, payload):
    recruit = create(service, payload)
    service.apply(recruit, 2, ProgramApplication())
    service.apply(recruit, 3, ProgramApplication())
    service.repository.session.add(EligibilityRecord(member_id=3, withdrawal_count=3))
    service.repository.session.commit()
    service.cancel_application(recruit, 2)
    assert (
        service.detail(recruit, 3)["my_application"]["application_status"] == "ACCEPTED"
    )
    other = create(service, payload, 4)
    with pytest.raises(PolicyError) as error:
        service.apply(other, 3, ProgramApplication())
    assert error.value.status == 403


def test_departure_exactly_once_and_no_count_for_waiting(service, payload):
    recruit = create(service, payload)
    service.apply(recruit, 2, ProgramApplication())
    service.apply(recruit, 3, ProgramApplication())
    service.test_clock[0] = payload["starts_at"]
    service.tick()
    service.cancel_application(recruit, 3)
    assert service.repository.session.get(EligibilityRecord, 3) is None
    service.cancel_application(recruit, 2)
    assert service.repository.session.get(EligibilityRecord, 2).withdrawal_count == 1
    with pytest.raises(PolicyError):
        service.cancel_application(recruit, 2)
    assert service.repository.session.get(EligibilityRecord, 2).withdrawal_count == 1


def test_extension_retry_same_result_and_different_body_rejected(service, payload):
    payload.update(
        category="project",
        required_skill_ids=[101, 102],
        capacity=4,
        creator_application={"skill_ids": [101]},
    )
    recruit = create(service, payload)
    service.test_clock[0] = payload["starts_at"] - timedelta(hours=24)
    request = ExtensionRequest(
        starts_at=payload["starts_at"] + timedelta(days=2),
        ends_at=payload["ends_at"] + timedelta(days=2),
        schedule_version=1,
        request_key="extension-1",
    )
    result = service.decide(recruit, 1, "extend", request)
    assert result == service.decide(recruit, 1, "extend", request)
    with pytest.raises(PolicyError):
        service.decide(
            recruit,
            1,
            "extend",
            request.model_copy(update={"ends_at": request.ends_at + timedelta(days=1)}),
        )
    assert service.detail(recruit, 1)["extension_count"] == 1


def test_activity_does_not_recognize_whole_team_or_award_xp(service, payload):
    recruit = create(service, payload)
    service.apply(recruit, 2, ProgramApplication())
    service.test_clock[0] = payload["starts_at"]
    service.tick()
    data = ActivityCreate(
        activity_type="WEEKLY_CHECK", week=1, title="인증", body="학습 완료"
    )
    service.activities(recruit, 1, data)
    assert len(service.activities(recruit, 2)) == 1
    assert not service.repository.session.scalars(
        select(OutboxRecord).where(OutboxRecord.kind == "XP_REQUEST")
    ).all()


def test_three_departures_block_new_auto_join_but_keep_existing_membership(
    service, payload
):
    already = create(service, payload, 4)
    service.apply(already, 2, ProgramApplication())
    groups = []
    for _ in range(3):
        recruit = create(service, payload)
        service.apply(recruit, 2, ProgramApplication())
        groups.append(recruit)
    service.test_clock[0] = payload["starts_at"]
    service.tick()
    for recruit in groups:
        service.cancel_application(recruit, 2)
    assert service.repository.session.get(EligibilityRecord, 2).withdrawal_count == 3
    assert (
        service.detail(already, 2)["my_application"]["application_status"] == "ACCEPTED"
    )
    future = {
        **payload,
        "starts_at": payload["starts_at"] + timedelta(days=4),
        "ends_at": payload["ends_at"] + timedelta(days=4),
    }
    with pytest.raises(PolicyError) as error:
        create(service, future, 2)
    assert error.value.status == 403


def test_failed_create_rolls_back_post_recruit_and_application(
    service, payload, monkeypatch
):
    from backend.app.models.post import Post
    from backend.app.models.recruit import Recruit
    from backend.app.models.recruit_program import ApplicationRecord

    def fail(*args):
        raise RuntimeError("저장 단계 실패")

    monkeypatch.setattr(service.repository, "set_metadata", fail)
    with pytest.raises(RuntimeError):
        create(service, payload)
    for model in [Post, Recruit, ApplicationRecord]:
        assert (
            service.repository.session.scalar(select(func.count()).select_from(model))
            == 0
        )


def test_deadline_edit_cannot_bypass_formal_extension(service, payload):
    payload.update(
        category="project",
        required_skill_ids=[101, 102],
        capacity=4,
        creator_application={"skill_ids": [101]},
    )
    recruit = create(service, payload)
    service.test_clock[0] = payload["starts_at"] - timedelta(hours=24)
    proposed = payload["starts_at"] + timedelta(days=2)
    with pytest.raises(PolicyError) as error:
        service.edit(recruit, 1, ProgramEdit(starts_at=proposed))
    assert error.value.status == 409
    request = ExtensionRequest(
        starts_at=proposed,
        ends_at=payload["ends_at"],
        schedule_version=1,
        request_key="audit-extension",
    )
    service.decide(recruit, 1, "extend", request)
    with pytest.raises(PolicyError) as error:
        service.edit(recruit, 1, ProgramEdit(starts_at=proposed + timedelta(days=2)))
    assert error.value.status == 409


def test_detail_exposes_own_restriction_and_extension_window(service, payload):
    recruit = create(service, payload)
    service.repository.session.add(
        EligibilityRecord(
            member_id=2, withdrawal_count=3, restricted_at=service.clock()
        )
    )
    service.repository.session.commit()
    own = service.detail(recruit, 2)
    other = service.detail(recruit, 1)
    assert own["my_eligibility"]["reason_code"] == "THREE_WITHDRAWALS"
    assert own["my_eligibility"]["withdrawal_count"] == 3
    assert other["my_eligibility"]["withdrawal_count"] == 0
    assert own["extension_window"]["remaining_extensions"] == 2
    assert own["exception_start"]["selected"] is False


def test_output_requires_explicit_submission_stage():
    with pytest.raises(ValidationError):
        ActivityCreate(activity_type="OUTPUT", title="결과물", body="기록")


def test_user_curriculum_does_not_require_unconfirmed_admin_policy(service, payload):
    from backend.app.services.recruit_program_service import ProgramService

    recruit = create(service, payload)
    default = ProgramService(service.repository, clock=service.clock)
    assert default.detail(recruit, 1)["permissions"]["can_edit_curriculum"] is True
    assert (
        default.curriculum(recruit, 1, CurriculumUpdate(version=1, items=[]))["version"]
        == 2
    )
    admin_recruit = create(service, payload, 9)
    with pytest.raises(PolicyError) as error:
        default.curriculum(admin_recruit, 9, CurriculumUpdate(version=1, items=[]))
    assert error.value.status == 403
