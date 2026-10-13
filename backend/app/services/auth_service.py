
import httpx

from app.core.config import (
    DISCORD_CLIENT_ID,
    DISCORD_CLIENT_SECRET,
    DISCORD_REDIRECT_URI,
)

DISCORD_API_URL = "https://discord.com/api/v10"


# 1. 인증 코드를 Access Token으로 교환
async def exchange_code_for_token(code: str) -> str:
    url = f"{DISCORD_API_URL}/oauth2/token"

    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": DISCORD_REDIRECT_URI,
    }

    auth = (
        DISCORD_CLIENT_ID,
        DISCORD_CLIENT_SECRET,
    )

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            url,
            data=data,
            auth=auth,
        )

        response.raise_for_status()
        token_data = response.json()

    return token_data["access_token"]


# 2. Access Token으로 Discord 사용자 정보 조회
async def get_discord_user(access_token: str) -> dict:
    url = f"{DISCORD_API_URL}/users/@me"

    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            url,
            headers=headers,
        )

        response.raise_for_status()

        user_data = response.json()

    return user_data
