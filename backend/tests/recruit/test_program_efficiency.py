"""업무 결과를 유지하면서 조회 범위·반복·저장 비용이 불필요하게 커지지 않는지 검증한다."""

from datetime import timedelta
from contextlib import contextmanager

from sqlalchemy import event

from backend.app.domain.recruit_program import Application, Program
from backend.app.models.recruit_program import ApplicationRecord
from backend.app.schemas.recruit_program import (
    ExtensionRequest,
    ProgramApplication,
    ProgramCreate,
)
from backend.app.services import recruit as legacy
from backend.app.services.recruit_dispatch_service import RecruitDispatchService
from backend.app.services.recruit_reward_service import RecruitOutboxService


@contextmanager
def statements(service):
    captured = []
    engine = service.repository.session.get_bind()

    def capture(connection, cursor, statement, parameters, context, many):
        captured.append(statement.lower())

    event.listen(engine, "before_cursor_execute", capture)
    try:
        yield captured
    finally:
        event.remove(engine, "before_cursor_execute", capture)


def test_sports_filter_does_not_read_new_programs(service, payload):
    for _ in range(3):
        service.create(1, ProgramCreate(**payload))
    facade = RecruitDispatchService(
        service, True, lambda: 1, lambda: None, lambda: 1, lambda: None
    )
    with statements(service) as captured:
        assert facade.list("sports") == []
    assert not any(
        "from recruit_applications" in query or "from recruit_programs" in query
        for query in captured
    )
    assert sum(query.lstrip().startswith("select") for query in captured) == 1


def test_list_reuses_like_count_and_loads_no_career_or_other_waiters(service, payload):
    recruit = service.create(1, ProgramCreate(**payload))["recruit_id"]
    for member in [2, 3, 4]:
        service.apply(
            recruit,
            member,
            ProgramApplication(direct_input={"education": "비공개 자료"}),
        )
    with statements(service) as captured:
        public = service.list(None)
    assert sum("post_likes" in query for query in captured) == 1
    assert public[0]["participant_count"] == 2 and public[0]["waiting_count"] == 2
    base = legacy.get_recruits(service.repository.session)
    program, _, _, counts = service.repository.list_programs(base, 3)[0]
    assert [item.member_id for item in program.applications] == [1, 2, 3]
    assert all(item.direct_input == {} for item in program.applications)
    assert counts["waiting_count"] == 2
    own = service.list(3)[0]
    assert own["my_application"]["application_status"] == "WAITING"
    assert "비공개 자료" not in str(own)


def test_flush_count_does_not_grow_with_cancelled_history(
    service, payload, monkeypatch
):
    session = service.repository.session
    session.autoflush = False  # 운영 SessionLocal과 같은 조건.
    counts = []
    calls = [0]
    original = session.flush

    def flush(*args, **kwargs):
        calls[0] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(session, "flush", flush)
    for history in [0, 100]:
        recruit = service.create(1, ProgramCreate(**payload))["recruit_id"]
        now = service.clock()
        session.add_all(
            [
                ApplicationRecord(
                    recruit_id=recruit,
                    member_id=4,
                    sequence=index + 2,
                    submitted_at=now,
                    status="CANCELED",
                    payload={
                        "skill_ids": [],
                        "direct_input": {},
                        "leader_volunteer": False,
                        "changed_at": now.isoformat(),
                    },
                )
                for index in range(history)
            ]
        )
        session.commit()
        calls[0] = 0
        with statements(service) as captured:
            result = service.apply(recruit, 2, ProgramApplication())
        counts.append(calls[0])
        assert result["application_status"] == "ACCEPTED"
        assert not any(
            query.startswith("update recruit_applications") for query in captured
        )
    assert counts[0] == counts[1]
    assert counts[1] <= 4


def test_full_group_skips_waiter_scan_and_project_recheck_scans_members_once(service):
    now = service.clock()
    for waiters in [100, 500]:
        group = Program(
            "study", 1, "USER", 2, now + timedelta(days=4), now + timedelta(days=14)
        )
        group.applications = [
            Application(
                index, index, now, status="ACCEPTED" if index <= 2 else "WAITING"
            )
            for index in range(1, waiters + 3)
        ]
        calls = [0]
        original = group.accepted

        def accepted():
            calls[0] += 1
            return original()

        group.accepted = accepted
        group.promote(now)
        assert calls[0] <= 2
        assert sum(item.status == "ACCEPTED" for item in group.applications) == 2
    project = Program(
        "project",
        1,
        "USER",
        2,
        now + timedelta(days=4),
        now + timedelta(days=14),
        [101, 102],
    )
    project.applications = [Application(1, 1, now, skill_ids=[101], status="ACCEPTED")]
    project.applications += [
        Application(index, index, now, skill_ids=[101]) for index in range(2, 102)
    ]
    project.applications.append(Application(102, 102, now, skill_ids=[102]))
    project.promote(now)
    assert [item.member_id for item in project.accepted()] == [1, 102]
    assert len(project.application_changes) == 1


def test_tick_only_processes_due_phase_and_current_schedule(
    service, payload, monkeypatch
):
    payload.update(
        category="project",
        capacity=4,
        required_skill_ids=[101, 102],
        creator_application={"skill_ids": [101]},
    )
    recruit = service.create(1, ProgramCreate(**payload))["recruit_id"]
    commits = [0]
    original = service.repository.session.commit

    def commit():
        commits[0] += 1
        return original()

    monkeypatch.setattr(service.repository.session, "commit", commit)
    assert service.tick() == 0 and commits[0] == 0
    service.test_clock[0] = payload["starts_at"] - timedelta(hours=24)
    assert service.tick() == 1
    assert service.tick() == 0
    service.decide(
        recruit,
        1,
        "extend",
        ExtensionRequest(
            starts_at=payload["starts_at"] + timedelta(days=2),
            ends_at=payload["ends_at"],
            schedule_version=1,
            request_key="efficient-extension",
        ),
    )
    assert service.tick() == 0
    service.test_clock[0] += timedelta(days=2)
    assert service.tick() == 1
    assert service.tick() == 0


def test_unconfigured_outbox_does_not_open_transactions(service, payload):
    recruit = service.create(1, ProgramCreate(**payload))["recruit_id"]
    with service.transaction():
        service.repository.enqueue(recruit, "XP_GRANT", "future-integration", {})
    with statements(service) as captured:
        assert RecruitOutboxService(service).dispatch() == 0
    assert captured == []
