import os
import sys
import asyncio
from pathlib import Path

import httpx
import pytest


BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ["APP_ENV"] = "test"

from app.core.auth import get_current_member_id  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def client():
    app.dependency_overrides[get_current_member_id] = lambda: 1
    class Client:
        def request(self, method, url, **kwargs):
            async def send():
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
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
