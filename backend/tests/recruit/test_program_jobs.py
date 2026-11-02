"""외부 전송 없는 예약 실행과 오류 복구를 검증한다. DB는 기본 격리 SQLite다."""

from datetime import timedelta
from threading import Event

import pytest
from sqlalchemy import func, select

from backend.app.core.recruit_config import RecruitSchedulerSettings
from backend.app.jobs import run_recruit_scheduler as scheduler
from backend.app.models.recruit_program import OutboxRecord
from backend.app.schemas.recruit_program import ProgramApplication, ProgramCreate


def create_pair(service, payload):
    """개설자를 포함한 두 사람을 확정한다."""
    recruit = service.create(1, ProgramCreate(**payload))["recruit_id"]
    service.apply(recruit, 2, ProgramApplication())
    return recruit


def test_failure_rolls_back_one_program_and_retries_next_cycle(
    service, payload, monkeypatch
):
    first = create_pair(service, payload)
    second = create_pair(service, payload)
    service.test_clock[0] = payload["starts_at"]
    original = service.repository.save

    def fail_first(program):
        original(program)
        if program.recruit_id == first:
            raise RuntimeError("저장 후 실패")

    monkeypatch.setattr(service.repository, "save", fail_first)
    failures = []
    assert service.tick(on_error=failures.append) == 1
    assert failures == [first]
    assert service.repository.load(first).lifecycle_status != "IN_PROGRESS"
    assert service.repository.load(second).lifecycle_status == "IN_PROGRESS"
    monkeypatch.setattr(service.repository, "save", original)
    assert service.tick() == 1
    assert service.repository.load(first).lifecycle_status == "IN_PROGRESS"


def test_restart_catches_up_and_repeated_execution_does_not_duplicate_events(
    service, payload
):
    recruit = create_pair(service, payload)
    service.test_clock[0] = payload["ends_at"] + timedelta(seconds=1)
    assert service.tick() == 1
    assert service.repository.load(recruit).lifecycle_status == "COMPLETED"
    assert service.tick() == 0
    events = service.repository.session.scalars(select(OutboxRecord)).all()
    assert [event.kind for event in events] == ["OPERATING_PERIOD_ENDED"]
    assert all(event.status == "PENDING" for event in events)


def test_cycle_closes_session_without_dispatching_outbox(service, payload, monkeypatch):
    from contextlib import contextmanager
    from backend.app.services.recruit_program_service import ProgramService
    from backend.app.services.recruit_reward_service import RecruitOutboxService

    recruit = create_pair(service, payload)
    service.test_clock[0] = payload["starts_at"] - timedelta(hours=24)
    calls = []

    @contextmanager
    def factory():
        try:
            yield service.repository.session
        finally:
            calls.append("closed")

    original = ProgramService.tick
    monkeypatch.setattr(
        ProgramService,
        "tick",
        lambda self, on_error: original(service, on_error=on_error),
    )

    def forbidden(*args, **kwargs):
        pytest.fail("예약 실행이 외부 전송기를 호출했습니다.")

    monkeypatch.setattr(RecruitOutboxService, "dispatch", forbidden)
    assert scheduler.run_cycle(factory) == (1, 0)
    assert calls == ["closed"]
    assert service.repository.load(recruit).lifecycle_status != "IN_PROGRESS"
    assert (
        service.repository.session.scalar(
            select(func.count()).select_from(OutboxRecord)
        )
        == 1
    )


@pytest.mark.parametrize("value", ["0", "-1", "abc", "", "1.5"])
def test_invalid_scheduler_settings_rejected(monkeypatch, value):
    monkeypatch.setenv("ENABLE_RECRUIT_PROGRAMS", "true")
    monkeypatch.setenv("RECRUIT_SCHEDULER_INTERVAL_SECONDS", value)
    with pytest.raises(ValueError):
        RecruitSchedulerSettings.from_environment()


def test_feature_flag_required(monkeypatch):
    monkeypatch.setenv("ENABLE_RECRUIT_PROGRAMS", "false")
    with pytest.raises(ValueError, match="ENABLE_RECRUIT_PROGRAMS"):
        RecruitSchedulerSettings.from_environment()


def test_valid_settings_and_invalid_retry(monkeypatch):
    monkeypatch.setenv("ENABLE_RECRUIT_PROGRAMS", "true")
    monkeypatch.setenv("RECRUIT_SCHEDULER_INTERVAL_SECONDS", "15")
    monkeypatch.setenv("RECRUIT_SCHEDULER_RETRY_SECONDS", "5")
    assert RecruitSchedulerSettings.from_environment() == RecruitSchedulerSettings(
        15, 5
    )
    monkeypatch.setenv("RECRUIT_SCHEDULER_RETRY_SECONDS", "0")
    with pytest.raises(ValueError, match="RETRY"):
        RecruitSchedulerSettings.from_environment()


def test_cycle_returns_session_even_when_target_query_fails(service, monkeypatch):
    from contextlib import contextmanager
    from backend.app.repositories.recruit_program_repository import ProgramRepository

    closed = []

    @contextmanager
    def factory():
        try:
            yield service.repository.session
        finally:
            service.repository.session.close()
            closed.append(True)

    def fail(self, now):
        raise RuntimeError("조회 장애")

    monkeypatch.setattr(ProgramRepository, "pending_ids", fail)
    with pytest.raises(RuntimeError):
        scheduler.run_cycle(factory)
    assert closed == [True]


@pytest.mark.parametrize("result", [(2, 0), (1, 1), RuntimeError("접속 장애")])
def test_loop_selects_retry_and_stops_without_sleeping(monkeypatch, result):
    class Stop:
        stopped = False
        delays = []

        def is_set(self):
            return self.stopped

        def wait(self, delay):
            self.delays.append(delay)
            self.stopped = True

    def cycle(factory):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(scheduler, "run_cycle", cycle)
    stop = Stop()
    settings = RecruitSchedulerSettings(interval_seconds=60, retry_seconds=7)
    assert scheduler.run_scheduler(None, settings, stop) == 0
    assert stop.delays == [60 if result == (2, 0) else 7]


def test_once_reports_failure_and_pre_stopped_loop_does_not_run(monkeypatch):
    monkeypatch.setattr(scheduler, "run_cycle", lambda factory: (0, 1))
    settings = RecruitSchedulerSettings()
    assert scheduler.run_scheduler(None, settings, Event(), once=True) == 1
    stop = Event()
    stop.set()
    assert scheduler.run_scheduler(None, settings, stop) == 0
