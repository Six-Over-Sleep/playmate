"""모집 마감(deadline_at) 이후 참여 차단을 DB 없이 확인한다.

Discord Bot은 마감 시각에 최종 참여자 기준으로 모임 채널을 만든다. 마감 뒤에도 참여가 가능하면
Discord 참여자와 DB 참여자가 어긋나므로, join_recruit이 마감 뒤 요청을 거절하는지 확인한다.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.app.services import recruit_member


class FakeDb:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.added = []

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def prepare(monkeypatch, deadline_at):
    recruit = SimpleNamespace(
        recruit_id=1, post_id=1, state="OPEN", capacity=5, deadline_at=deadline_at,
    )
    monkeypatch.setattr(recruit_member.recruit_repo, "get_recruit_for_update", lambda db, recruit_id: recruit)
    monkeypatch.setattr(recruit_member.recruit_repo, "get_post",
                        lambda db, post_id: SimpleNamespace(post_status=None))
    monkeypatch.setattr(recruit_member.recruit_repo, "find_member", lambda db, recruit_id, member_id: None)
    monkeypatch.setattr(recruit_member.recruit_repo, "count_joined_members", lambda db, recruit_id: 0)
    db = FakeDb()
    monkeypatch.setattr(recruit_member.recruit_repo, "add_member", lambda db_, member: db.added.append(member))
    return db


def test_join_is_rejected_after_deadline(monkeypatch):
    db = prepare(monkeypatch, recruit_member.kst_now() - timedelta(minutes=1))
    with pytest.raises(HTTPException) as error:
        recruit_member.join_recruit(db, 1, member_id=5)
    assert error.value.status_code == 400
    assert "마감" in error.value.detail
    assert db.added == [] and db.commits == 0, "마감 뒤에는 참여 기록을 만들지 않는다"
    assert db.rollbacks == 1, "트랜잭션(행 잠금)을 정리한다"


def test_join_is_allowed_before_deadline(monkeypatch):
    db = prepare(monkeypatch, recruit_member.kst_now() + timedelta(hours=1))
    assert recruit_member.join_recruit(db, 1, member_id=5) == {"message": "모임 참여 완료"}
    assert len(db.added) == 1 and db.commits == 1


def test_join_without_deadline_keeps_previous_behavior(monkeypatch):
    """deadline_at이 없는 예전 데이터는 기존처럼 state만 본다 (마감 판단 기준이 없으므로 막지 않는다)."""
    db = prepare(monkeypatch, None)
    assert recruit_member.join_recruit(db, 1, member_id=5) == {"message": "모임 참여 완료"}
    assert db.commits == 1


class UtcHostDatetime(datetime):
    """서버 로컬 시간대가 UTC인 호스트를 흉내 낸다: 2026-10-25 12:00 UTC (= 한국 21:00)."""

    INSTANT = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.INSTANT.astimezone(tz) if tz is not None else cls.INSTANT.replace(tzinfo=None)


def test_deadline_is_compared_in_korean_time_on_utc_host(monkeypatch):
    """deadline_at은 한국 시각으로 저장된다. UTC 서버에서 서버 로컬 시각과 비교하면 9시간 늦게 마감된다."""
    monkeypatch.setattr(recruit_member, "datetime", UtcHostDatetime)
    # 한국 20:00 마감은 한국 21:00 현재 이미 지났다 (UTC 로컬 12:00과 비교하면 아직 안 지난 것으로 잘못 판단함)
    db = prepare(monkeypatch, datetime(2026, 10, 25, 20, 0))
    with pytest.raises(HTTPException) as error:
        recruit_member.join_recruit(db, 1, member_id=5)
    assert error.value.status_code == 400 and db.added == []
    # 한국 22:00 마감은 아직 남았다
    db = prepare(monkeypatch, datetime(2026, 10, 25, 22, 0))
    assert recruit_member.join_recruit(db, 1, member_id=5) == {"message": "모임 참여 완료"}
    assert len(db.added) == 1
