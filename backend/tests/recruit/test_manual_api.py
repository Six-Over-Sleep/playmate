"""사람이 사용할 격리 Swagger도 실제 신규 서비스/라우터로 동작하는지 확인한다."""

import asyncio
import os

import httpx

from backend.tests.recruit.manual_api import create_app


def test_manual_sandbox_join_waiting_and_clock(monkeypatch):
    for name in [
        "APP_ENV",
        "DISCORD_CLIENT_ID",
        "DISCORD_CLIENT_SECRET",
        "DISCORD_REDIRECT_URI",
        "SESSION_SECRET_KEY",
        "DB_HOST",
        "DB_PORT",
        "DB_USER",
        "DB_PASSWORD",
        "DB_NAME",
        "DB_SSLMODE",
        "DATABASE_URL",
    ]:
        # factory가 바꾸는 프로세스 환경만 테스트 종료 시 원래 값으로 복구한다.
        monkeypatch.setenv(name, os.environ.get(name, ""))
    app = create_app()

    async def verify():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            guide = (await client.get("/__test__/guide")).json()
            assert guide["mode"] == "ISOLATED_SQLITE"
            assert guide["real_login_tested"] is False
            schema = (await client.get("/openapi.json")).json()
            assert "격리" in schema["info"]["title"]
            assert "X-Test-Member-ID" in str(schema)
            project = guide["project_id"]
            study = guide["study_id"]
            joined = await client.post(
                f"/api/recruits/{project}/join",
                json=guide["project_join_example"],
                headers={"X-Test-Member-ID": "2"},
            )
            assert (
                joined.status_code == 200
                and joined.json()["application_status"] == "ACCEPTED"
            )
            assert (
                await client.post(
                    f"/api/recruits/{study}/join", headers={"X-Test-Member-ID": "2"}
                )
            ).status_code == 200
            waiter = await client.post(
                f"/api/recruits/{study}/join", headers={"X-Test-Member-ID": "3"}
            )
            assert waiter.json()["application_status"] == "WAITING"
            await client.delete(
                f"/api/recruits/{study}/join", headers={"X-Test-Member-ID": "2"}
            )
            detail = (
                await client.get(
                    f"/api/recruits/{study}", headers={"X-Test-Member-ID": "3"}
                )
            ).json()
            assert detail["my_application"]["application_status"] == "ACCEPTED"
            assert (
                await client.post("/__test__/advance", json={"hours": 72})
            ).status_code == 200
            detail = (await client.get(f"/api/recruits/{project}")).json()
            assert detail["leader_member_id"] == 1
            assert detail["permissions"]["can_cancel_project"] is False
            assert (
                await client.post("/__test__/advance", json={"hours": 24})
            ).status_code == 200
            detail = (await client.get(f"/api/recruits/{project}")).json()
            assert detail["lifecycle_status"] == "IN_PROGRESS"

    try:
        asyncio.run(verify())
    finally:
        app.state.sandbox_engine.dispose()
