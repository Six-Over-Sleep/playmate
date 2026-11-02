import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from backend.app.core.database import Base
from backend.app.schemas.recruit_program import ProgramApplication, ProgramCreate
from backend.app.services.recruit_program_service import ProgramService
from backend.app.services.recruit_dispatch_service import RecruitDispatchService
from backend.app.models.recruit_program import ApplicationRecord


def test_list_is_bare_array_and_does_not_query_per_group(service, payload):
    def query_count():
        counter = []

        def capture(*args):
            counter.append(1)

        engine = service.repository.session.get_bind()
        event.listen(engine, "before_cursor_execute", capture)
        try:
            result = service.list(2)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert isinstance(result, list)
        assert all("direct_input" not in str(item["my_application"]) for item in result)
        return len(counter)

    service.create(1, ProgramCreate(**payload))
    first = query_count()
    for _ in range(5):
        service.create(1, ProgramCreate(**payload))
    assert query_count() == first


@pytest.mark.parametrize(
    "endpoint,limit", [("detail", 3), ("members", 3), ("count", 3)]
)
def test_read_endpoints_avoid_repeated_program_and_application_reads(
    service, payload, endpoint, limit
):
    """실제 분기 포함 쿼리 상한을 검사한다. 인증 DB 쿼리는 이 테스트 범위 밖이다."""
    recruit = service.create(1, ProgramCreate(**payload))["recruit_id"]
    service.apply(recruit, 2, ProgramApplication())
    service.apply(recruit, 3, ProgramApplication())
    session = service.repository.session
    # 취소 이력에 큰 커리어 자료가 있어도 인원/참여자 조회는 적재하지 않아야 한다.
    session.add(
        ApplicationRecord(
            recruit_id=recruit,
            member_id=4,
            sequence=4,
            submitted_at=service.clock(),
            status="CANCELED",
            payload={"direct_input": {"education": "비공개" * 1000}},
        )
    )
    session.commit()
    session.expunge_all()
    service.repository._schema_ready = None
    facade = RecruitDispatchService(
        service, True, lambda: 1, lambda: 1, lambda: 1, lambda: 1
    )
    statements = []

    def capture(connection, cursor, sql, parameters, context, many):
        if sql.lstrip().lower().startswith("select"):
            statements.append(sql.lower())

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = getattr(facade, endpoint)(recruit)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) <= limit
    assert "비공개" not in str(result)
    if endpoint == "detail":
        assert result["participant_count"] == 2
        assert result["waiting_count"] == 1
        assert sum("recruit_programs.details" in sql for sql in statements) == 1
        assert result["members"] == service.members(recruit, 1)
        assert result["participation"] == service.count(recruit, 1)
    elif endpoint == "members":
        assert [item["member_id"] for item in result] == [1, 2]
        assert [item["role"] for item in result] == ["HOST", "MEMBER"]
        assert not any("direct_input" in sql for sql in statements)
    else:
        assert result["current_members"] == 2
        assert result["waiting_count"] == 1
        assert not any("recruit_applications.payload" in sql for sql in statements)


def test_empty_admin_roster_and_counts_keep_missing_and_deleted_checks(
    service, payload
):
    from backend.app.domain.recruit_program import PolicyError
    from backend.app.models.post import Post
    from backend.app.models.recruit import Recruit

    recruit = service.create(9, ProgramCreate(**payload))["recruit_id"]
    assert service.members(recruit, None) == []
    counts = service.count(recruit, None)
    assert counts["current_members"] == counts["waiting_count"] == 0
    assert counts["remaining"] == payload["capacity"]
    empty = service.detail(recruit, None)
    assert empty["members"] == []
    assert empty["participation"] == counts
    for read in (service.detail, service.members, service.count):
        with pytest.raises(PolicyError) as error:
            read(recruit + 100, None)
        assert error.value.status == 404
    session = service.repository.session
    session.get(Post, session.get(Recruit, recruit).post_id).post_status = "DELETED"
    session.commit()
    for read in (service.detail, service.members, service.count):
        with pytest.raises(PolicyError) as error:
            read(recruit, None)
        assert error.value.status == 404


@pytest.mark.parametrize("member_id", [None, 1, 3, 4])
def test_bundle_single_select_preserves_counts_privacy_and_own_state(
    service, payload, member_id
):
    from backend.app.models.post_like import PostLike
    from backend.app.models.post_scrap import PostScrap
    from backend.app.models.recruit_program import EligibilityRecord

    recruit = service.create(1, ProgramCreate(**payload))["recruit_id"]
    for member in (2, 3, 4):
        service.apply(
            recruit,
            member,
            ProgramApplication(direct_input={"education": "비공개 커리어"}),
        )
    session = service.repository.session
    post_id = service.repository.basic_detail(recruit)["post_id"]
    session.add_all(
        [
            PostLike(post_id=post_id, member_id=1),
            PostLike(post_id=post_id, member_id=2),
            PostScrap(post_id=post_id, member_id=3),
            EligibilityRecord(member_id=3, withdrawal_count=3),
        ]
    )
    session.commit()
    session.expunge_all()
    queries = []

    def capture(connection, cursor, sql, parameters, context, many):
        queries.append(sql)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        bundle = service.repository.detail_bundle(recruit, member_id)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(queries) == 1
    assert "direct_input" not in queries[0]
    assert bundle["counts"] == {"capacity": 2, "accepted": 2, "waiting": 2}
    assert [item["member_id"] for item in bundle["members"]] == [1, 2]
    visible = {item.member_id for item in bundle["program"].applications}
    assert visible == {1, 2} | ({member_id} if member_id in {3, 4} else set())
    response = service.detail(recruit, member_id)
    assert response["like_count"] == 2
    assert response["liked_by_me"] == (member_id == 1)
    assert response["scrapped_by_me"] == (member_id == 3)
    assert response["participation"]["waiting_count"] == 2
    assert "비공개 커리어" not in str(response)
    if member_id is None:
        assert response["my_application"] is None
        assert response["my_eligibility"] is None
        assert not any(response["permissions"].values())
    else:
        expected = "WAITING" if member_id in {3, 4} else "ACCEPTED"
        assert response["my_application"]["application_status"] == expected
        assert response["my_eligibility"]["is_restricted"] == (member_id == 3)


def test_default_catalog_fails_explicitly_without_writing_project(service, payload):
    payload.update(
        category="project",
        required_skill_ids=[101],
        creator_application={"skill_ids": [101]},
    )
    unavailable = ProgramService(service.repository, clock=service.clock)
    from backend.app.domain.recruit_program import PolicyError

    with pytest.raises(PolicyError) as error:
        unavailable.create(1, ProgramCreate(**payload))
    assert error.value.status == 503
    assert unavailable.list(1) == []


def test_regular_schedule_and_contract_examples(service, payload):
    from datetime import timedelta

    payload.update(
        recruit_mode="regular",
        regular_days=["금"],
        regular_time="09:00:00",
        regular_start_date="2026-10-30",
    )
    # fixture 시작은 UTC 00:00, 한국 09:00이다.
    data = ProgramCreate(**payload)
    recruit = service.create(1, data)["recruit_id"]
    detail = service.detail(recruit, 1)
    assert detail["meeting_start"] is None
    assert detail["regular_start_date"] == "2026-10-30"
    payload["regular_time"] = "10:00:00"
    with pytest.raises(ValidationError):
        ProgramCreate(**payload)


def test_members_exclude_waiters_and_private_career(service, payload):
    recruit = service.create(1, ProgramCreate(**payload))["recruit_id"]
    service.apply(recruit, 2, ProgramApplication(direct_input={"education": "비공개"}))
    service.apply(recruit, 3, ProgramApplication())
    members = service.members(recruit, 1)
    assert [item["member_id"] for item in members] == [1, 2]
    assert "비공개" not in json.dumps(members, ensure_ascii=False)
    assert service.count(recruit, 1)["waiting_count"] == 1


def test_postgres_migration_matches_metadata_without_connecting():
    path = Path(__file__).resolve().parents[3] / "database/sql/012_recruit_programs.sql"
    sql = path.read_text(encoding="utf-8")

    def normalized(value):
        return re.sub(r"\s+", " ", value).strip()

    names = {
        "recruit_programs",
        "recruit_applications",
        "recruit_eligibility",
        "recruit_withdrawals",
        "recruit_curricula",
        "recruit_activities",
        "recruit_recognitions",
        "recruit_outbox",
        "recruit_program_commands",
    }
    for table in Base.metadata.sorted_tables:
        if table.name not in names:
            continue
        assert normalized(
            str(CreateTable(table).compile(dialect=postgresql.dialect()))
        ) in normalized(sql)
        for index in table.indexes:
            assert normalized(
                str(CreateIndex(index).compile(dialect=postgresql.dialect()))
            ) in normalized(sql)
    assert "DELETE FROM" not in sql and "DROP TABLE" not in sql


def test_deleted_legacy_post_is_hidden_and_not_processed(service, payload):
    from backend.app.models.post import Post
    from backend.app.domain.recruit_program import PolicyError

    result = service.create(1, ProgramCreate(**payload))
    post = service.repository.session.get(Post, result["post_id"])
    post.post_status = "DELETED"
    service.repository.session.commit()
    assert service.list(1) == []
    assert service.tick() == 0
    with pytest.raises(PolicyError) as error:
        service.detail(result["recruit_id"], 1)
    assert error.value.status == 404
