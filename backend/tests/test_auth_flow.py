"""Discord 외부 호출 없이 실제 HTTP 리디렉션과 세션 분기를 검증한다."""

from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.parametrize("existing_member", [None, {"member_id": 1}])
def test_login(existing_member):
    """신규·기존 회원 콜백의 302 목적지와 이후 /auth/me 세션을 확인한다."""
    with TestClient(app) as client:
        response = client.get("/auth/discord/login", follow_redirects=False)
        assert response.status_code == 302
        state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
        fake_user = {
            "id": "123456789012345678",
            "username": "test_user",
            "avatar": None,
        }
        with (
            patch(
                "app.routers.auth.exchange_code_for_token",
                new_callable=AsyncMock,
                return_value="fake_token",
            ),
            patch(
                "app.routers.auth.get_discord_user",
                new_callable=AsyncMock,
                return_value=fake_user,
            ),
            patch("app.routers.auth.get_member", return_value=existing_member),
        ):
            response = client.get(
                "/auth/discord/callback",
                params={"code": "fake_code", "state": state},
                follow_redirects=False,
            )
        assert response.status_code == 302
        expected = "auth=success" if existing_member else "signup=required"
        assert response.headers["location"] == f"http://localhost:5173/?{expected}"
        response = client.get("/auth/me")
        assert response.status_code == 200
        result = response.json()
        assert result["signup_required"] is (existing_member is None)
        if existing_member:
            assert result["member_id"] == 1
        else:
            assert result["member"] is None


def test_oauth_state_rejected():
    """저장된 state가 없는 콜백은 토큰 교환 전에 400으로 거부한다."""
    with (
        TestClient(app) as client,
        patch(
            "app.routers.auth.exchange_code_for_token", new_callable=AsyncMock
        ) as exchange,
    ):
        response = client.get("/auth/discord/callback?code=fake&state=invalid")
        assert response.status_code == 400
        exchange.assert_not_called()
