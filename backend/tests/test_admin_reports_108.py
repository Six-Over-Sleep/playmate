"""Issue #108: 신고 접수 및 관리자 처리 회귀 검증."""

from contextlib import contextmanager

import pytest
from fastapi import HTTPException

from app.routers import board_moderation as reports
from app.services import admin_service


class ReportCursor:
    """실제 DB 연결 없이 신고 SQL의 처리 순서를 검증합니다."""

    def __init__(self):
        self.post = {
            "post_id": 10,
            "author_member_id": 99,
            "post_status": "PUBLISHED",
            "deleted_at": None,
            "post_type": "BOARD",
            "source_type": "USER",
            "board_name": "자유게시판",
        }
        self.reporters = set()
        self.current = None
        self.queries = []

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        self.queries.append((normalized, params))

        if "FOR UPDATE OF p" in normalized:
            self.current = dict(self.post)

        elif "INSERT INTO post_reports" in normalized:
            reporter_id = params[1]
            if reporter_id in self.reporters:
                self.current = None
            else:
                self.reporters.add(reporter_id)
                self.current = {"report_id": len(self.reporters)}

        elif "COUNT(*)::int AS count" in normalized:
            self.current = {"count": len(self.reporters)}

        elif "UPDATE posts SET post_status = 'HIDDEN'" in normalized:
            self.post["post_status"] = "HIDDEN"
            self.current = None

        else:
            raise AssertionError(f"예상하지 못한 SQL: {normalized}")

    def fetchone(self):
        return self.current


def submit(cursor, member_id):
    return reports.submit_report(
        cursor,
        board_id=1,
        post_id=10,
        member_id=member_id,
        payload=reports.ReportCreate(
            reason="SPAM",
            details="광고 게시글",
        ),
    )


def test_three_reports_trigger_auto_hide():
    cursor = ReportCursor()

    first = submit(cursor, 1)
    second = submit(cursor, 2)

    assert first["report_count"] == 1
    assert second["report_count"] == 2
    assert first["hidden"] is False
    assert second["hidden"] is False
    assert cursor.post["post_status"] == "PUBLISHED"

    third = submit(cursor, 3)

    assert third["report_count"] == 3
    assert third["hidden"] is True
    assert cursor.post["post_status"] == "HIDDEN"

    assert any(
        "FOR UPDATE OF p" in sql
        for sql, _ in cursor.queries
    )


def test_same_member_cannot_report_twice():
    cursor = ReportCursor()
    submit(cursor, 7)

    with pytest.raises(HTTPException) as exc:
        submit(cursor, 7)

    assert exc.value.status_code == 409
    assert len(cursor.reporters) == 1

    assert any(
        "ON CONFLICT (post_id, reporter_member_id) DO NOTHING" in sql
        for sql, _ in cursor.queries
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("board_name", "공지사항"),
        ("source_type", "SYSTEM"),
        ("author_member_id", 7),
    ],
)
def test_protected_posts_reject_reports(field, value):
    cursor = ReportCursor()
    cursor.post[field] = value

    with pytest.raises(HTTPException) as exc:
        submit(cursor, 7)

    assert exc.value.status_code == 403
    assert not cursor.reporters


def test_hidden_post_rejects_new_report():
    cursor = ReportCursor()
    cursor.post["post_status"] = "HIDDEN"

    with pytest.raises(HTTPException) as exc:
        submit(cursor, 7)

    assert exc.value.status_code == 404


def test_paginated_report_details(monkeypatch):
    class PageCursor:
        def __init__(self):
            self.results = iter([
                {
                    "total": 1,
                    "hidden_total": 1,
                    "report_count": 3,
                },
                [{
                    "post_id": 10,
                    "post_status": "HIDDEN",
                    "title": "신고 게시글",
                    "report_count": 3,
                }],
                [{
                    "post_id": 10,
                    "report_id": 1,
                    "reason": "SPAM",
                    "details": "광고",
                    "reporter_name": "회원 A",
                }],
            ])
            self.queries = []

        def execute(self, sql, params=()):
            self.queries.append((" ".join(sql.split()), params))

        def fetchone(self):
            return next(self.results)

        def fetchall(self):
            return next(self.results)

    cursor = PageCursor()

    @contextmanager
    def fake_db(**kwargs):
        assert kwargs.get("read_only") is True
        yield cursor

    monkeypatch.setattr(reports, "db_cursor", fake_db)

    result = reports._reports_paged(
        page=1,
        search="신고",
        state="hidden",
    )

    assert result["total"] == 1
    assert result["page"] == 1
    assert result["hidden_total"] == 1
    assert result["report_count"] == 3
    assert result["items"][0]["reports"][0]["reason"] == "SPAM"
    assert result["items"][0]["reports"][0]["details"] == "광고"
    assert cursor.queries[1][1][-2:] == (20, 0)


@pytest.mark.parametrize(
    "hidden,expected_status",
    [
        (True, "HIDDEN"),
        (False, "PUBLISHED"),
    ],
)
def test_admin_hide_and_restore(
    monkeypatch, hidden, expected_status,
):
    class VisibilityCursor:
        rowcount = 1

        def execute(self, sql, params):
            self.sql = " ".join(sql.split())
            self.params = params

    cursor = VisibilityCursor()

    @contextmanager
    def fake_db(**kwargs):
        assert kwargs.get("commit") is True
        yield cursor

    monkeypatch.setattr(admin_service, "db_cursor", fake_db)

    admin_service.change_post_visibility(10, hidden)

    assert cursor.params == (expected_status, 10)
    assert "b.board_name <> '공지사항'" in cursor.sql
    assert "p.deleted_at IS NULL" in cursor.sql


def test_visibility_returns_404_when_post_missing(monkeypatch):
    class MissingCursor:
        rowcount = 0

        def execute(self, sql, params):
            pass

    @contextmanager
    def fake_db(**kwargs):
        yield MissingCursor()

    monkeypatch.setattr(admin_service, "db_cursor", fake_db)

    with pytest.raises(HTTPException) as exc:
        admin_service.change_post_visibility(999999, True)

    assert exc.value.status_code == 404
