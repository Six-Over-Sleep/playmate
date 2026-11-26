"""052 source preflight and career storage/authorization regressions; no DB."""

from contextlib import contextmanager
import json

import pytest
from fastapi import HTTPException

from app.repositories import career_repository as repo
from app.services import career_service as service
from app.schemas.career import CareerLabResolveUpdate, CareerLabVoteCreate
from backend.scripts.check_compat_view_references import find_references


class Cursor:
    def __init__(self, rows=(), rowcount=1):
        self.rows = iter(rows)
        self.calls = []
        self.rowcount = rowcount

    def execute(self, sql, params=None):
        assert sql.count("%s") == len(params or ())
        self.calls.append((" ".join(sql.split()), params))

    def fetchone(self):
        return next(self.rows)

    def fetchall(self):
        return next(self.rows)


def test_application_has_no_compatibility_view_references():
    assert find_references() == []


def test_discord_bot_compatibility_view_scanner(tmp_path, monkeypatch):
    from backend.scripts import check_compat_view_references as checker

    source = (
        tmp_path / "playmate-discord-bot"
        / "repositories" / "legacy.py"
    )
    source.parent.mkdir(parents=True)
    source.write_text("SELECT * FROM career_posts", encoding="utf-8")

    fixture = (
        tmp_path / "playmate-discord-bot"
        / "tests" / "test_legacy.py"
    )
    fixture.parent.mkdir(parents=True)
    fixture.write_text("SELECT * FROM career_posts", encoding="utf-8")

    monkeypatch.setattr(checker, "ROOT", tmp_path)

    references = checker.find_references()

    assert len(references) == 1
    assert references[0].endswith(
        "legacy.py:1: SELECT * FROM career_posts"
    )


@pytest.mark.parametrize("kind,category", [
    ("review", "reviews"), ("talk", "talk"), ("lounge", "lounge"), ("lab", "lab"),
])
def test_create_update_and_author_lock_use_consolidated_storage(kind, category):
    cursor = Cursor([{"post_id": 7}])
    assert getattr(repo, f"create_{kind}")(cursor, 2, {
        "title": "title", "body": "body", "subcategory_code": "test",
    }) == 7
    assert "INSERT INTO public.posts" in cursor.calls[0][0]
    assert "INSERT INTO public.career" in cursor.calls[1][0]
    assert cursor.calls[1][1][1] == category
    assert isinstance(json.loads(cursor.calls[1][1][3]), dict)

    cursor = Cursor([{"author_member_id": 2}])
    assert getattr(repo, f"get_{kind}_author_for_update")(cursor, 7) == 2
    sql, params = cursor.calls[0]
    assert "FOR UPDATE OF p" in sql and "p.deleted_at IS NULL" in sql
    assert f"cp.category_code = '{category}'" in sql and params == (7,)

    cursor = Cursor([{"post_id": 7}, {"post_id": 7}])
    getattr(repo, f"update_{kind}")(cursor, 7, {"body": "changed", "is_anonymous": False})
    assert "FOR UPDATE OF p" in cursor.calls[0][0]
    assert "FROM public.career" in cursor.calls[1][0] and "FOR UPDATE" in cursor.calls[1][0]
    assert "UPDATE public.posts" in cursor.calls[2][0]

    cursor = Cursor(rowcount=0)
    assert not getattr(repo, f"delete_{kind}")(cursor, 7, 99)
    assert "author_member_id = %s" in cursor.calls[0][0]
    assert f"category_code = '{category}'" in cursor.calls[0][0]


@pytest.mark.parametrize("kind", ["review", "talk", "lounge", "lab"])
def test_missing_detail_and_empty_list_contract(kind):
    cursor = Cursor([None])
    assert getattr(repo, f"get_{kind}")(cursor, 7, 2) is None
    plural = {"review": "reviews", "talk": "talks", "lounge": "lounges", "lab": "labs"}[kind]
    cursor = Cursor([{"total": 0}, []])
    result = getattr(repo, f"list_{plural}")(cursor, 2, q="query", page=2, page_size=5)
    assert result == {"items": [], "total": 0, "page": 2, "page_size": 5}
    assert "p.is_anonymous" in cursor.calls[1][0]


def test_attachment_operations_always_isolate_scope():
    calls = [
        (repo.list_talk_attachments, (7,), []),
        (repo.get_next_talk_attachment_order, (7,), {"display_order": 1}),
        (repo.get_talk_attachment, (7, 8), None),
        (repo.delete_talk_attachment, (7, 8), None),
        (repo.create_talk_attachment, (7, "a.png", "/tmp/a", "IMAGE", "image/png", 12, 1), {}),
    ]
    for function, args, result in calls:
        cursor = Cursor([result])
        function(cursor, *args)
        sql = cursor.calls[0][0]
        assert "post_attachments" in sql and "attachment_scope" in sql and "'CAREER_TALK'" in sql


def test_vote_duplicate_and_resolved_non_question_are_rejected():
    cursor = Cursor([None])
    assert repo.create_lab_vote(cursor, 7, 2, 11) is False
    assert "ON CONFLICT (post_id, member_id) DO NOTHING" in cursor.calls[0][0]
    cursor = Cursor([None])
    assert repo.update_lab_resolved(cursor, 7, True) is False
    assert len(cursor.calls) == 1
    assert "details ->> 'post_type' = 'QUESTION'" in cursor.calls[0][0]


def test_resolved_change_checks_owner_before_writing(monkeypatch):
    cursor = Cursor([{"author_member_id": 1}])

    @contextmanager
    def transaction(**kwargs):
        assert kwargs == {"commit": True}
        yield cursor

    monkeypatch.setattr(service, "db_cursor", transaction)
    with pytest.raises(HTTPException) as error:
        service.update_lab_resolved(7, CareerLabResolveUpdate(is_resolved=True), 99)
    assert error.value.status_code == 403
    assert len(cursor.calls) == 1 and "FOR UPDATE OF p" in cursor.calls[0][0]


def test_removed_orm_models_cannot_recreate_views():
    from backend.app.core.database import Base
    from backend.app.models import recruit, recruit_program  # noqa: F401
    from backend.scripts.check_compat_view_references import COMPAT_VIEWS
    assert not set(COMPAT_VIEWS).intersection(Base.metadata.tables)


@pytest.mark.parametrize("rows,status", [
    ([None], 404),
    ([{"post_type": "QUESTION"}], 400),
    ([{"post_type": "DISCUSSION"}, None], 400),
    ([{"post_type": "DISCUSSION"}, {"exists": 1}, None], 409),
])
def test_vote_service_validates_before_insert_and_keeps_http_contract(monkeypatch, rows, status):
    cursor = Cursor(rows)

    @contextmanager
    def transaction(**kwargs):
        assert kwargs == {"commit": True}
        yield cursor

    monkeypatch.setattr(service, "db_cursor", transaction)
    with pytest.raises(HTTPException) as error:
        service.vote_lab(7, CareerLabVoteCreate(option_id=11), 2)
    assert error.value.status_code == status
    assert "FOR UPDATE OF p" in cursor.calls[0][0]
    if status != 409:
        assert all("INSERT" not in sql for sql, _ in cursor.calls)


def test_poll_creation_keeps_sequence_ids_in_json():
    cursor = Cursor([{"option_id": 101}, {"option_id": 105}, {"post_id": 7}])
    repo.create_lab(cursor, 2, {
        "title": "title", "body": "body", "subcategory_code": "JOB_COMPARISON",
        "post_type": "DISCUSSION", "poll_options": ["A", "B"],
    })
    options = json.loads(cursor.calls[-1][1][-1])
    assert options == [
        {"option_id": 101, "option_text": "A", "display_order": 1},
        {"option_id": 105, "option_text": "B", "display_order": 2},
    ]


def test_cleanup_migration_is_guarded_and_non_destructive():
    import re
    from backend.scripts.check_compat_view_references import ROOT, COMPAT_VIEWS
    sql = (ROOT / "database/sql/068_remove_compat_views.sql").read_text(encoding="utf-8")
    sql = re.sub(r"--[^\n]*", "", sql)
    assert set(re.findall(r"DROP VIEW IF EXISTS public\.(\w+) RESTRICT;", sql)) == set(COMPAT_VIEWS)
    assert not re.search(r"\bCASCADE\b|DROP\s+TABLE|DELETE\s+FROM|TRUNCATE\s", sql, re.I)
    assert "relation.relkind <> 'v'" in sql
    assert "IS DISTINCT FROM 'verified'" in sql
    assert all(f"pg_catalog.{name}" in sql for name in ("pg_depend", "pg_trigger", "pg_proc"))
