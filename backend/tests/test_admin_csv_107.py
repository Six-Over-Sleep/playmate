"""Regression tests for Issue #107 CSV export."""

import csv
import io
from contextlib import contextmanager

import pytest
from fastapi import HTTPException

from app.services import activity_csv_service as service


class FakeCursor:
    def __init__(self, records):
        self.records = records
        self.sql = ""
        self.params = ()

    def execute(self, sql, params):
        self.sql = " ".join(sql.split())
        self.params = params

    def fetchall(self):
        return self.records


def fake_database(monkeypatch, records):
    cursor = FakeCursor(records)

    @contextmanager
    def db_cursor(**kwargs):
        assert kwargs.get("read_only") is True
        yield cursor

    monkeypatch.setattr(service, "db_cursor", db_cursor)
    return cursor


def parse_csv(response):
    assert response.body.startswith(b"\xef\xbb\xbf")
    decoded = response.body.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(decoded)))


def test_member_export(monkeypatch):
    cursor = fake_database(monkeypatch, [
        {
            "member_id": 7,
            "active_seconds": 1800,
            "active_days": 2,
        },
        {
            "member_id": 8,
            "active_seconds": 0,
            "active_days": 0,
        },
    ])

    response = service.export_usage_csv(7, "members")
    rows = parse_csv(response)

    assert response.status_code == 200
    assert rows[0][2] == "member_id"
    assert rows[1][2:] == ["7", "1800", "2", "900"]
    assert rows[2][2:] == ["8", "0", "0", "0"]
    assert "BETWEEN %s AND %s" in cursor.sql
    assert cursor.params[2] == 10001
    assert response.headers["cache-control"] == "no-store"


def test_board_export_prevents_formula_injection(monkeypatch):
    fake_database(monkeypatch, [
        {
            "board_key": "42",
            "board_name": " =SUM(1,1)",
            "visits": 15,
        },
    ])

    response = service.export_usage_csv(30, "boards")
    rows = parse_csv(response)

    assert rows[0] == [
        "period_start", "period_end",
        "board_key", "board_name", "visits",
    ]
    assert rows[1][3] == "' =SUM(1,1)"
    assert rows[1][4] == "15"


@pytest.mark.parametrize("days,kind", [
    (0, "members"),
    (8, "members"),
    (31, "boards"),
    (7, "invalid"),
])
def test_invalid_export_parameters(days, kind):
    with pytest.raises(HTTPException) as error:
        service.export_usage_csv(days, kind)
    assert error.value.status_code == 422


def test_export_row_limit(monkeypatch):
    record = {
        "member_id": 1,
        "active_seconds": 0,
        "active_days": 0,
    }
    fake_database(monkeypatch, [record] * 10001)

    with pytest.raises(HTTPException) as error:
        service.export_usage_csv(7, "members")

    assert error.value.status_code == 413


def test_empty_export_has_header(monkeypatch):
    fake_database(monkeypatch, [])

    response = service.export_usage_csv(7, "boards")
    rows = parse_csv(response)

    assert len(rows) == 1
    assert rows[0][2] == "board_key"


def test_custom_date_range_export(monkeypatch):
    from datetime import datetime, timedelta

    end = datetime.now(service.KST).date()
    start = end - timedelta(days=13)
    cursor = fake_database(monkeypatch, [
        {"board_key": "42", "board_name": "Board", "visits": 12}
    ])

    response = service.export_usage_csv(
        7, "boards", start_date=start, end_date=end
    )
    rows = parse_csv(response)

    assert response.status_code == 200
    assert cursor.params[:2] == (start, end)
    assert rows[1][:2] == [start.isoformat(), end.isoformat()]
    assert rows[1][-1] == "12"


def test_invalid_custom_date_ranges():
    from datetime import datetime, timedelta

    today = datetime.now(service.KST).date()

    cases = [
        (today, None),
        (None, today),
        (today, today - timedelta(days=1)),
        (today, today + timedelta(days=1)),
        (today - timedelta(days=365), today),
    ]

    for start, end in cases:
        with pytest.raises(HTTPException) as error:
            service.export_usage_csv(
                7, "members", start_date=start, end_date=end
            )
        assert error.value.status_code == 422
