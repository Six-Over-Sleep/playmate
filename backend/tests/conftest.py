import os
import sys
import asyncio
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ["APP_ENV"] = "test"
# 단위·HTTP 테스트는 실제 OAuth/공유 DB 설정을 읽지 않고 실행한다.
# 어떤 환경변수가 있어도 항상 가짜 값으로 덮어써 .env의 공용 DB·Discord 설정이 쓰이지 않게 한다.
# 실제 PostgreSQL 통합 테스트는 각 파일의 전용 로컬 테스트 DB 주소로만 접속한다.
# DISCORD_API_URL은 대역이 빠져도 실제 Discord가 아닌 닫힌 로컬 포트로 향하게 하는 안전장치다.
for name, value in {
    "DISCORD_CLIENT_ID": "test",
    "DISCORD_CLIENT_SECRET": "test",
    "DISCORD_REDIRECT_URI": "http://test/callback",
    "DISCORD_API_URL": "http://127.0.0.1:9/discord-blocked",
    "SESSION_SECRET_KEY": "isolated-test-secret",
    "DB_HOST": "127.0.0.1",
    "DB_PORT": "1",
    "DB_USER": "test",
    "DB_PASSWORD": "test",
    "DB_NAME": "test",
}.items():
    os.environ[name] = value

from app.core.auth import get_current_member_id  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client():
    app.dependency_overrides[get_current_member_id] = lambda: 1

    class Client:
        def request(self, method, url, **kwargs):
            async def send():
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://test"
                ) as async_client:
                    return await async_client.request(method, url, **kwargs)

            return asyncio.run(send())

        def get(self, url, **kwargs):
            return self.request("GET", url, **kwargs)

        def post(self, url, **kwargs):
            return self.request("POST", url, **kwargs)

        def patch(self, url, **kwargs):
            return self.request("PATCH", url, **kwargs)

        def delete(self, url, **kwargs):
            return self.request("DELETE", url, **kwargs)

    yield Client()
    app.dependency_overrides.clear()
