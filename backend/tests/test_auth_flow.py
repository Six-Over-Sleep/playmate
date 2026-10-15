
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.main import app


def _login_callback(existing_member=None):
    """대역 OAuth 콜백의 리디렉션과 이후 회원 세션을 검증한다."""
    # 매번 새로운 브라우저 세션 생성
    with TestClient(app) as client:

        # 1. Discord 로그인 시작
        response = client.get(
            "/auth/discord/login",
            follow_redirects=False,
        )

        assert response.status_code == 302

        # 2. 로그인 요청의 state 추출
        redirect_url = response.headers["location"]

        state = parse_qs(
            urlparse(redirect_url).query
        )["state"][0]

        # 3. Discord 및 DB 응답을 가짜 데이터로 대체
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
            patch(
                "app.routers.auth.get_member",
                return_value=existing_member,
            ),
        ):
            response = client.get(
                "/auth/discord/callback",
                params={
                    "code": "fake_code",
                    "state": state,
                },
                follow_redirects=False,
            )

        assert response.status_code == 302
        result = parse_qs(urlparse(response.headers["location"]).query)

        # 4. 로그인 상태 확인
        me_response = client.get("/auth/me")
        assert me_response.status_code == 200

        return result, me_response.json()


# 신규 회원 테스트
def test_new_member_login():
    """신규 회원 리디렉션과 회원가입 필요 상태를 확인한다."""
    new_result, new_me = _login_callback()
    assert new_result["signup"] == ["required"]
    assert new_me["signup_required"] is True
    assert new_me["member"] is None


# 기존 회원 테스트
fake_member = {
    "member_id": 1,
    "discord_id": "123456789012345678",
    "nickname": "테스트",
    "course": "AI",
    "cohort": 36,
    "role_code": "USER",
}


def test_existing_member_login():
    """기존 회원 리디렉션과 member_id 세션을 확인한다."""
    existing_result, existing_me = _login_callback(fake_member)
    assert existing_result["auth"] == ["success"]
    assert existing_me["signup_required"] is False
    assert existing_me["member_id"] == 1
