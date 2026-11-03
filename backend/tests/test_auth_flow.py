"""Discord OAuth 로그인 흐름(로그인 시작 → 콜백 → /auth/me)을 외부 요청 없이 검증한다.

Discord 토큰 교환·사용자 조회와 회원 DB 조회는 앱이 실제로 쓰는 모듈(backend.app.routers.auth)에서 대역으로 바꾼다.
대역이 빠지더라도 실제 네트워크 전송 계층을 막아 Discord로 요청이 나가지 않게 한다.
"""

from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app
from backend.app.routers import auth as auth_routes


FAKE_DISCORD_USER = {
    "id": "123456789012345678",
    "username": "test_user",
    "avatar": None,
}

fake_member = {
    "member_id": 1,
    "discord_id": "123456789012345678",
    "nickname": "테스트",
    "course": "AI",
    "cohort": 36,
    "role_code": "USER",
}


@pytest.fixture(autouse=True)
def block_real_http(monkeypatch):
    """httpx의 실제 네트워크 전송을 막는다. TestClient의 앱 내부 전송에는 영향이 없다."""

    def refuse(*args, **kwargs):
        raise AssertionError("테스트 중 실제 외부 HTTP 요청이 시도되었습니다.")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)


def discord_doubles(member=None, exchange=None):
    """앱이 실제로 사용하는 auth 라우터 모듈의 외부 호출·회원 조회를 대역으로 바꾼다."""
    exchange = exchange or AsyncMock(return_value="fake_token")
    return exchange, (
        patch.object(auth_routes, "exchange_code_for_token", exchange),
        patch.object(auth_routes, "get_discord_user", AsyncMock(return_value=FAKE_DISCORD_USER)),
        patch.object(auth_routes, "get_member", return_value=member),
    )


def start_login(client):
    """로그인 시작 응답의 리디렉션과 state를 확인하고 state를 반환한다."""
    response = client.get("/auth/discord/login", follow_redirects=False)
    assert response.status_code == 302
    location = urlparse(response.headers["location"])
    assert location.netloc == "discord.com"
    return parse_qs(location.query)["state"][0]


def callback(client, **params):
    return client.get("/auth/discord/callback", params=params, follow_redirects=False)


def test_patches_target_module_used_by_app():
    """대역 대상 모듈이 main 앱에 등록된 실제 OAuth 콜백 라우트의 모듈과 같은지 확인한다."""
    route = next(r for r in main_module.auth_router.routes if r.path.endswith("/discord/callback"))
    assert route.endpoint.__module__ == auth_routes.__name__


def _login_callback(existing_member=None):
    """대역 OAuth 콜백의 리디렉션과 이후 회원 세션을 검증한다."""
    exchange, doubles = discord_doubles(existing_member)
    with TestClient(app) as client, doubles[0], doubles[1], doubles[2]:
        state = start_login(client)
        response = callback(client, code="fake_code", state=state)
        assert response.status_code == 302
        result = parse_qs(urlparse(response.headers["location"]).query)

        # /auth/me도 회원 조회 대역이 적용된 상태에서 확인한다.
        me_response = client.get("/auth/me")
        assert me_response.status_code == 200
        exchange.assert_awaited_once_with("fake_code")
        return result, me_response.json()


def test_new_member_login():
    """신규 회원 리디렉션과 회원가입 필요 상태를 확인한다."""
    new_result, new_me = _login_callback()
    assert new_result["signup"] == ["required"]
    assert new_me["signup_required"] is True
    assert new_me["member"] is None


def test_existing_member_login():
    """기존 회원 리디렉션과 member_id 세션을 확인한다."""
    existing_result, existing_me = _login_callback(fake_member)
    assert existing_result["auth"] == ["success"]
    assert existing_me["signup_required"] is False
    assert existing_me["member_id"] == 1


def test_wrong_state_is_rejected_without_token_exchange():
    """로그인 시작 때 받은 state와 다르면 400이고 Discord 토큰 교환을 하지 않는다."""
    exchange, doubles = discord_doubles(fake_member)
    with TestClient(app) as client, doubles[0], doubles[1], doubles[2]:
        start_login(client)
        response = callback(client, code="fake_code", state="forged-state")
        assert response.status_code == 400
        assert client.get("/auth/me").status_code == 401
    exchange.assert_not_awaited()


def test_reused_state_is_rejected():
    """한 번 사용한 state로 콜백을 다시 호출하면 400이다(state 일회성)."""
    exchange, doubles = discord_doubles(fake_member)
    with TestClient(app) as client, doubles[0], doubles[1], doubles[2]:
        state = start_login(client)
        assert callback(client, code="fake_code", state=state).status_code == 302
        assert callback(client, code="fake_code", state=state).status_code == 400
    exchange.assert_awaited_once()


def test_callback_without_login_session_is_rejected():
    """로그인 시작 세션이 없거나 만료된 상태(다른 브라우저 등)의 콜백은 400이다."""
    exchange, doubles = discord_doubles(fake_member)
    with TestClient(app) as starter, TestClient(app) as other, doubles[0], doubles[1], doubles[2]:
        state = start_login(starter)
        response = callback(other, code="fake_code", state=state)
        assert response.status_code == 400
        assert other.get("/auth/me").status_code == 401
    exchange.assert_not_awaited()


@pytest.mark.parametrize(
    "params",
    [{"error": "access_denied"}, {}],
    ids=["discord_denied", "missing_code"],
)
def test_denied_or_missing_code_is_rejected(params):
    """사용자가 Discord 인증을 거부했거나 인증 코드가 없으면 400이다."""
    exchange, doubles = discord_doubles(fake_member)
    with TestClient(app) as client, doubles[0], doubles[1], doubles[2]:
        state = start_login(client)
        response = callback(client, state=state, **params)
        assert response.status_code == 400
        assert client.get("/auth/me").status_code == 401
    exchange.assert_not_awaited()


def test_discord_token_failure_returns_502_without_session():
    """Discord 토큰 교환이 실패하면 502이고 로그인 세션이 만들어지지 않는다."""
    failing = AsyncMock(side_effect=httpx.HTTPError("token exchange failed"))
    exchange, doubles = discord_doubles(fake_member, exchange=failing)
    with TestClient(app) as client, doubles[0], doubles[1], doubles[2]:
        state = start_login(client)
        response = callback(client, code="fake_code", state=state)
        assert response.status_code == 502
        assert client.get("/auth/me").status_code == 401
