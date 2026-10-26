from datetime import datetime, timedelta, timezone

import pytest

from backend.app.domain.recruit_program import PolicyError, Program


def program(category="study", capacity=2, skills=None, creator_type="USER"):
    start = datetime(2026, 11, 10, 10, tzinfo=timezone.utc)
    return Program(
        category,
        1,
        creator_type,
        capacity,
        start,
        start + timedelta(days=14),
        skills or [],
    )


def test_study_waiter_promotes_in_order_without_newcomer_overtaking():
    group = program()
    now = group.starts_at - timedelta(days=3)
    for member in range(1, 6):
        group.apply(member, now)
    group.cancel_application(3, now)
    group.cancel_application(2, now)
    assert [item.member_id for item in group.accepted()] == [1, 4]
    assert [item.member_id for item in group.waiting()] == [5]
    assert group.apply(6, now).status == "WAITING"


def test_cutoff_blocks_promotion_and_new_application():
    group = program()
    now = group.deadline_at - timedelta(seconds=1)
    for member in [1, 2, 3]:
        group.apply(member, now)
    group.cancel_application(2, group.deadline_at)
    assert group.waiting()[0].member_id == 3
    with pytest.raises(PolicyError):
        group.apply(4, group.deadline_at)
    group.tick(group.deadline_at)
    assert group.lifecycle_status == "CANCELED"


def test_project_reserves_last_skill_slot_and_rechecks_waiters():
    group = program("project", 3, [101, 102])
    now = group.starts_at - timedelta(days=3)
    group.apply(1, now, [101], creator=True)
    group.apply(2, now, [101])
    assert group.apply(3, now, [101]).status == "WAITING"
    assert group.apply(4, now, [102]).status == "ACCEPTED"
    group.cancel_application(2, now)
    assert group.active_application(3).status == "ACCEPTED"


def test_many_required_skills_can_be_covered_by_one_person():
    group = program("project", 2, [1, 2, 3, 4])
    now = group.starts_at - timedelta(days=3)
    group.apply(1, now, [1, 2, 3, 4], creator=True)
    assert group.apply(2, now, [1]).status == "ACCEPTED"
    group.tick(group.starts_at)
    assert group.lifecycle_status == "IN_PROGRESS"


@pytest.mark.parametrize("creator_type,expected", [("USER", 2), ("ADMIN", 1)])
def test_initial_leader_and_succession(creator_type, expected):
    group = program("project", 4, [101], creator_type)
    now = group.starts_at - timedelta(days=3)
    group.apply(1, now, [101])
    group.apply(2, now, [101], leader_volunteer=True)
    group.apply(3, now, [101], leader_volunteer=True)
    group.tick(group.deadline_at)
    assert group.leader_id == expected
    group.cancel_application(expected, group.deadline_at)
    assert group.leader_id == (1 if expected == 2 else 2)


def test_two_extensions_and_explicit_exception_start():
    group = program("project", 4, [101, 102])
    now = group.starts_at - timedelta(days=3)
    group.apply(1, now, [101], creator=True)
    group.apply(2, now, [101])
    for expected in [1, 2]:
        group.tick(group.deadline_at)
        group.extend(
            1,
            group.deadline_at,
            group.starts_at + timedelta(days=14),
            group.ends_at + timedelta(days=14),
            expected,
        )
    assert group.extension_count == 2
    group.tick(group.deadline_at)
    group.choose_exception(1, group.deadline_at, 3)
    assert group.lifecycle_status == "RECRUITING"
    group.tick(group.starts_at)
    assert group.lifecycle_status == "IN_PROGRESS"


def test_missing_conditions_cancel_without_departure_penalty():
    group = program("project", 2, [101, 102])
    group.apply(1, group.starts_at - timedelta(days=3), [101], creator=True)
    group.tick(group.starts_at)
    assert group.lifecycle_status == "CANCELED"
    assert group.accepted()[0].status == "ACCEPTED"


def test_single_survivor_can_abort_without_normal_completion():
    group = program("project", 2, [101])
    now = group.starts_at - timedelta(days=3)
    group.apply(1, now, [101])
    group.apply(2, now, [101])
    group.tick(group.starts_at)
    departure, _ = group.cancel_application(2, group.starts_at + timedelta(hours=1))
    assert departure
    group.end_early(1, group.starts_at + timedelta(hours=2), "진행 불가")
    group.tick(group.ends_at)
    assert group.lifecycle_status == "ABORTED"
    assert not any(event["kind"] == "OPERATING_PERIOD_ENDED" for event in group.events)


@pytest.mark.parametrize("days", [0, 15])
def test_extension_calendar_limits(days):
    group = program("project", 2, [101, 102])
    group.apply(1, group.starts_at - timedelta(days=3), [101], creator=True)
    group.tick(group.deadline_at)
    with pytest.raises(PolicyError):
        group.extend(
            1,
            group.deadline_at,
            group.starts_at + timedelta(days=days),
            group.ends_at + timedelta(days=days),
            1,
        )


def test_direct_input_is_a_snapshot_and_not_a_reference():
    group = program("project", 2, [101])
    submitted = {"skills": ["Python"], "education": "제출 당시"}
    group.apply(1, group.starts_at - timedelta(days=3), [101], direct_input=submitted)
    submitted["skills"].append("나중에 변경")
    submitted["education"] = "새 내용"
    assert group.accepted()[0].direct_input == {
        "skills": ["Python"],
        "education": "제출 당시",
    }


def test_exception_choice_does_not_override_minimum_at_actual_start():
    group = program("project", 4, [101, 102])
    now = group.starts_at - timedelta(days=3)
    group.apply(1, now, [101], creator=True)
    group.apply(2, now, [101])
    group.extension_count = 2
    group.tick(group.deadline_at)
    group.choose_exception(1, group.deadline_at, 1)
    group.cancel_application(2, group.starts_at - timedelta(seconds=1))
    group.tick(group.starts_at)
    assert group.lifecycle_status == "CANCELED"


def test_team_leader_cannot_use_missing_condition_cancel_for_ready_group():
    group = program("project", 2, [101])
    now = group.starts_at - timedelta(days=3)
    group.apply(1, now, [101])
    group.apply(2, now, [101])
    group.tick(group.deadline_at)
    assert not group.permissions(1, group.deadline_at)["can_cancel_project"]
    with pytest.raises(PolicyError):
        group.cancel(1, group.deadline_at, "미달 전용 취소를 잘못 사용")
