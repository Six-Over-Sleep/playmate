"""실제 main 앱의 경로에서 기존 모임과 신규 프로그램을 함께 검증한다. 인증은 대역이다."""

import asyncio
from base64 import b64encode
from collections import Counter
import json

import httpx
from fastapi import HTTPException
from itsdangerous import TimestampSigner
import pytest

from app.main import app
from backend.app.core.database import Base
from backend.app.models.recruit import (
    RecruitSportsDetail,
    RecruitGameDetail,
    RecruitGroupBuyDetail,
)
from backend.app.routers import recruit as routes
from backend.app.routers.recruit_program import build_program_service


@pytest.fixture
def runtime(service, monkeypatch):
    engine = service.repository.session.get_bind()
    Base.metadata.create_all(
        engine,
        tables=[
            RecruitSportsDetail.__table__,
            RecruitGameDetail.__table__,
            RecruitGroupBuyDetail.__table__,
        ],
    )
    monkeypatch.setenv("ENABLE_RECRUIT_PROGRAMS", "true")
    app.dependency_overrides[build_program_service] = lambda: service

    def fake_auth(request, development_member):
        member = request.session.get("member_id") or development_member
        if member is None:
            raise HTTPException(401, "로그인이 필요합니다.")
        return member

    monkeypatch.setattr(routes, "get_current_member_id", fake_auth)
    cookie = (
        TimestampSigner("isolated-test-secret")
        .sign(
            b64encode(
                json.dumps({"member_id": 1, "user": {"discord_id": "fake"}}).encode()
            )
        )
        .decode()
    )

    class Client:
        def request(self, method, path, *, member=None, legacy_login=False, **kwargs):
            headers = {}
            if member is not None:
                headers["X-Dev-Member-ID"] = str(member)
            if legacy_login:
                headers["Cookie"] = "playmate_session=" + cookie

            async def send():
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as client:
                    return await client.request(method, path, headers=headers, **kwargs)

            return asyncio.run(send())

    yield Client()
    app.dependency_overrides.pop(build_program_service, None)


def json_payload(payload):
    return {
        key: value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in payload.items()
    }


@pytest.mark.parametrize(
    "category,extra",
    [
        ("sports", {"sport_name": "러닝"}),
        ("game", {"game_name": "보드게임"}),
        ("group_buy", {"product_name": "책"}),
        ("study", {"study_topic": "기존 스터디"}),
    ],
)
def test_legacy_creation_and_public_detail_preserved(runtime, payload, category, extra):
    body = {
        "title": "기존 모임",
        "body": "기존 계약 유지",
        "category": category,
        "recruit_mode": "short",
        "capacity": 6,
        "deadline_at": payload["starts_at"].replace(tzinfo=None).isoformat(),
        "meeting_start": payload["starts_at"].replace(tzinfo=None).isoformat(),
        "meeting_end": payload["ends_at"].replace(tzinfo=None).isoformat(),
        **extra,
    }
    result = runtime.request("POST", "/api/recruits", json=body, legacy_login=True)
    assert result.status_code == 201, result.text
    recruit = result.json()["recruit_id"]
    detail = runtime.request("GET", f"/api/recruits/{recruit}")
    assert detail.status_code == 200 and detail.json()["category"] == category
    assert "lifecycle_status" not in detail.json()


def test_new_study_real_main_routes_public_read_and_authenticated_join(
    runtime, payload
):
    created = runtime.request(
        "POST", "/api/recruits", json=json_payload(payload), member=1
    )
    assert created.status_code == 201, created.text
    recruit = created.json()["recruit_id"]
    public = runtime.request("GET", f"/api/recruits/{recruit}").json()
    assert public["my_application"] is None and public["my_eligibility"] is None
    assert not any(public["permissions"].values())
    assert public["is_leader"] is False and public["liked_by_me"] is False
    assert runtime.request("POST", f"/api/recruits/{recruit}/join").status_code == 401
    assert (
        runtime.request("POST", f"/api/recruits/{recruit}/join", member=2).json()[
            "application_status"
        ]
        == "ACCEPTED"
    )
    assert (
        runtime.request("POST", f"/api/recruits/{recruit}/join", member=3).json()[
            "application_status"
        ]
        == "WAITING"
    )
    assert (
        runtime.request(
            "PATCH", f"/api/recruits/{recruit}", json={"title": "도용"}, member=2
        ).status_code
        == 403
    )
    assert (
        runtime.request("DELETE", f"/api/recruits/{recruit}/join", member=2).status_code
        == 200
    )
    assert (
        runtime.request("GET", f"/api/recruits/{recruit}", member=3).json()[
            "my_application"
        ]["application_status"]
        == "ACCEPTED"
    )
    assert runtime.request("GET", "/api/recruits").json()[0]["recruit_id"] == recruit


def test_new_project_does_not_fall_back_when_validation_fails(runtime, payload):
    body = json_payload(payload)
    body.update(
        category="project",
        required_skill_ids=[101, 102],
        creator_application={"skill_ids": [101]},
    )
    assert (
        runtime.request("POST", "/api/recruits", json=body, member=1).status_code == 201
    )
    del body["starts_at"]
    assert (
        runtime.request("POST", "/api/recruits", json=body, member=1).status_code == 422
    )
    assert len(runtime.request("GET", "/api/recruits").json()) == 1


def test_feature_off_cannot_bypass_rules_through_legacy(runtime, payload, monkeypatch):
    result = runtime.request(
        "POST", "/api/recruits", json=json_payload(payload), member=1
    )
    recruit = result.json()["recruit_id"]
    monkeypatch.setenv("ENABLE_RECRUIT_PROGRAMS", "false")
    assert runtime.request("GET", "/api/recruits").json() == []
    assert (
        runtime.request(
            "PATCH", f"/api/recruits/{recruit}", json={"capacity": 5}, member=2
        ).status_code
        == 503
    )
    assert (
        runtime.request(
            "POST", "/api/recruits", json=json_payload(payload), member=1
        ).status_code
        == 503
    )


def test_main_registers_each_recruit_method_once():
    keys = [
        (method, route.path)
        for route in app.routes
        if route.path.startswith("/api/recruits")
        for method in getattr(route, "methods", [])
    ]
    assert all(count == 1 for count in Counter(keys).values())
    assert ("POST", "/api/recruits/{recruit_id}/extension") in keys
    assert ("GET", "/__test__/guide") not in keys


@pytest.mark.parametrize(
    "category,extra",
    [
        ("sports", {"sport_name": "러닝"}),
        ("game", {"game_name": "보드게임"}),
        ("group_buy", {"product_name": "책"}),
        ("study", {"study_topic": "기존 스터디"}),
    ],
)
def test_legacy_join_and_cancel_use_authenticated_member(
    runtime, payload, category, extra
):
    """같은 로그인 회원의 이중 참여를 막고 본인 참여만 취소한다."""
    body = {
        "title": "회원 식별 검증",
        "body": "기존 계약",
        "category": category,
        "recruit_mode": "short",
        "capacity": 4,
        "deadline_at": payload["starts_at"].replace(tzinfo=None).isoformat(),
        "meeting_start": payload["starts_at"].replace(tzinfo=None).isoformat(),
        "meeting_end": payload["ends_at"].replace(tzinfo=None).isoformat(),
        **extra,
    }
    created = runtime.request("POST", "/api/recruits", json=body, legacy_login=True)
    assert created.status_code == 201, created.text
    path = f"/api/recruits/{created.json()['recruit_id']}"

    def participants():
        return sorted(
            item["member_id"]
            for item in runtime.request("GET", path + "/members").json()
        )

    assert participants() == [1]
    assert runtime.request("POST", path + "/join").status_code == 401
    assert runtime.request("DELETE", path + "/join").status_code == 401
    assert runtime.request("POST", path + "/join", legacy_login=True).status_code == 400
    assert participants() == [1]
    assert runtime.request("POST", path + "/join", member=2).status_code == 200
    assert runtime.request("POST", path + "/join", member=2).status_code == 400
    assert participants() == [1, 2]
    assert runtime.request("DELETE", path + "/join", member=3).status_code == 400
    assert participants() == [1, 2]
    assert runtime.request("DELETE", path + "/join", member=2).status_code == 200
    assert participants() == [1]
    assert runtime.request("POST", path + "/join", member=2).status_code == 200
    assert participants() == [1, 2]
    assert (
        runtime.request("DELETE", path + "/join", legacy_login=True).status_code == 403
    )


def test_main_category_filter_and_no_legacy_fallback_for_new_fields(runtime, payload):
    runtime.request("POST", "/api/recruits", json=json_payload(payload), member=1)
    assert len(runtime.request("GET", "/api/recruits?category=study").json()) == 1
    assert runtime.request("GET", "/api/recruits?category=project").json() == []
    assert runtime.request("GET", "/api/recruits?category=invalid").status_code == 422
    recruit = runtime.request("GET", "/api/recruits").json()[0]["recruit_id"]
    assert (
        runtime.request(
            "PATCH", f"/api/recruits/{recruit}", json={"unknown_field": 1}, member=1
        ).status_code
        == 422
    )


def test_new_draft_delete_checks_owner_and_preserves_participation(runtime, payload):
    recruit = runtime.request(
        "POST", "/api/recruits", json=json_payload(payload), member=1
    ).json()["recruit_id"]
    assert (
        runtime.request("DELETE", f"/api/recruits/{recruit}", member=2).status_code
        == 403
    )
    runtime.request("POST", f"/api/recruits/{recruit}/join", member=2)
    assert (
        runtime.request("DELETE", f"/api/recruits/{recruit}", member=1).status_code
        == 409
    )
    empty = runtime.request(
        "POST", "/api/recruits", json=json_payload(payload), member=1
    ).json()["recruit_id"]
    assert (
        runtime.request("DELETE", f"/api/recruits/{empty}", member=1).status_code == 200
    )
    assert runtime.request("GET", f"/api/recruits/{empty}").status_code == 404
