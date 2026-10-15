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
for name, value in {
    "DISCORD_CLIENT_ID": "test",
    "DISCORD_CLIENT_SECRET": "test",
    "DISCORD_REDIRECT_URI": "http://test/callback",
    "SESSION_SECRET_KEY": "isolated-test-secret",
    "DB_HOST": "127.0.0.1",
    "DB_PORT": "1",
    "DB_USER": "test",
    "DB_PASSWORD": "test",
    "DB_NAME": "test",
}.items():
    if os.getenv("RUN_POSTGRES_INTEGRATION") != "1":
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
