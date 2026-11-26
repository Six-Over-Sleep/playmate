from sqlalchemy import func, select

import pytest

from backend.app.domain.recruit_program import PolicyError
from backend.app.integrations.recruit_events import RecognitionDecision
from backend.app.models.recruit_program import OutboxRecord, RecognitionRecord
from backend.app.schemas.recruit_program import (
    ActivityCreate,
    ProgramApplication,
    ProgramCreate,
)
from backend.app.services.recruit_reward_service import (
    RecruitOutboxService,
    RecruitRewardService,
)


class Policy:
    def evaluate(self, activity, member_id, kind):
        # 확정 정책이 아닌 격리 테스트 대역. 남이 낸 결과물로 전체 팀원을 인정하지 않는다.
        return RecognitionDecision(
            activity.author_member_id == member_id,
            "test-policy-1",
            "개인 활동 확인",
            f"week:1:member:{member_id}",
        )


class Gateway:
    def __init__(self):
        self.calls = []
        self.failed = True

    def deliver(self, key, kind, payload):
        self.calls.append((key, kind, payload))
        if self.failed:
            self.failed = False
            raise TimeoutError("비밀 본문은 저장하지 않음")
        return "external-reference"


def activity(service, payload):
    recruit_id = service.create(1, ProgramCreate(**payload))["recruit_id"]
    service.apply(recruit_id, 2, ProgramApplication())
    service.test_clock[0] = payload["starts_at"]
    service.tick()
    record = service.activities(
        recruit_id,
        1,
        ActivityCreate(
            activity_type="WEEKLY_CHECK",
            week=1,
            title="인증",
            body="학습 기록",
        ),
    )
    return recruit_id, record["activity_id"]


def test_no_policy_cannot_fake_recognition(service, payload):
    recruit, record = activity(service, payload)
    with pytest.raises(PolicyError) as error:
        RecruitRewardService(service).recognize(recruit, record, 1, "WEEKLY")
    assert error.value.status == 503


def test_personal_recognition_duplicate_retry_and_original_revoke(service, payload):
    recruit, record = activity(service, payload)
    rewards = RecruitRewardService(service, Policy())
    first = rewards.recognize(recruit, record, 1, "WEEKLY")
    assert rewards.recognize(recruit, record, 1, "WEEKLY") == first
    with pytest.raises(PolicyError):
        rewards.recognize(recruit, record, 2, "WEEKLY")
    assert (
        service.repository.session.scalar(
            select(func.count()).select_from(RecognitionRecord)
        )
        == 1
    )
    gateway = Gateway()
    dispatcher = RecruitOutboxService(
        service, {"XP_GRANT": gateway, "XP_REVOKE": gateway}
    )
    assert dispatcher.dispatch() == 0
    assert service.activities(recruit, 1)[0]["activity_id"] == record
    pending = service.repository.session.scalar(
        select(OutboxRecord).where(OutboxRecord.kind == "XP_GRANT")
    )
    assert pending.status == "PENDING" and pending.attempts == 1
    assert "비밀" not in str(pending.payload)
    assert dispatcher.dispatch() == 1
    assert dispatcher.dispatch() == 0
    assert gateway.calls[0][0] == gateway.calls[1][0]
    rewards.invalidate(recruit, first["recognition_key"], "근거 무효")
    assert dispatcher.dispatch() == 1
    assert gateway.calls[-1][2]["original_grant_reference"] == "external-reference"
    with pytest.raises(PolicyError):
        rewards.recognize(recruit, record, 1, "WEEKLY")


def test_operating_end_alone_does_not_award_completion(service, payload):
    recruit, record = activity(service, payload)
    service.test_clock[0] = payload["ends_at"]
    service.tick()
    assert service.detail(recruit, 1)["lifecycle_status"] == "COMPLETED"
    assert (
        service.repository.session.scalar(
            select(func.count()).select_from(RecognitionRecord)
        )
        == 0
    )


def test_stale_schedule_event_is_not_delivered(service, payload):
    payload.update(
        category="project",
        required_skill_ids=[101, 102],
        capacity=4,
        creator_application={"skill_ids": [101]},
    )
    recruit = service.create(1, ProgramCreate(**payload))["recruit_id"]
    from datetime import timedelta
    from backend.app.schemas.recruit_program import ExtensionRequest

    service.test_clock[0] = payload["starts_at"] - timedelta(hours=24)
    service.tick()
    service.decide(
        recruit,
        1,
        "extend",
        ExtensionRequest(
            starts_at=payload["starts_at"] + timedelta(days=2),
            ends_at=payload["ends_at"] + timedelta(days=2),
            schedule_version=1,
            request_key="first-extension",
        ),
    )
    gateway = Gateway()
    assert RecruitOutboxService(service, {"DISCORD_PREPARE": gateway}).dispatch() == 0
    assert not gateway.calls
