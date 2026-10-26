"""명시적 전용 테스트 URL이 있을 때만 실제 PostgreSQL 행 잠금/DDL을 검증한다."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from backend.app.core.database import Base
from backend.app.models.member import Member
from backend.app.models.post import Post
from backend.app.models.post_like import PostLike
from backend.app.models.post_scrap import PostScrap
from backend.app.models.recruit import Recruit, RecruitMember, RecruitStudyDetail
from backend.app.repositories.recruit_program_repository import ProgramRepository
from backend.app.schemas.recruit_program import ProgramApplication, ProgramCreate
from backend.app.services.recruit_program_service import ProgramService


@pytest.fixture
def postgres(service):
    url = os.getenv("RECRUIT_TEST_DATABASE_URL")
    if os.getenv("RUN_RECRUIT_POSTGRES_TESTS") != "1" or not url:
        pytest.skip("명시적 전용 PostgreSQL 테스트 URL이 없어 실제 잠금 검증 보류")
    base = create_engine(url, hide_parameters=True)
    schema = "recruit_test_" + uuid4().hex
    with base.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    engine = base.execution_options(schema_translate_map={None: schema})
    tables = [
        Member.__table__,
        Post.__table__,
        Recruit.__table__,
        RecruitMember.__table__,
        RecruitStudyDetail.__table__,
        PostLike.__table__,
        PostScrap.__table__,
    ]
    try:
        # 기존 공유 테이블의 빈 테스트 구조만 준비한다. 신규 테이블은 실제 배포 SQL로 만든다.
        Base.metadata.create_all(engine, tables=tables)
        migration = (
            Path(__file__).resolve().parents[3]
            / "database/sql/20261026_recruit_programs.sql"
        ).read_text(encoding="utf-8")
        with base.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as connection:
            connection.exec_driver_sql(f'SET search_path TO "{schema}", pg_catalog')
            # SQL 파일 자체의 BEGIN/COMMIT을 포함해 그대로 실행한다.
            connection.exec_driver_sql(migration)
        with Session(engine) as session:
            session.add_all(
                [
                    Member(member_id=member, member_status="ACTIVE", role_code="MEMBER")
                    for member in [1, 2, 3]
                ]
            )
            session.commit()
        yield engine
    finally:
        # 삭제 대상은 이 테스트가 생성한 UUID 스키마 한 개로 제한한다.
        with base.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        base.dispose()


def test_last_slot_application_serialized(postgres, service, payload):
    now = service.clock()
    with Session(postgres) as session:
        recruit = ProgramService(ProgramRepository(session), clock=lambda: now).create(
            1, ProgramCreate(**payload)
        )["recruit_id"]

    def apply(member):
        with Session(postgres) as session:
            return ProgramService(ProgramRepository(session), clock=lambda: now).apply(
                recruit, member, ProgramApplication()
            )["application_status"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(apply, [2, 3]))
    assert sorted(statuses) == ["ACCEPTED", "WAITING"]
    with Session(postgres) as session:
        program = ProgramRepository(session).load(recruit)
        assert len(program.accepted()) == 2


def test_migration_creates_program_tables_and_active_unique_index(postgres):
    schema = postgres.get_execution_options()["schema_translate_map"][None]
    inspector = inspect(postgres)
    assert {
        "recruit_programs",
        "recruit_applications",
        "recruit_eligibility",
        "recruit_withdrawals",
        "recruit_curricula",
        "recruit_activities",
        "recruit_recognitions",
        "recruit_outbox",
        "recruit_program_commands",
    }.issubset(inspector.get_table_names(schema=schema))
    indexes = inspector.get_indexes("recruit_applications", schema=schema)
    assert any(
        index["name"] == "program_active_member_unique" and index["unique"]
        for index in indexes
    )


def test_summary_projection_and_due_filter_on_postgres(postgres, service, payload):
    """JSON 필드 투영·대기 인원 집계·예약 조건을 실제 PostgreSQL에서 검증한다."""
    now = service.clock()
    with Session(postgres) as session:
        actual = ProgramService(ProgramRepository(session), clock=lambda: now)
        recruit = actual.create(1, ProgramCreate(**payload))["recruit_id"]
        actual.apply(recruit, 2, ProgramApplication())
        actual.apply(
            recruit, 3, ProgramApplication(direct_input={"education": "비공개"})
        )
        summary = actual.list(3)[0]
        assert summary["participant_count"] == 2
        assert summary["waiting_count"] == 1
        assert summary["my_application"]["application_status"] == "WAITING"
        assert actual.repository.pending_ids(now) == []
        cutoff = payload["starts_at"] - timedelta(hours=24)
        assert actual.repository.pending_ids(cutoff) == [recruit]


def test_same_member_concurrent_duplicate_is_rejected(postgres, service, payload):
    from backend.app.domain.recruit_program import PolicyError

    now = service.clock()
    with Session(postgres) as session:
        recruit = ProgramService(ProgramRepository(session), clock=lambda: now).create(
            1, ProgramCreate(**payload)
        )["recruit_id"]

    def apply():
        with Session(postgres) as session:
            try:
                return ProgramService(
                    ProgramRepository(session), clock=lambda: now
                ).apply(recruit, 2, ProgramApplication())["application_status"]
            except PolicyError as error:
                return error.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(apply) for _ in range(2)]
        outcomes = [future.result(timeout=15) for future in futures]
    assert outcomes.count("ACCEPTED") == 1
    assert outcomes.count(409) == 1
    with Session(postgres) as session:
        program = ProgramRepository(session).load(recruit)
        assert len([item for item in program.accepted() if item.member_id == 2]) == 1


def test_main_api_program_flow_on_postgres(postgres, service, payload, monkeypatch):
    """main의 실제 분기/등록과 PostgreSQL 저장을 연결한다. OAuth는 다음 단계 검증이다."""
    import asyncio
    import httpx
    from fastapi import HTTPException
    from app.main import app
    from backend.app.routers import recruit as routes
    from backend.app.routers.recruit_program import build_program_service

    monkeypatch.setenv("ENABLE_RECRUIT_PROGRAMS", "true")

    def authenticated(request, member):
        if member is None:
            raise HTTPException(401, "로그인 필요")
        return member

    monkeypatch.setattr(routes, "get_current_member_id", authenticated)
    with Session(postgres) as session:
        actual = ProgramService(ProgramRepository(session), clock=service.clock)
        app.dependency_overrides[build_program_service] = lambda: actual

        async def verify():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                body = {
                    key: value.isoformat() if hasattr(value, "isoformat") else value
                    for key, value in payload.items()
                }
                response = await client.post(
                    "/api/recruits", json=body, headers={"X-Dev-Member-ID": "1"}
                )
                assert response.status_code == 201, response.text
                recruit = response.json()["recruit_id"]
                public = await client.get(f"/api/recruits/{recruit}")
                assert public.status_code == 200, public.text
                assert public.json()["my_application"] is None
                assert (await client.get("/api/recruits")).json()[0][
                    "recruit_id"
                ] == recruit
                response = await client.post(
                    f"/api/recruits/{recruit}/join", headers={"X-Dev-Member-ID": "2"}
                )
                assert (
                    response.status_code == 200
                    and response.json()["application_status"] == "ACCEPTED"
                )
                response = await client.post(
                    f"/api/recruits/{recruit}/join", headers={"X-Dev-Member-ID": "3"}
                )
                assert (
                    response.status_code == 200
                    and response.json()["application_status"] == "WAITING"
                )
                assert (await client.get(f"/api/recruits/{recruit}/count")).json()[
                    "waiting_count"
                ] == 1

        try:
            asyncio.run(verify())
        finally:
            app.dependency_overrides.pop(build_program_service, None)
