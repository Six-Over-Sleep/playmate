"""모임 참여·취소가 실제 로그인 회원 ID를 쓰는지 공유 DB 없이 확인한다.

모임 생성자는 HOST로 이미 참여 중이므로 일반 참여를 403으로 막고,
취소는 로그인 회원 본인의 참여 기록만 바꾸는지 확인한다.
"""

from types import SimpleNamespace
from base64 import b64encode
from contextlib import contextmanager
import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from itsdangerous import TimestampSigner
from starlette.middleware.sessions import SessionMiddleware

from backend.app.core import auth
from backend.app.routers import recruit as recruit_router
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


def prepare(monkeypatch, rows, capacity=5):
    """rows: {member_id: 참여 기록}. find_member가 받은 member_id를 기록한다."""
    recruit = SimpleNamespace(
        recruit_id=1, post_id=1, state="OPEN", capacity=capacity, deadline_at=None
    )
    db = FakeDb()
    db.looked_up = []

    def find_member(db_, recruit_id, member_id):
        db.looked_up.append(member_id)
        return rows.get(member_id)

    monkeypatch.setattr(
        recruit_member.recruit_repo,
        "get_recruit_for_update",
        lambda db_, recruit_id: recruit,
    )
    monkeypatch.setattr(
        recruit_member.recruit_repo,
        "get_post",
        lambda db_, post_id: SimpleNamespace(post_status=None),
    )
    monkeypatch.setattr(recruit_member.recruit_repo, "find_member", find_member)
    monkeypatch.setattr(
        recruit_member.recruit_repo,
        "count_joined_members",
        lambda db_, recruit_id: sum(r.status == "JOINED" for r in rows.values()),
    )
    monkeypatch.setattr(
        recruit_member.recruit_repo,
        "add_member",
        lambda db_, member: db.added.append(member),
    )
    return db


def row(role="MEMBER", status="JOINED"):
    return SimpleNamespace(role=role, status=status, canceled_at=None, joined_at=None)


def test_join_requires_explicit_member_id(monkeypatch):
    """회원 ID를 생략해도 임시 참여 기록을 생성하지 않는다."""
    db = prepare(monkeypatch, {7: row(role="HOST")})
    with pytest.raises(TypeError):
        recruit_member.join_recruit(db, 1)
    assert db.looked_up == []
    assert db.added == []
    assert db.commits == 0


def test_cancel_still_requires_member_id():
    """취소는 본인 참여 기록을 바꾸므로 기본값 없이 실제 member_id가 필요하다."""
    with pytest.raises(TypeError):
        recruit_member.cancel_join(FakeDb(), 1)


def test_join_saves_logged_in_member_as_member(monkeypatch):
    db = prepare(monkeypatch, {7: row(role="HOST")})
    assert recruit_member.join_recruit(db, 1, member_id=5) == {
        "message": "모임 참여 완료"
    }
    assert db.looked_up == [5]
    assert [(m.member_id, m.role, m.status) for m in db.added] == [
        (5, "MEMBER", "JOINED")
    ]
    assert db.commits == 1


def test_host_cannot_join_own_meetup(monkeypatch):
    db = prepare(monkeypatch, {7: row(role="HOST")})
    with pytest.raises(HTTPException) as error:
        recruit_member.join_recruit(db, 1, member_id=7)
    assert error.value.status_code == 403
    assert error.value.detail == "모임장은 이미 참여 중입니다."
    assert db.added == [] and db.commits == 0 and db.rollbacks == 1


def test_joined_member_cannot_join_twice(monkeypatch):
    db = prepare(monkeypatch, {5: row()})
    with pytest.raises(HTTPException) as error:
        recruit_member.join_recruit(db, 1, member_id=5)
    assert error.value.status_code == 400 and db.added == []


def test_rejoin_after_cancel_reuses_row(monkeypatch):
    canceled = row(status="CANCELED")
    db = prepare(monkeypatch, {5: canceled})
    recruit_member.join_recruit(db, 1, member_id=5)
    assert canceled.status == "JOINED" and canceled.canceled_at is None
    assert db.added == [], "기존 참여 기록을 재사용한다"


def test_cancel_changes_only_logged_in_member_row(monkeypatch):
    mine, other = row(), row()
    db = prepare(monkeypatch, {5: mine, 6: other})
    assert recruit_member.cancel_join(db, 1, member_id=5) == {
        "message": "모임 참여 취소 완료"
    }
    assert db.looked_up == [5]
    assert mine.status == "CANCELED" and other.status == "JOINED"


@pytest.mark.parametrize(
    "rows,member_id,status",
    [
        ({}, 5, 400),  # 참여하지 않은 회원
        ({7: row(role="HOST")}, 7, 403),  # 모임장
    ],
)
def test_cancel_rejections_keep_policy(monkeypatch, rows, member_id, status):
    db = prepare(monkeypatch, rows)
    with pytest.raises(HTTPException) as error:
        recruit_member.cancel_join(db, 1, member_id=member_id)
    assert error.value.status_code == status and db.commits == 0


@pytest.fixture
def router_client(monkeypatch):
    """실제 Router·Dispatch·인증을 연결하고 DB 경계만 대역으로 교체한다."""
    monkeypatch.setenv("APP_ENV", "production")
    checked_members = []
    auth_queries = []
    repository = SimpleNamespace(
        session=FakeDb(),
        is_program=lambda recruit_id: False,
        actor=checked_members.append,
    )
    program_service = SimpleNamespace(repository=repository)

    @contextmanager
    def cursor(**kwargs):
        yield SimpleNamespace(
            execute=lambda sql, values: auth_queries.append(values),
            fetchone=lambda: (1,),
        )

    monkeypatch.setattr(auth, "db_cursor", cursor)
    app = FastAPI()
    secret = "isolated-router-test-secret"
    app.add_middleware(SessionMiddleware, secret_key=secret)
    app.include_router(recruit_router.router)
    app.dependency_overrides[recruit_router.build_program_service] = (
        lambda: program_service
    )

    def request(method, member_id=None):
        headers = {}
        if member_id is not None:
            session = {
                "member_id": member_id,
                "user": {"discord_id": "isolated-discord-user"},
            }
            cookie = (
                TimestampSigner(secret)
                .sign(b64encode(json.dumps(session).encode()))
                .decode()
            )
            headers["Cookie"] = f"session={cookie}"

        async def send():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                return await client.request(
                    method, "/api/recruits/1/join", headers=headers
                )

        return asyncio.run(send())

    return request, checked_members, auth_queries


@pytest.mark.parametrize(
    "method,operation", [("POST", "join_recruit"), ("DELETE", "cancel_join")]
)
def test_router_passes_authenticated_member_id(
    router_client, monkeypatch, method, operation
):
    request, checked, queries = router_client
    received = []

    def process(db, recruit_id, member_id):
        received.append((recruit_id, member_id))
        return {"message": "완료"}

    monkeypatch.setattr(recruit_member, operation, process)
    response = request(method, member_id=5)
    assert response.status_code == 200
    assert received == [(1, 5)]
    assert checked == [5]
    assert queries == [(5, "isolated-discord-user")]


@pytest.mark.parametrize(
    "method,operation", [("POST", "join_recruit"), ("DELETE", "cancel_join")]
)
def test_router_rejects_without_login_before_processing(
    router_client, monkeypatch, method, operation
):
    request, checked, queries = router_client

    def forbidden(*args, **kwargs):
        pytest.fail("비로그인 요청이 참여 저장에 도달했습니다.")

    monkeypatch.setattr(recruit_member, operation, forbidden)
    response = request(method)
    assert response.status_code == 401
    assert checked == []
    assert queries == []
