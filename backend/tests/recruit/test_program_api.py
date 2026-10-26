import asyncio

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from backend.app.core.auth import get_current_member_id
from backend.app.routers.recruit_program import get_service, router


@pytest.fixture
def api(service):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_service] = lambda: service
    app.dependency_overrides[get_current_member_id] = lambda: 1

    class Client:
        def request(self, method, path, **kwargs):
            async def send():
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app), base_url="http://test"
                ) as client:
                    return await client.request(method, path, **kwargs)

            return asyncio.run(send())

        def post(self, path, **kwargs):
            return self.request("POST", path, **kwargs)

        def patch(self, path, **kwargs):
            return self.request("PATCH", path, **kwargs)

        def get(self, path, **kwargs):
            return self.request("GET", path, **kwargs)

    yield Client(), app


def request_payload(payload):
    return {
        key: value.isoformat() if hasattr(value, "isoformat") else value
        for key, value in payload.items()
    }


def test_create_contract_and_second_member_authority(api, payload):
    client, app = api
    response = client.post("/api/recruits", json=request_payload(payload))
    assert response.status_code == 201
    assert set(response.json()) == {"recruit_id", "post_id"}
    recruit = response.json()["recruit_id"]
    app.dependency_overrides[get_current_member_id] = lambda: 2
    assert (
        client.patch(f"/api/recruits/{recruit}", json={"title": "도용"}).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/recruits/{recruit}/join", json={"career_item_ids": ["1"]}
        ).status_code
        == 422
    )
    result = client.post(f"/api/recruits/{recruit}/join", json={})
    assert result.status_code == 200
    assert result.json()["member_id"] == 2
    assert result.json()["application_status"] == "ACCEPTED"
    assert client.post(f"/api/recruits/{recruit}/join", json={}).status_code == 409
    assert client.get(f"/api/recruits/{recruit}").json()["participant_count"] == 2


def test_missing_auth_is_not_replaced_with_test_member(api, payload):
    client, app = api

    def unauthorized():
        raise HTTPException(401, "로그인 필요")

    app.dependency_overrides[get_current_member_id] = unauthorized
    assert (
        client.post("/api/recruits", json=request_payload(payload)).status_code == 401
    )


def test_schema_rejects_tampered_identity_and_bad_schedule(api, payload):
    client, _ = api
    data = request_payload(payload)
    data["creator_type"] = "ADMIN"
    assert client.post("/api/recruits", json=data).status_code == 422
    data.pop("creator_type")
    data["ends_at"] = data["starts_at"]
    assert client.post("/api/recruits", json=data).status_code == 422
