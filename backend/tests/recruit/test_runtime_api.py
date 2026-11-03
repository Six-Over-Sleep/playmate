"""실제 main 앱의 경로에서 기존 모임과 신규 프로그램을 함께 검증한다. 인증은 대역이다."""

import asyncio
from base64 import b64encode
from collections import Counter
import importlib.util
import json
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from itsdangerous import TimestampSigner
import pytest

from app.main import app
import app.main as main_module
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
    from backend.app.services import recruit_member

    # 기존 모임도 같은 가상 KST 시각을 사용해 실제 날짜가 바뀌어도 마감되지 않게 한다.
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(
        recruit_member,
        "kst_now",
        lambda: service.clock().astimezone(ZoneInfo("Asia/Seoul")).replace(tzinfo=None),
    )
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
    # 활성 회원 전용 정책: 조회도 로그인한 회원(4)으로 수행한다.
    detail = runtime.request("GET", f"/api/recruits/{recruit}", member=4)
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
    # 비로그인 조회는 401, 신청하지 않은 다른 회원(4)에게는 개인 상태가 비어 있다.
    assert runtime.request("GET", f"/api/recruits/{recruit}").status_code == 401
    public = runtime.request("GET", f"/api/recruits/{recruit}", member=4).json()
    assert public["my_application"] is None
    # 신청 전 회원에게는 참여 신청 권한만 열려 있고 수정·운영 권한은 없다.
    assert {key for key, allowed in public["permissions"].items() if allowed} == {"can_join"}
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
    assert runtime.request("GET", "/api/recruits", member=4).json()[0]["recruit_id"] == recruit


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
    assert len(runtime.request("GET", "/api/recruits", member=4).json()) == 1


def test_feature_off_cannot_bypass_rules_through_legacy(runtime, payload, monkeypatch):
    result = runtime.request(
        "POST", "/api/recruits", json=json_payload(payload), member=1
    )
    recruit = result.json()["recruit_id"]
    monkeypatch.setenv("ENABLE_RECRUIT_PROGRAMS", "false")
    assert runtime.request("GET", "/api/recruits", member=4).json() == []
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


MAIN_PATH = Path(main_module.__file__)


def _main_route_keys(monkeypatch):
    """main.py를 다시 실행하며 include_router 호출을 기록해 실제 등록 (메서드, 경로) 목록을 만든다.

    FastAPI 버전별 app.routes 내부 구조(_IncludedRouter 등)에 의존하지 않고,
    공개 API인 include_router 인자와 APIRouter.routes의 path·methods만 사용한다.
    같은 라우터를 두 번 포함하거나 라우터 안·사이에서 같은 경로를 중복 정의해도 목록에 그대로 드러난다.
    """
    included = []
    original = FastAPI.include_router

    def record(self, router, *args, **kwargs):
        included.append((router, kwargs.get("prefix", "")))
        return original(self, router, *args, **kwargs)

    monkeypatch.setattr(FastAPI, "include_router", record)
    spec = importlib.util.spec_from_file_location("main_route_audit", MAIN_PATH)
    spec.loader.exec_module(importlib.util.module_from_spec(spec))

    keys = []
    for router, prefix in included:
        for route in router.routes:
            # 모임 라우터가 하위 라우터를 포함하게 되면 이 검사도 함께 보완해야 한다.
            assert hasattr(route, "path"), f"경로 정보를 확인할 수 없는 라우트: {route!r}"
            keys += [(method, prefix + route.path) for method in getattr(route, "methods", None) or []]
    return keys


def test_main_registers_each_recruit_method_once(monkeypatch):
    """main 앱에 모임 API의 (메서드, 경로)가 각각 한 번만 등록되고, 필요한 경로만 노출되는지 확인한다."""
    keys = [key for key in _main_route_keys(monkeypatch) if key[1].startswith("/api/recruits")]

    duplicated = {key: count for key, count in Counter(keys).items() if count > 1}
    assert not duplicated, f"중복 등록된 모임 라우트: {duplicated}"
    assert ("POST", "/api/recruits/{recruit_id}/extension") in keys
    assert ("GET", "/__test__/guide") not in keys
    # 공용 앱의 OpenAPI에도 같은 모임 작업들이 노출되는지 함께 확인한다(존재 확인용, 중복 판정은 위 목록 기준).
    documented = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/recruits")
        for method in operations
    }
    assert documented == set(keys)


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
            for item in runtime.request("GET", path + "/members", member=4).json()
        )

    assert participants() == [1]
    assert runtime.request("POST", path + "/join").status_code == 401
    assert runtime.request("DELETE", path + "/join").status_code == 401
    # 기존 서비스는 HOST 재신청을 일반 중복(400)과 구분해 권한 오류로 반환한다.
    assert runtime.request("POST", path + "/join", legacy_login=True).status_code == 403
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
    assert len(runtime.request("GET", "/api/recruits?category=study", member=4).json()) == 1
    assert runtime.request("GET", "/api/recruits?category=project", member=4).json() == []
    assert (
        runtime.request("GET", "/api/recruits?category=invalid", member=4).status_code
        == 422
    )
    recruit = runtime.request("GET", "/api/recruits", member=4).json()[0]["recruit_id"]
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
    assert runtime.request("GET", f"/api/recruits/{empty}", member=4).status_code == 404
