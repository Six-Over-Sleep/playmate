"""Issue #106: Admin center pagination, usage and authorization tests."""

from contextlib import contextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.auth import get_current_member_id
from app.repositories import activity_repository
from app.routers import admin, activity, board_moderation
from app.services import activity_service, admin_service


@contextmanager
def fake_db(**kwargs):
    assert kwargs.get("read_only") is True
    yield object()


@pytest.mark.parametrize(
    "service_name,count_name,read_name,total,requested,expected",
    [
        (
            "board_posts_paginated", "count_board_posts",
            "read_board_posts_page", 45, 999, 3,
        ),
        (
            "members_paginated", "count_admin_members",
            "read_members_page", 0, 2, 1,
        ),
        (
            "notices_paginated", "count_notices_paginated",
            "read_notices_paginated", 21, 2, 2,
        ),
    ],
)
def test_admin_pagination_bounds(
    monkeypatch, service_name, count_name, read_name,
    total, requested, expected,
):
    calls = []

    monkeypatch.setattr(admin_service, "db_cursor", fake_db)
    monkeypatch.setattr(
        admin_service.repo,
        count_name,
        lambda cursor, search: total,
    )

    def read_page(cursor, search, page, size):
        calls.append((search, page, size))
        return [{"id": 1}] if total else []

    monkeypatch.setattr(
        admin_service.repo, read_name, read_page
    )

    result = getattr(admin_service, service_name)(
        "test", requested
    )

    assert result["total"] == total
    assert result["page"] == expected
    assert result["page_size"] == 20
    assert result["total_pages"] == max(1, (total + 19) // 20)
    assert calls == [("test", expected, 20)]
    assert isinstance(result["items"], list)


@pytest.mark.parametrize("days", [7, 30])
def test_usage_empty_period_and_page_bounds(monkeypatch, days):
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    calls = []

    monkeypatch.setattr(activity_service, "db_cursor", fake_db)

    def summary(cursor, start, end):
        assert end == today
        assert start == today - timedelta(days=days - 1)
        return {
            "total_seconds": 0,
            "first_activity_date": None,
            "period_seconds": 0,
            "active_user_days": 0,
            "period_users": 0,
            "today_users": 0,
        }

    def daily(cursor, start, end):
        calls.append(("daily", start, end))
        return []

    def members(cursor, start, end, page, size):
        calls.append(("members", start, end, page, size))
        return []

    repo = activity_service.repository

    monkeypatch.setattr(repo, "read_summary", summary)
    monkeypatch.setattr(repo, "read_daily", daily)
    monkeypatch.setattr(repo, "count_members", lambda cursor, start: 25)
    monkeypatch.setattr(repo, "read_members", members)
    monkeypatch.setattr(
        repo, "read_top_boards",
        lambda cursor, start, end: [],
    )
    monkeypatch.setattr(
        repo, "read_most_visited_board",
        lambda cursor: None,
    )

    result = activity_service.get_usage(days, page=999)

    assert result["days"] == days
    assert result["members_page"] == 3
    assert result["members_total_pages"] == 3
    assert result["members_page_size"] == 10
    assert result["all_time_daily_average_seconds"] == 0
    assert result["daily_average_seconds"] == 0
    assert result["per_active_user_day_seconds"] == 0
    assert len(result["daily"]) == days
    assert all(row["seconds"] == 0 for row in result["daily"])
    assert calls[0] == (
        "daily", today - timedelta(days=days - 1), today
    )
    assert calls[1][-2:] == (3, 10)


def test_usage_sql_date_boundaries():
    class Cursor:
        def __init__(self):
            self.calls = []

        def execute(self, sql, params=()):
            self.calls.append((" ".join(sql.split()), params))

        def fetchone(self):
            return {"total_seconds": 0}

        def fetchall(self):
            return []

    cursor = Cursor()
    start = datetime(2026, 11, 1).date()
    end = datetime(2026, 11, 12).date()

    activity_repository.read_summary(cursor, start, end)
    activity_repository.read_daily(cursor, start, end)
    activity_repository.read_members(cursor, start, end, 2, 10)

    summary, daily, members = cursor.calls

    assert "WHERE activity_date <= %s" in summary[0]
    assert summary[1] == (start, start, start, end, end)
    assert "BETWEEN %s AND %s" in daily[0]
    assert daily[1] == (start, end)
    assert "d.activity_date BETWEEN %s AND %s" in members[0]
    assert members[1] == (start, end, 10, 10)


@pytest.fixture
def admin_client(monkeypatch):
    monkeypatch.setattr(
        admin_service, "assert_admin", lambda member_id: None
    )

    monkeypatch.setattr(
        admin_service, "board_posts_paginated",
        lambda q, page: {"kind": "posts", "q": q, "page": page},
    )
    monkeypatch.setattr(
        admin_service, "members_paginated",
        lambda q, page: {"kind": "members", "q": q, "page": page},
    )
    monkeypatch.setattr(
        admin_service, "notices_paginated",
        lambda q, page: {"kind": "notices", "q": q, "page": page},
    )
    monkeypatch.setattr(
        activity_service, "get_usage",
        lambda days, page: {"days": days, "page": page},
    )
    monkeypatch.setattr(
        board_moderation, "_reports_paged",
        lambda page, q, state: {
            "kind": "reports", "q": q,
            "page": page, "status": state,
        },
    )

    app = FastAPI()
    app.include_router(admin.router)
    app.include_router(activity.router)
    app.include_router(board_moderation.admin_router)
    app.dependency_overrides[get_current_member_id] = lambda: 7

    with TestClient(app) as client:
        yield client


def test_admin_paginated_endpoints(admin_client):
    assert admin_client.get(
        "/api/admin/posts?page=2&q=python"
    ).json() == {"kind": "posts", "q": "python", "page": 2}

    assert admin_client.get(
        "/api/admin/members?page=3&q=42"
    ).json() == {"kind": "members", "q": "42", "page": 3}

    assert admin_client.get(
        "/api/admin/notices?page=4&q=notice"
    ).json() == {"kind": "notices", "q": "notice", "page": 4}

    assert admin_client.get(
        "/api/admin/board-reports/details"
        "?page=2&q=spam&status_filter=hidden"
    ).json() == {
        "kind": "reports", "q": "spam",
        "page": 2, "status": "hidden",
    }

    assert admin_client.get(
        "/api/admin/usage?days=30&page=2"
    ).json() == {"days": 30, "page": 2}


@pytest.mark.parametrize(
    "url",
    [
        "/api/admin/posts?page=0",
        "/api/admin/members?page=0",
        "/api/admin/notices?page=0",
        "/api/admin/board-reports/details?page=0",
        "/api/admin/board-reports/details?page=1&status_filter=invalid",
        "/api/admin/usage?days=8&page=1",
        "/api/admin/usage?days=7&page=0",
    ],
)
def test_invalid_admin_queries_return_422(admin_client, url):
    assert admin_client.get(url).status_code == 422


def test_revoked_admin_cannot_access_paginated_api(
    admin_client, monkeypatch
):
    def deny(member_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    monkeypatch.setattr(admin_service, "assert_admin", deny)

    for url in (
        "/api/admin/posts?page=1",
        "/api/admin/members?page=1",
        "/api/admin/notices?page=1",
        "/api/admin/board-reports/details?page=1",
        "/api/admin/usage?days=7&page=1",
    ):
        assert admin_client.get(url).status_code == 403, url
