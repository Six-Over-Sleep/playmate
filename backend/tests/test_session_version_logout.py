"""로그아웃 후 과거 서명 세션 쿠키의 재사용을 거부합니다."""
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from app.main import app
from backend.app.routers import auth as routes


def test_stale_cookie_cannot_restore_login():
    state = {"version": 0}
    discord = {"id": "123456789012345678", "username": "test-user", "avatar": None}

    def get_member(discord_id):
        assert discord_id == discord["id"]
        return {
            "member_id": 99,
            "discord_id": discord_id,
            "nickname": "테스트",
            "role_code": "USER",
            "session_version": state["version"],
        }

    def revoke(member_id, discord_id, version):
        assert (member_id, discord_id) == (99, discord["id"])
        if version != state["version"]:
            return False
        state["version"] += 1
        return True

    with (
        patch.object(routes, "exchange_code_for_token", new=AsyncMock(return_value="fake-token")),
        patch.object(routes, "get_discord_user", new=AsyncMock(return_value=discord)),
        patch.object(routes, "get_member", side_effect=get_member),
        patch.object(routes, "revoke_member_session", side_effect=revoke),
        TestClient(app) as client,
    ):
        login = client.get("/auth/discord/login", follow_redirects=False)
        oauth_state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        callback = client.get("/auth/discord/callback", params={"code": "test", "state": oauth_state}, follow_redirects=False)
        assert callback.status_code == 302
        old_cookie = client.cookies.get("playmate_session")
        assert old_cookie
        assert client.get("/auth/me").status_code == 200
        assert client.post("/auth/logout").status_code == 200
        assert state["version"] == 1
        assert client.get("/auth/me").status_code == 401
        client.cookies.set("playmate_session", old_cookie)
        assert client.get("/auth/me").status_code == 401
