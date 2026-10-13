
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.main import app


def test_login(existing_member=None):
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
            )

        assert response.status_code == 200
        result = response.json()

        # 4. 로그인 상태 확인
        me_response = client.get("/auth/me")
        assert me_response.status_code == 200

        return result, me_response.json()


# 신규 회원 테스트
new_result, new_me = test_login()

assert new_result["signup_required"] is True
assert new_me["signup_required"] is True
assert new_me["member"] is None

print("신규 회원 구분 성공!")


# 기존 회원 테스트
fake_member = {
    "member_id": 1,
    "discord_id": "123456789012345678",
    "nickname": "테스트",
    "course": "AI",
    "cohort": 36,
    "role_code": "USER",
}

existing_result, existing_me = test_login(fake_member)

assert existing_result["signup_required"] is False
assert existing_me["signup_required"] is False
assert existing_me["member_id"] == 1

print("기존 회원 자동 로그인 성공!")
print("모든 인증 분기 테스트 통과!")
