"""Admin-only CSV export of usage statistics."""

import csv
import io
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Response

from app.core.db_connect import db_cursor


KST = ZoneInfo("Asia/Seoul")
MAX_EXPORT_ROWS = 10000


def _safe_cell(value: object) -> str:
    """Prevent spreadsheet formulas and control-character injection."""
    text = "" if value is None else str(value)
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)

    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text

    return text


def export_usage_csv(
    days: int,
    kind: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> Response:
    if days not in (7, 30) or kind not in ("members", "boards"):
        raise HTTPException(status_code=422, detail="Invalid CSV parameters")

    today = datetime.now(KST).date()

    if (start_date is None) != (end_date is None):
        raise HTTPException(status_code=422, detail="Both dates are required")

    if start_date is not None:
        if not (start_date <= end_date <= today):
            raise HTTPException(status_code=422, detail="Invalid date range")
        if (end_date - start_date).days >= 365:
            raise HTTPException(status_code=422, detail="Maximum 365 days")
        start, end = start_date, end_date
    else:
        start = today - timedelta(days=days - 1)
        end = today

    with db_cursor(read_only=True) as cursor:
        if kind == "members":
            cursor.execute(
                """
                SELECT
                    m.member_id,
                    COALESCE(SUM(d.active_seconds), 0)::bigint
                        AS active_seconds,
                    COUNT(DISTINCT d.activity_date)::int AS active_days
                FROM members AS m
                LEFT JOIN member_daily_activity AS d
                    ON d.member_id = m.member_id
                   AND d.activity_date BETWEEN %s AND %s
                WHERE m.member_id > 0
                GROUP BY m.member_id
                ORDER BY active_seconds DESC, m.member_id
                LIMIT %s
                """,
                (start, end, MAX_EXPORT_ROWS + 1),
            )
        else:
            cursor.execute(
                """
                SELECT
                    v.board_key,
                    COALESCE(
                        b.board_name,
                        CASE v.board_key
                            WHEN 'hot' THEN 'HOT'
                            WHEN 'hall-of-fame'
                                THEN '명예의 전당'
                            ELSE '삭제된 게시판'
                        END
                    ) AS board_name,
                    SUM(v.visit_count)::bigint AS visits
                FROM board_daily_visits AS v
                LEFT JOIN boards AS b
                    ON v.board_key = b.board_id::text
                WHERE v.visit_date BETWEEN %s AND %s
                GROUP BY v.board_key, b.board_name
                ORDER BY visits DESC, v.board_key
                LIMIT %s
                """,
                (start, end, MAX_EXPORT_ROWS + 1),
            )

        records = cursor.fetchall()

    if len(records) > MAX_EXPORT_ROWS:
        raise HTTPException(
            status_code=413,
            detail="CSV export exceeds the 10000-row limit",
        )

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")

    if kind == "members":
        writer.writerow([
            "period_start", "period_end", "member_id",
            "active_seconds", "active_days",
            "avg_active_day_seconds",
        ])

        for row in records:
            seconds = int(row["active_seconds"])
            active_days = int(row["active_days"])

            writer.writerow([
                start.isoformat(),
                end.isoformat(),
                int(row["member_id"]),
                seconds,
                active_days,
                round(seconds / active_days) if active_days else 0,
            ])
    else:
        writer.writerow([
            "period_start", "period_end",
            "board_key", "board_name", "visits",
        ])

        for row in records:
            writer.writerow([
                start.isoformat(),
                end.isoformat(),
                _safe_cell(row["board_key"]),
                _safe_cell(row["board_name"]),
                int(row["visits"]),
            ])

    filename = (
        f"playmate_usage_{kind}_{days}d_"
        f"{start:%Y%m%d}_{end:%Y%m%d}.csv"
    )

    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
        },
    )
