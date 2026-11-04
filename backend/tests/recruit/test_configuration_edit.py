"""다른 회원 신청 전·모집 마감 전의 모임 형태 변경 계약을 검증한다."""

from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from backend.app.domain.recruit_program import PolicyError
from backend.app.models.recruit import Recruit
from backend.app.schemas.recruit_program import (
    ProgramApplication, ProgramCreate, ProgramEdit,
)
from backend.app.schemas.recruit import RecruitCreate
from backend.app.services import recruit as legacy
from backend.app.services.recruit_dispatch_service import RecruitDispatchService
from backend.tests.recruit.test_runtime_api import runtime, json_payload


@pytest.fixture
def dispatch(service):
    from backend.app.models.recruit import (
        RecruitSportsDetail, RecruitGameDetail, RecruitGroupBuyDetail,
    )
    for model in (RecruitSportsDetail, RecruitGameDetail, RecruitGroupBuyDetail):
        model.__table__.create(service.repository.session.get_bind(), checkfirst=True)
    return RecruitDispatchService(
        service, True, lambda: 1, lambda: 1, lambda: 1, lambda: 1,
    )


def category_payload(payload, category):
    values = {**payload, "category": category, "recruit_mode": "short"}
    if category == "project":
        for key in ("study_type", "difficulty", "study_topic"):
            values.pop(key)
        return ProgramCreate(
            **values, required_skill_ids=[101],
            creator_application=ProgramApplication(skill_ids=[101]),
        ).model_dump()
    if category == "study":
        return ProgramCreate(**values).model_dump()
    return RecruitCreate(
        title=payload["title"], body=payload["body"], category=category,
        capacity=2, recruit_mode="short",
        deadline_at=payload["starts_at"] - timedelta(hours=24),
        meeting_start=payload["starts_at"], meeting_end=payload["ends_at"],
        sport_name="러닝", game_name="체스", product_name="교재", pickup_method="배송",
    ).model_dump()


@pytest.mark.parametrize("source,target", [
    (source, target)
    for source in ("project", "study", "sports", "game", "group_buy")
    for target in ("project", "study", "sports", "game", "group_buy")
    if source != target
])
def test_category_conversion_preserves_post_and_selected_category(
    service, dispatch, payload, source, target,
):
    source_data = category_payload(payload, source)
    if source in {"project", "study"}:
        created = service.create(1, ProgramCreate(**source_data))
    else:
        created = legacy.create_recruit(
            service.repository.session, RecruitCreate(**source_data), 1
        )
    recruit_id = created["recruit_id"]
    post_id = service.repository.basic_detail(recruit_id)["post_id"]
    dispatch.update(recruit_id, category_payload(payload, target))
    service.repository.session.expire_all()
    after = dispatch.detail(recruit_id)
    assert after["category"] == target
    assert service.repository.basic_detail(recruit_id)["post_id"] == post_id
    assert after["recruit_id"] == recruit_id
    assert service.repository.is_program(recruit_id) == (target in {"project", "study"})
    if target == "project":
        assert after["my_application"]["skill_ids"] == [101]
    else:
        assert after.get("required_skill_ids", []) == []


def regular_fields(start):
    local = start.astimezone(ZoneInfo("Asia/Seoul"))
    return {
        "recruit_mode": "regular",
        "regular_days": [["월", "화", "수", "목", "금", "토", "일"][local.weekday()]],
        "regular_time": local.time().replace(tzinfo=None),
        "regular_start_date": local.date(),
    }


def test_mode_roundtrip_preserves_identity_and_clears_unused_schedule(service, payload):
    recruit_id = service.create(1, ProgramCreate(**payload))["recruit_id"]
    before = service.detail(recruit_id, 1)
    regular = service.edit(
        recruit_id, 1, ProgramEdit(**regular_fields(payload["starts_at"]))
    )
    assert regular["recruit_mode"] == "regular"
    assert regular["regular_days"]
    short = service.edit(recruit_id, 1, ProgramEdit(recruit_mode="short"))
    assert short["recruit_mode"] == "short"
    assert short["regular_days"] is None
    assert short["regular_time"] is None
    assert short["regular_start_date"] is None
    assert short["meeting_start"] == before["starts_at"]
    assert short["meeting_end"] == before["ends_at"]
    assert short["post_id"] == before["post_id"]
    assert short["category"] == "study"
    row = service.repository.session.get(Recruit, recruit_id)
    assert row.regular_days is None
    assert row.meeting_start is not None


@pytest.mark.parametrize("condition", ["other", "canceled", "deadline", "non_owner"])
def test_configuration_rejects_ineligible_changes(service, payload, condition):
    recruit_id = service.create(1, ProgramCreate(**payload))["recruit_id"]
    actor = 1
    if condition in {"other", "canceled"}:
        service.apply(recruit_id, 2, ProgramApplication())
        if condition == "canceled":
            service.cancel_application(recruit_id, 2)
    elif condition == "deadline":
        service.test_clock[0] = payload["starts_at"] - timedelta(hours=24)
    else:
        actor = 2
    assert not service.detail(recruit_id, actor)["permissions"]["can_edit_configuration"]
    with pytest.raises(PolicyError):
        service.edit(recruit_id, actor, ProgramEdit(**regular_fields(payload["starts_at"])))
    assert service.detail(recruit_id, 1)["recruit_mode"] == "short"


def test_invalid_regular_schedule_rolls_back(service, payload):
    recruit_id = service.create(1, ProgramCreate(**payload))["recruit_id"]
    with pytest.raises(ValidationError):
        service.edit(recruit_id, 1, ProgramEdit(recruit_mode="regular"))
    assert service.detail(recruit_id, 1)["recruit_mode"] == "short"


@pytest.mark.parametrize("source", ["study", "sports"])
@pytest.mark.parametrize("condition", ["history", "deadline", "non_owner", "invalid"])
def test_category_change_rechecks_permission_and_preserves_failed_source(
    service, dispatch, payload, source, condition,
):
    from backend.app.models.recruit import RecruitMember
    from backend.app.services.recruit_configuration_service import RecruitConfigurationService

    source_data = category_payload(payload, source)
    if source == "study":
        recruit_id = service.create(1, ProgramCreate(**source_data))["recruit_id"]
    else:
        recruit_id = legacy.create_recruit(
            service.repository.session, RecruitCreate(**source_data), 1
        )["recruit_id"]
    actor = 1
    target = category_payload(payload, "project")
    if condition == "history":
        if source == "study":
            service.apply(recruit_id, 2, ProgramApplication())
            service.cancel_application(recruit_id, 2)
        else:
            service.repository.session.add(RecruitMember(
                recruit_id=recruit_id, member_id=2, status="CANCELED", role="MEMBER",
            ))
            service.repository.session.commit()
    elif condition == "deadline":
        service.test_clock[0] = payload["starts_at"] - timedelta(hours=24)
    elif condition == "non_owner":
        actor = 2
    else:
        target["required_skill_ids"] = [999]
    with pytest.raises(PolicyError):
        RecruitConfigurationService(service).change(recruit_id, actor, target)
    service.repository.session.rollback()
    assert dispatch.detail(recruit_id)["category"] == source


@pytest.mark.parametrize("source,target", [
    (source, target)
    for source in ("project", "study", "sports", "game", "group_buy")
    for target in ("project", "study", "sports", "game", "group_buy")
    if source != target
])
@pytest.mark.parametrize("mode", ["short", "regular"])
def test_main_api_category_conversion(runtime, payload, source, target, mode):
    """프론트가 사용하는 실제 main 경로의 요청 검증·분기·직렬화까지 검사한다."""
    def request_payload(category):
        data = category_payload(payload, category)
        if mode == "regular" and category != "group_buy":
            data.update(regular_fields(payload["starts_at"]))
            data.update(meeting_start=None, meeting_end=None)
        return json_payload(data)

    created = runtime.request(
        "POST", "/api/recruits", member=1, legacy_login=True,
        json=request_payload(source),
    )
    assert created.status_code == 201, created.text
    recruit_id = created.json()["recruit_id"]
    updated = runtime.request(
        "PATCH", f"/api/recruits/{recruit_id}", member=1, legacy_login=True,
        json=request_payload(target),
    )
    assert updated.status_code == 200, updated.text
    detail = runtime.request("GET", f"/api/recruits/{recruit_id}", member=1)
    assert detail.status_code == 200, detail.text
    assert detail.json()["category"] == target
    assert detail.json()["recruit_mode"] == (
        "short" if target == "group_buy" else mode
    )


def test_legacy_join_reuses_dispatch_lock(runtime, service, payload, monkeypatch):
    """종류 전환 경합 검사에서 확보한 잠금을 참여 서비스가 다시 조회하지 않는다."""
    from backend.app.repositories import recruit as legacy_repository

    created = runtime.request(
        "POST", "/api/recruits", member=1, legacy_login=True,
        json=json_payload(category_payload(payload, "sports")),
    )
    recruit_id = created.json()["recruit_id"]
    def unexpected_lock(*args, **kwargs):
        pytest.fail("이미 잠근 모임을 참여 서비스에서 중복 조회했습니다.")
    monkeypatch.setattr(legacy_repository, "get_recruit_for_update", unexpected_lock)
    joined = runtime.request("POST", f"/api/recruits/{recruit_id}/join", member=2)
    assert joined.status_code == 200, joined.text


def test_admin_conversion_keeps_program_creator_out_of_participant_count(
    service, dispatch, payload,
):
    """관리자 생성 여부를 전환 뒤에도 서버 권한으로 판정하며 중복 참여를 만들지 않는다."""
    from backend.app.services.recruit_configuration_service import RecruitConfigurationService

    recruit_id = service.create(9, ProgramCreate(**payload))["recruit_id"]
    for category in ("project", "sports", "game", "group_buy", "study"):
        data = category_payload(payload, category)
        data.pop("creator_application", None)
        RecruitConfigurationService(service).change(recruit_id, 9, data)
        if category in {"project", "study"}:
            detail = service.detail(recruit_id, 9)
            assert detail["creator_type"] == "ADMIN"
            assert detail["participant_count"] == 0
            assert detail["my_application"] is None
