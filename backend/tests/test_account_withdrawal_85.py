"""Issue #85: 로그아웃/탈퇴는 쿠키를 비우고 개인 정보 변경을 수행한다."""
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.main import app


def _logged_in_client():
    client = TestClient(app)
    login = client.get("/auth/discord/login", follow_redirects=False)
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    fake_user = {"id": "123456789012345678", "username": "tester", "avatar": None}
    fake_member = {"member_id": 918, "discord_id": fake_user["id"], "nickname": "테스터"}
    with (
        patch("backend.app.routers.auth.exchange_code_for_token", new_callable=AsyncMock, return_value="token"),
        patch("backend.app.routers.auth.get_discord_user", new_callable=AsyncMock, return_value=fake_user),
        patch("backend.app.routers.auth.get_member", return_value=fake_member),
    ):
        callback = client.get(
            "/auth/discord/callback", params={"code": "code", "state": state},
            follow_redirects=False,
        )
    assert callback.status_code == 302
    assert client.cookies.get("playmate_session")
    return client


def test_logout_clears_cookie_and_session():
    with _logged_in_client() as client:
        assert client.post("/auth/logout").status_code == 200
        assert not client.cookies.get("playmate_session")
        assert client.get("/auth/me").status_code == 401


def test_withdraw_requires_login():
    with TestClient(app) as client:
        assert client.delete("/auth/withdraw").status_code == 401


def test_withdraw_clears_cookie_after_success():
    with _logged_in_client() as client:
        with patch("backend.app.routers.auth.withdraw_member", return_value=True) as withdraw:
            response = client.delete("/auth/withdraw")
        assert response.status_code == 200
        withdraw.assert_called_once_with(918, "123456789012345678")
        assert not client.cookies.get("playmate_session")
        assert client.get("/auth/me").status_code == 401


def test_withdraw_does_not_clear_cookie_on_failure():
    with _logged_in_client() as client:
        with patch("backend.app.routers.auth.withdraw_member", return_value=False):
            response = client.delete("/auth/withdraw")
        assert response.status_code == 404
        assert client.cookies.get("playmate_session")
