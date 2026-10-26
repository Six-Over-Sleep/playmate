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
    path = (
        Path(__file__).resolve().parents[3]
        / "database/sql/20261026_recruit_programs.sql"
    )
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
