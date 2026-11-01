"""PLAYMATE 이용 시간과 게시판 방문 통계 서비스입니다."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.core.db_connect import db_cursor
from app.repositories import activity_repository as repository


KST = ZoneInfo("Asia/Seoul")
SPECIAL_BOARDS = {"hot", "hall-of-fame"}


def ping(member_id: int) -> dict:
    """로그인 회원의 활성 이용 시간을 최대 15초 기록합니다."""
    if member_id <= 0:
        return {"recorded_seconds": 0}

    with db_cursor(commit=True) as cursor:
        seconds = repository.record_activity(cursor, member_id)

    return {"recorded_seconds": seconds}


def visit_board(member_id: int, board_key: str) -> dict:
    """게시판 진입 횟수를 일별로 기록합니다. 회원별 방문 이력은 저장하지 않습니다."""
    if member_id <= 0:
        return {"recorded": False}

    # HOT/명예의 전당은 실제 boards 테이블에 없는 가상 게시판입니다.
    if board_key not in SPECIAL_BOARDS:
        if not board_key.isdecimal() or len(board_key) > 18:
            raise HTTPException(status_code=422, detail="게시판 번호가 올바르지 않습니다.")

        board_id = int(board_key)
        if board_id <= 0:
            raise HTTPException(status_code=422, detail="게시판 번호가 올바르지 않습니다.")

        with db_cursor(commit=True) as cursor:
            if not repository.board_exists(cursor, board_id):
                raise HTTPException(status_code=404, detail="게시판을 찾을 수 없습니다.")
            repository.record_board_view(cursor, str(board_id))
    else:
        with db_cursor(commit=True) as cursor:
            repository.record_board_view(cursor, board_key)

    return {"recorded": True}


def get_usage(days: int, page: int = 1) -> dict:
    """전체·기간별 이용 통계와 회원별 10명 단위 페이지를 반환합니다."""
    today = datetime.now(KST).date()
    start = today - timedelta(days=days - 1)
    page_size = 10

    with db_cursor(read_only=True) as cursor:
        summary = repository.read_summary(cursor, start, today)
        daily_rows = repository.read_daily(cursor, start)
        member_count = repository.count_members(cursor, start)
        max_page = max(1, (member_count + page_size - 1) // page_size)
        current_page = min(page, max_page)
        members = repository.read_members(cursor, start, current_page, page_size)
        top_boards = repository.read_top_boards(cursor, start, today)
        most_visited_board = repository.read_most_visited_board(cursor)

    # 방문하지 않은 날짜도 0으로 채워 기간별 평균을 계산합니다.
    by_date = {row["activity_date"]: row for row in daily_rows}
    daily = []

    for offset in range(days):
        day = start + timedelta(days=offset)
        row = by_date.get(day, {})
        daily.append({
            "date": day.isoformat(),
            "seconds": int(row.get("seconds", 0)),
            "users": int(row.get("users", 0)),
        })

    total_seconds = int(summary["total_seconds"])
    first_activity_date = summary["first_activity_date"]
    all_time_days = (today - first_activity_date).days + 1 if first_activity_date else 0
    period_seconds = int(summary["period_seconds"])
    active_user_days = int(summary["active_user_days"])

    return {
        "days": days,
        "start_date": start.isoformat(),
        "end_date": today.isoformat(),
        "total_seconds": total_seconds,
        "all_time_days": all_time_days,
        "all_time_daily_average_seconds": round(total_seconds / all_time_days)

        if all_time_days else 0,

        "period_seconds": period_seconds,
        "daily_average_seconds": round(period_seconds / days),
        "per_active_user_day_seconds": round(period_seconds / active_user_days)

        if active_user_days else 0,
        
        "period_users": int(summary["period_users"]),
        "today_users": int(summary["today_users"]),
        "daily": daily,
        "members": [dict(member) for member in members],
        "members_page": current_page,
        "members_page_size": page_size,
        "members_total": member_count,
        "members_total_pages": max_page,
        "top_boards": [dict(item) for item in top_boards],
        "most_visited_board": most_visited_board,
    }
