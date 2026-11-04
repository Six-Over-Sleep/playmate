"""명시적 전용 테스트 URL이 있을 때만 실제 PostgreSQL 행 잠금/DDL을 검증한다."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
from datetime import timedelta
from threading import Barrier

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
from backend.tests.local_test_db import require_local_test_db_url


@pytest.fixture
def postgres(service):
    url = os.getenv("RECRUIT_TEST_DATABASE_URL")
    if os.getenv("RUN_RECRUIT_POSTGRES_TESTS") != "1" or not url:
        pytest.skip("명시적 전용 PostgreSQL 테스트 URL이 없어 실제 잠금 검증 보류")
    # 연결 전에 로컬(localhost·127.0.0.1·::1)이고 이름에 test가 들어간 일회용 DB인지 확인한다.
    url = require_local_test_db_url("RECRUIT_TEST_DATABASE_URL")
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
            / "database/sql/012_recruit_programs.sql"
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
        detail = actual.detail(recruit, 3)
        assert detail["waiting_count"] == 1
        assert detail["my_application"]["application_status"] == "WAITING"
        roster = actual.members(recruit, 1)
        assert [item["member_id"] for item in roster] == [1, 2]
        assert [item["role"] for item in roster] == ["HOST", "MEMBER"]
        assert all(item["skill_ids"] == [] for item in roster)
        assert detail["members"] == roster
        counts = actual.count(recruit, 1)
        assert counts["current_members"] == 2
        assert counts["waiting_count"] == 1
        assert detail["participation"] == counts
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


def test_concurrent_scheduler_reloads_locked_state_and_deduplicates_events(
    postgres, service, payload
):
    """두 실행기가 같은 대상을 조회해도 잠금 후 전날 사건을 한 번만 저장한다."""
    from sqlalchemy import func, select
    from backend.app.models.recruit_program import OutboxRecord

    now = service.clock()
    with Session(postgres) as session:
        actual = ProgramService(ProgramRepository(session), clock=lambda: now)
        recruit = actual.create(1, ProgramCreate(**payload))["recruit_id"]
        actual.apply(recruit, 2, ProgramApplication())
    cutoff = payload["starts_at"] - timedelta(hours=24)
    barrier = Barrier(2, timeout=15)

    def run():
        with Session(postgres) as session:
            repository = ProgramRepository(session)
            original = repository.pending_ids

            def both_read(moment):
                ids = original(moment)
                barrier.wait()
                return ids

            repository.pending_ids = both_read
            failures = []
            count = ProgramService(repository, clock=lambda: cutoff).tick(
                on_error=failures.append
            )
            return count, failures

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        assert [future.result(timeout=30) for future in futures] == [(1, []), (1, [])]
    with Session(postgres) as session:
        assert session.scalar(select(func.count()).select_from(OutboxRecord)) == 1
        actual = ProgramService(ProgramRepository(session), clock=lambda: cutoff)
        assert actual.tick() == 0
        assert actual.repository.load(recruit).lifecycle_status != "IN_PROGRESS"
        actual.clock = lambda: payload["starts_at"]
        assert actual.tick() == 1
        assert actual.repository.load(recruit).lifecycle_status == "IN_PROGRESS"
        actual.clock = lambda: payload["ends_at"]
        assert actual.tick() == 1
        assert actual.tick() == 0
        assert actual.repository.load(recruit).lifecycle_status == "COMPLETED"
        assert session.scalar(select(func.count()).select_from(OutboxRecord)) == 2


def test_scheduler_cli_once_uses_existing_database_configuration(
    postgres, service, payload
):
    """실제 별도 프로세스가 전용 스키마만 처리하고 반복 실행에도 중복 저장하지 않는다."""
    import subprocess
    import sys

    schema = postgres.get_execution_options()["schema_translate_map"][None]
    with Session(postgres) as session:
        actual = ProgramService(ProgramRepository(session), clock=service.clock)
        recruit = actual.create(1, ProgramCreate(**payload))["recruit_id"]
        actual.apply(recruit, 2, ProgramApplication())
    url = postgres.url
    environment = {
        **os.environ,
        "DB_HOST": url.host,
        "DB_PORT": str(url.port or 5432),
        "DB_NAME": url.database,
        "DB_USER": url.username,
        "DB_PASSWORD": url.password,
        "DB_SSLMODE": "disable",
        "PGOPTIONS": f"-c search_path={schema},pg_catalog",
        "ENABLE_RECRUIT_PROGRAMS": "true",
        "DISCORD_CLIENT_ID": "isolated-test",
        "DISCORD_CLIENT_SECRET": "isolated-test",
        "DISCORD_REDIRECT_URI": "http://test/callback",
        "SESSION_SECRET_KEY": "isolated-test",
    }
    command = [
        sys.executable,
        "-m",
        "backend.app.jobs.run_recruit_scheduler",
        "--once",
    ]
    for _ in range(2):
        result = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[3],
            env=environment,
            capture_output=True,
            timeout=30,
        )
        assert result.returncode == 0, "예약 실행 CLI가 실패했습니다."
    with Session(postgres) as session:
        # 실제 현재 시각에 따라 도래한 상태까지만 진행한다.
        from datetime import datetime, timezone

        expected = ProgramRepository(session).load(recruit)
        expected.tick(datetime.now(timezone.utc))
        assert (
            ProgramRepository(session).load(recruit).lifecycle_status
            == expected.lifecycle_status
        )
    invalid = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[3],
        env={**environment, "RECRUIT_SCHEDULER_INTERVAL_SECONDS": "0"},
        capture_output=True,
        timeout=30,
    )
    assert invalid.returncode == 2


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
                anonymous = await client.get(f"/api/recruits/{recruit}")
                assert anonymous.status_code == 401, anonymous.text
                public = await client.get(
                    f"/api/recruits/{recruit}", headers={"X-Dev-Member-ID": "3"}
                )
                assert public.status_code == 200, public.text
                assert public.json()["my_application"] is None
                assert (await client.get(
                    "/api/recruits", headers={"X-Dev-Member-ID": "3"}
                )).json()[0][
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
                assert (await client.get(
                    f"/api/recruits/{recruit}/count", headers={"X-Dev-Member-ID": "1"}
                )).json()[
                    "waiting_count"
                ] == 1

        try:
            asyncio.run(verify())
        finally:
            app.dependency_overrides.pop(build_program_service, None)


def test_issue88_catalog_migration_and_project_roundtrip(postgres, service):
    from backend.app.services.recruit_skill_catalog import DatabaseSkillCatalog
    migration = (Path(__file__).resolve().parents[3] / "database/sql/021_recruit_skills.sql").read_text(encoding="utf-8")
    schema = postgres.get_execution_options()["schema_translate_map"][None]
    with postgres.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.exec_driver_sql(f'SET search_path TO "{schema}", pg_catalog')
        connection.exec_driver_sql(migration)
        connection.exec_driver_sql(migration)  # safe to apply twice; stable IDs
    with Session(postgres) as session:
        catalog = DatabaseSkillCatalog(session)
        options = catalog.options()
        assert len(options) == 5 and len({row['skill_id'] for row in options}) == 5
        skill = options[0]['skill_id']
        now = service.clock()
        start = now + timedelta(days=7)
        api = ProgramService(ProgramRepository(session), catalog=catalog, clock=lambda: now)
        created = api.create(1, ProgramCreate(title='실제 DB 프로젝트', body='기술 배정', category='project',
            capacity=3, starts_at=start, ends_at=start+timedelta(days=30), required_skill_ids=[skill],
            creator_application=ProgramApplication(skill_ids=[skill])))
        session.expire_all()
        detail = api.detail(created['recruit_id'], 1)
        assert detail['required_skills'][0]['name'] == options[0]['name']
        assert detail['my_application']['skill_ids'] == [skill]


def test_issue88_regular_study_postgres_roundtrip(postgres, service, payload):
    from zoneinfo import ZoneInfo
    from backend.app.schemas.recruit_program import ProgramEdit
    start = service.clock() + timedelta(days=7)
    local = start.astimezone(ZoneInfo('Asia/Seoul'))
    data = {**payload, 'recruit_mode': 'regular', 'starts_at': start, 'ends_at': start+timedelta(days=28),
            'deadline_at': start-timedelta(hours=24), 'meeting_start': None, 'meeting_end': None,
            'regular_days': [['월','화','수','목','금','토','일'][local.weekday()]],
            'regular_time': local.time().replace(tzinfo=None), 'regular_start_date': local.date()}
    with Session(postgres) as session:
        api = ProgramService(ProgramRepository(session), clock=service.clock)
        created = api.create(1, ProgramCreate(**data))
        rid = created['recruit_id']
        api.edit(rid, 1, ProgramEdit(title='수정된 정기 스터디', starts_at=start+timedelta(days=7), ends_at=start+timedelta(days=35)))
    with Session(postgres) as session:
        api = ProgramService(ProgramRepository(session), clock=service.clock)
        detail = api.detail(rid, 1)
        assert detail['title'] == '수정된 정기 스터디'
        assert detail['regular_start_date'] == (local+timedelta(days=7)).date().isoformat()
        assert detail['regular_days'] == data['regular_days']
        assert detail['participant_count'] == 1


@pytest.fixture
def single_connection_catalog(postgres):
    """실제 서버와 같은 연결 1개 제한으로 기술 사전 접근을 검증한다."""
    from backend.app.models.recruit_program import RecruitSkill

    schema = postgres.get_execution_options()["schema_translate_map"][None]
    limited = create_engine(
        postgres.url,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.2,
        execution_options={"schema_translate_map": {None: schema}},
    )
    try:
        RecruitSkill.__table__.create(limited)
        with Session(limited) as session:
            session.add_all([
                RecruitSkill(skill_id=701, skill_code="PYTHON", name="Python"),
                RecruitSkill(skill_id=702, skill_code="REACT", name="React"),
            ])
            session.commit()
        yield limited
    finally:
        limited.dispose()


def test_catalog_reuses_checked_out_connection(single_connection_catalog):
    """회원 조회가 연결을 점유한 뒤에도 검사·조회가 추가 연결을 요구하지 않는다."""
    from backend.app.domain.recruit_program import PolicyError
    from backend.app.services.recruit_skill_catalog import DatabaseSkillCatalog

    with Session(single_connection_catalog) as session:
        session.get(Member, 1)
        catalog = DatabaseSkillCatalog(session)
        assert {item["skill_id"] for item in catalog.options()} == {701, 702}
        catalog.validate([701, 702])
        assert catalog.names([701, 702]) == {"701": "Python", "702": "React"}
        for invalid in ([999], [701, 701]):
            with pytest.raises(PolicyError) as error:
                catalog.validate(invalid)
            assert error.value.status == 422


def test_project_roundtrip_with_one_connection(single_connection_catalog, service):
    """생성·수정 트랜잭션 안에서 기술을 검사하고 새 세션으로 저장 결과를 읽는다."""
    from backend.app.schemas.recruit_program import ProgramEdit
    from backend.app.services.recruit_skill_catalog import DatabaseSkillCatalog

    start = service.clock() + timedelta(days=7)
    with Session(single_connection_catalog) as session:
        actual = ProgramService(
            ProgramRepository(session),
            catalog=DatabaseSkillCatalog(session),
            clock=service.clock,
        )
        created = actual.create(1, ProgramCreate(
            title="연결 제한 프로젝트", body="기술 저장 검증", category="project",
            capacity=3, starts_at=start, ends_at=start + timedelta(days=30),
            required_skill_ids=[701],
            creator_application=ProgramApplication(skill_ids=[701]),
        ))
        recruit_id = created["recruit_id"]
        actual.edit(recruit_id, 1, ProgramEdit(required_skill_ids=[701, 702]))
    with Session(single_connection_catalog) as session:
        actual = ProgramService(
            ProgramRepository(session),
            catalog=DatabaseSkillCatalog(session),
            clock=service.clock,
        )
        detail = actual.detail(recruit_id, 1)
        assert detail["category"] == "project"
        assert session.get(Recruit, recruit_id).category == "project"
        assert {item["name"] for item in detail["required_skills"]} == {"Python", "React"}
        assert detail["my_application"]["skill_ids"] == [701]


def test_catalog_missing_table_uses_existing_connection(postgres):
    """스키마에 사전이 없으면 다른 스키마를 읽거나 DB 오류를 숨기지 않고 안내한다."""
    from backend.app.domain.recruit_program import PolicyError
    from backend.app.services.recruit_skill_catalog import DatabaseSkillCatalog

    with Session(postgres) as session:
        session.get(Member, 1)
        with pytest.raises(PolicyError) as error:
            DatabaseSkillCatalog(session).options()
        assert error.value.status == 503


@pytest.mark.parametrize("mode", ["short", "regular"])
def test_configuration_conversion_postgres(single_connection_catalog, service, payload, mode):
    """실제 외래키·배열·연결 1개 조건에서 종류와 정기/단기를 바꾸고 재조회한다."""
    from backend.app.models.recruit import (
        RecruitSportsDetail, RecruitGameDetail, RecruitGroupBuyDetail,
    )
    from backend.app.schemas.recruit_program import ProgramEdit
    from backend.app.services.recruit_dispatch_service import RecruitDispatchService
    from backend.app.services.recruit_skill_catalog import DatabaseSkillCatalog
    from backend.tests.recruit.test_configuration_edit import category_payload, regular_fields

    for model in (RecruitSportsDetail, RecruitGameDetail, RecruitGroupBuyDetail):
        model.__table__.create(single_connection_catalog)
    with Session(single_connection_catalog) as session:
        actual = ProgramService(
            ProgramRepository(session), catalog=DatabaseSkillCatalog(session),
            clock=service.clock,
        )
        dispatch = RecruitDispatchService(
            actual, True, lambda: 1, lambda: 1, lambda: 1, lambda: 1,
        )
        recruit_id = actual.create(1, ProgramCreate(**payload))["recruit_id"]
        post_id = actual.repository.basic_detail(recruit_id)["post_id"]
        session.add(PostLike(post_id=post_id, member_id=2))
        session.commit()
        for category in ("project", "sports", "game", "group_buy", "study"):
            data = category_payload(payload, category)
            if mode == "regular" and category != "group_buy":
                data.update(regular_fields(payload["starts_at"]))
                data.update(meeting_start=None, meeting_end=None)
            if category == "project":
                data["required_skill_ids"] = [701]
                data["creator_application"]["skill_ids"] = [701]
            dispatch.update(recruit_id, data)
            session.expire_all()
            assert dispatch.detail(recruit_id)["category"] == category
            assert actual.repository.basic_detail(recruit_id)["post_id"] == post_id
            assert session.get(PostLike, (post_id, 2)) is not None
        actual.edit(recruit_id, 1, ProgramEdit(**regular_fields(payload["starts_at"])))
    with Session(single_connection_catalog) as session:
        actual = ProgramService(ProgramRepository(session), clock=service.clock)
        detail = actual.detail(recruit_id, 1)
        assert detail["category"] == "study"
        assert detail["recruit_mode"] == "regular"
        assert detail["regular_days"]
        actual.edit(recruit_id, 1, ProgramEdit(recruit_mode="short"))
        session.expire_all()
        assert actual.detail(recruit_id, 1)["regular_days"] is None


def test_category_conversion_and_join_serialize(postgres, service, payload, monkeypatch):
    """기존 모임 신청과 프로젝트 전환이 겹쳐도 신청 조건을 우회하지 않는다."""
    from sqlalchemy import text
    from fastapi import HTTPException
    from backend.app.domain.recruit_program import PolicyError
    from backend.app.models.recruit import (
        RecruitSportsDetail, RecruitGameDetail, RecruitGroupBuyDetail,
    )
    from backend.app.schemas.recruit import RecruitCreate
    from backend.app.services import recruit as legacy, recruit_member
    from backend.app.services.recruit_dispatch_service import RecruitDispatchService
    from backend.tests.recruit.test_configuration_edit import category_payload

    monkeypatch.setattr(
        recruit_member, "kst_now",
        lambda: service.clock().replace(tzinfo=None) + timedelta(hours=9),
    )
    for model in (RecruitSportsDetail, RecruitGameDetail, RecruitGroupBuyDetail):
        model.__table__.create(postgres)
    with Session(postgres) as session:
        recruit_id = legacy.create_recruit(
            session, RecruitCreate(**category_payload(payload, "sports")), 1
        )["recruit_id"]
    barrier = Barrier(2)

    def run(convert):
        with Session(postgres) as session:
            session.execute(text("SET LOCAL lock_timeout = '3s'"))
            actual = ProgramService(
                ProgramRepository(session), catalog=service.catalog, clock=service.clock,
            )
            member = 1 if convert else 2
            dispatch = RecruitDispatchService(
                actual, True, lambda: member, lambda: member,
                lambda: member, lambda: member,
            )
            barrier.wait(timeout=5)
            try:
                if convert:
                    dispatch.update(recruit_id, category_payload(payload, "project"))
                else:
                    dispatch.apply(recruit_id, None)
                return 200
            except (PolicyError, HTTPException) as error:
                return getattr(error, "status", None) or error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, convert) for convert in (True, False)]
        results = [future.result(timeout=10) for future in futures]
    assert all(status in {200, 400, 409, 422} for status in results)
    with Session(postgres) as session:
        recruit = session.get(Recruit, recruit_id)
        if recruit.category == "project":
            member = session.get(RecruitMember, (recruit_id, 2))
            assert member is None or member.status != "JOINED"
        else:
            assert recruit.category == "sports"
            assert session.get(RecruitMember, (recruit_id, 2)).status == "JOINED"
