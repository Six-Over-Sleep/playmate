"""PLAYMATE 회원 활동 기록과 관리자 통계 SQL을 관리합니다."""

from datetime import date


PING_SECONDS = 15


def record_activity(cursor, member_id: int) -> int:
    """활성 시간을 기록하고 여러 탭의 중복 집계를 줄입니다."""
    cursor.execute(
        """
        INSERT INTO member_activity_tracker (member_id)
        VALUES (%s)
        ON CONFLICT (member_id) DO NOTHING
        RETURNING member_id
        """,
        (member_id,),
    )
    is_first = cursor.fetchone() is not None

    cursor.execute(
        """
        SELECT
            last_ping_at,
            GREATEST(0, EXTRACT(EPOCH FROM (NOW() - last_ping_at))) AS elapsed
        FROM member_activity_tracker
        WHERE member_id = %s
        FOR UPDATE
        """,
        (member_id,),
    )
    row = cursor.fetchone()
    elapsed = PING_SECONDS if is_first else int(row["elapsed"])
    earned = min(PING_SECONDS, max(0, elapsed))

    cursor.execute(
        """
        UPDATE member_activity_tracker
        SET last_ping_at = NOW()
        WHERE member_id = %s
        """,
        (member_id,),
    )

    if earned:
        cursor.execute(
            """
            INSERT INTO member_daily_activity (
                member_id, activity_date, active_seconds, last_seen_at
            )
            VALUES (
                %s,
                (NOW() AT TIME ZONE 'Asia/Seoul')::date,
                %s,
                NOW()
            )
            ON CONFLICT (member_id, activity_date)
            DO UPDATE SET
                active_seconds = member_daily_activity.active_seconds
                    + EXCLUDED.active_seconds,
                last_seen_at = NOW()
            """,
            (member_id, earned),
        )

    return earned


def read_summary(cursor, start_date: date, today: date) -> dict:
    """전체 누적과 기간별 이용 시간, 최초 이용일을 조회합니다."""
    cursor.execute(
        """
        SELECT
            COALESCE(SUM(active_seconds), 0)::bigint AS total_seconds,
            MIN(activity_date) AS first_activity_date,
            COALESCE(SUM(active_seconds) FILTER (
                WHERE activity_date >= %s
            ), 0)::bigint AS period_seconds,
            COUNT(DISTINCT member_id) FILTER (
                WHERE activity_date >= %s
            )::int AS period_users,
            COUNT(*) FILTER (
                WHERE activity_date >= %s
            )::int AS active_user_days,
            COUNT(DISTINCT member_id) FILTER (
                WHERE activity_date = %s
            )::int AS today_users
        FROM member_daily_activity
        """,
        (start_date, start_date, start_date, today),
    )
    return dict(cursor.fetchone())


def read_daily(cursor, start_date: date) -> list[dict]:
    """날짜별 이용 시간과 활동 회원 수를 조회합니다."""
    cursor.execute(
        """
        SELECT
            activity_date,
            COALESCE(SUM(active_seconds), 0)::bigint AS seconds,
            COUNT(DISTINCT member_id)::int AS users
        FROM member_daily_activity
        WHERE activity_date >= %s
        GROUP BY activity_date
        ORDER BY activity_date
        """,
        (start_date,),
    )
    return list(cursor.fetchall())


def count_members(cursor, start_date: date) -> int:
    """이용 기록이 0인 회원도 포함하여 전체 회원 수를 반환합니다."""
    cursor.execute(
        """
        SELECT COUNT(*)::int AS count
        FROM members
        WHERE member_id > 0
        """
    )
    return int(cursor.fetchone()["count"])


def read_members(cursor, start_date: date, page: int, page_size: int = 10) -> list[dict]:
    """활동 시간이 0인 회원까지 10명 단위로 조회합니다."""
    offset = (page - 1) * page_size

    cursor.execute(
        """
        SELECT
            m.member_id,
            COALESCE(m.nickname, '회원') AS nickname,
            COALESCE(SUM(d.active_seconds), 0)::bigint AS seconds,
            COUNT(DISTINCT d.activity_date)::int AS active_days
        FROM members AS m
        LEFT JOIN member_daily_activity AS d
            ON m.member_id = d.member_id
           AND d.activity_date >= %s
        WHERE m.member_id > 0
        GROUP BY m.member_id, m.nickname
        ORDER BY seconds DESC, m.member_id
        LIMIT %s OFFSET %s
        """,
        (start_date, page_size, offset),
    )
    return list(cursor.fetchall())


def record_board_view(cursor, board_key: str) -> None:
    """개인별 이동 경로를 저장하지 않고 게시판별 일일 방문만 누적합니다."""
    cursor.execute(
        """
        INSERT INTO board_daily_visits (board_key, visit_date, visit_count)
        VALUES (%s, (NOW() AT TIME ZONE 'Asia/Seoul')::date, 1)
        ON CONFLICT (board_key, visit_date)
        DO UPDATE SET
            visit_count = board_daily_visits.visit_count + 1
        """,
        (board_key,),
    )


def board_exists(cursor, board_id: int) -> bool:
    cursor.execute("SELECT 1 FROM boards WHERE board_id = %s", (board_id,))
    return cursor.fetchone() is not None


def read_top_boards(cursor, start_date: date, today: date) -> list[dict]:
    """기간 내 방문 횟수가 많은 게시판 TOP 10을 반환합니다."""
    cursor.execute(
        """
        SELECT
            v.board_key,
            COALESCE(
                b.board_name,
                CASE v.board_key
                    WHEN 'hall-of-fame' THEN '🏆 명예의 전당'
                    WHEN 'hot' THEN '🔥 HOT 게시판'
                    ELSE '삭제된 게시판'
                END
            ) AS name,
            SUM(v.visit_count)::bigint AS visits
        FROM board_daily_visits AS v
        LEFT JOIN boards AS b ON v.board_key = b.board_id::text
        WHERE v.visit_date BETWEEN %s AND %s
        GROUP BY v.board_key, b.board_name
        ORDER BY visits DESC, name, v.board_key
        LIMIT 10
        """,
        (start_date, today),
    )
    return list(cursor.fetchall())

# 전체 기간 동안 가장 많이 방문한 게시판 1개를 조회합니다.
def read_most_visited_board(cursor) -> dict | None:
    """전체 기간 누적 방문 횟수 1위 게시판을 조회합니다."""
    cursor.execute(
        """
        SELECT
            v.board_key,
            COALESCE(
                b.board_name,
                CASE v.board_key
                    WHEN 'hall-of-fame' THEN '🏆 명예의 전당'
                    WHEN 'hot' THEN '🔥 HOT 게시판'
                    ELSE '삭제된 게시판'
                END
            ) AS name,
            SUM(v.visit_count)::bigint AS visits
        FROM board_daily_visits AS v
        LEFT JOIN boards AS b
            ON v.board_key = b.board_id::text
        GROUP BY v.board_key, b.board_name
        ORDER BY visits DESC, name, v.board_key
        LIMIT 1
        """
    )
    row = cursor.fetchone()
    return dict(row) if row else None

