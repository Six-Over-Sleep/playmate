"""신규 모임 응답 직렬화. DB 조회 없이 한 시점의 상태로 화면 표시를 구성한다."""

from datetime import timedelta
from zoneinfo import ZoneInfo


def program_view(
    program,
    member_id,
    basic,
    details,
    eligibility,
    now,
    curriculum_policy=None,
    counts=None,
):
    """조회한 요약/상세를 동일 API 계약으로 변환한다. 개인 자료와 익명 권한을 분리한다."""
    item = program.active_application(member_id)
    members = program.accepted()
    missing_skill_ids = program.missing(members=members)
    waiting_count = (
        counts["waiting_count"]
        if counts is not None
        else sum(a.status == "WAITING" for a in program.applications)
    )
    reference_date = program.starts_at.astimezone(ZoneInfo("Asia/Seoul")).date()
    restricted = eligibility["is_restricted"]
    names = details.get("required_skill_names", {})
    permissions = program.permissions(member_id, now, restricted)
    permissions["can_edit_curriculum"] = permissions["can_edit_curriculum"] and (
        curriculum_policy is None or curriculum_policy(program, now)
    )
    if member_id is None:
        permissions = {key: False for key in permissions}
    return {
        **basic,
        "state": "OPEN" if program.is_recruiting(now) else "CLOSED",
        "recruit_id": program.recruit_id,
        "category": program.category,
        "capacity": program.capacity,
        "creator_member_id": program.creator_id,
        "creator_type": program.creator_type,
        "leader_member_id": program.leader_id,
        "is_leader": member_id is not None and program.leader_id == member_id,
        "my_eligibility": eligibility if member_id is not None else None,
        "extension_window": {
            "reference_start_date": reference_date.isoformat(),
            "earliest_start_date": (reference_date + timedelta(days=1)).isoformat(),
            "latest_start_date": (reference_date + timedelta(days=14)).isoformat(),
            "remaining_extensions": max(0, 2 - program.extension_count),
            "timezone": "Asia/Seoul",
        },
        "exception_start": {
            "selected": program.exception_version == program.schedule_version,
            "schedule_version": program.exception_version,
            "missing_skill_ids": program.exception_missing_skills,
        },
        "starts_at": program.starts_at.isoformat(),
        "ends_at": program.ends_at.isoformat(),
        "deadline_at": program.deadline_at.isoformat(),
        "meeting_start": (
            program.starts_at.isoformat() if basic["recruit_mode"] == "short" else None
        ),
        "meeting_end": (
            program.ends_at.isoformat() if basic["recruit_mode"] == "short" else None
        ),
        "schedule_version": program.schedule_version,
        "extension_count": program.extension_count,
        "lifecycle_status": program.lifecycle_status,
        "termination_reason": program.termination_reason,
        "required_skill_ids": program.required_skill_ids,
        "required_skills": [
            {
                "skill_id": skill,
                "name": names.get(str(skill)),
                "confirmed_member_count": sum((skill in a.skill_ids for a in members)),
            }
            for skill in program.required_skill_ids
        ],
        "missing_skill_ids": missing_skill_ids,
        "participant_count": len(members),
        "minimum_participants": 2,
        "waiting_count": waiting_count,
        "my_application": (
            {
                "application_id": item.application_id,
                "application_status": item.status,
                "skill_ids": item.skill_ids,
                "leader_volunteer": item.leader_volunteer,
            }
            if item
            else None
        ),
        "permissions": permissions,
        "detail": {
            key: value
            for key, value in details.items()
            if key != "required_skill_names"
        },
        "regular_days": details.get("regular_days"),
        "regular_time": details.get("regular_time"),
        "regular_start_date": details.get("regular_start_date"),
    }
