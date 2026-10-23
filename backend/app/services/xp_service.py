from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from backend.app.core.database import get_db_connection

# 회원 종합 레벨 계산

def calculate_level(total_xp: int) -> int:
    if total_xp < 0:
        raise ValueError("XP는 음수일 수 없습니다.")

    if total_xp >= 1500:
        return 4
    elif total_xp >= 500:
        return 3
    elif total_xp >= 100:
        return 2
    else:
        return 1


# 기본 활동별 XP
XP_RULES = {
    "ATTEND": 1,
    "POST": 5,
    "COMMENT": 2,
    "REPLY": 2,
}


def grant_xp(member_id: int, activity_type: str, source_id: int | None = None):
    """활동별 XP 지급 및 종합 레벨 갱신"""

    if activity_type not in XP_RULES:
        raise ValueError("지원하지 않는 XP 활동입니다.")

    if activity_type != "ATTEND" and (source_id is None or source_id <= 0):
        raise ValueError("활동 데이터 ID가 필요합니다.")

    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    xp = XP_RULES[activity_type]

    # 동일 활동의 중복 지급 방지
    if activity_type == "ATTEND":
        event_key = f"ATTEND:{today}"
        source_type = None
    else:
        event_type = "COMMENT" if activity_type == "REPLY" else activity_type
        event_key = f"{event_type}:{source_id}"
        source_type = event_type

    with get_db_connection() as conn:
        with conn.cursor() as cursor:

            


            # 게시글 작성자 및 작성일 검증
            if activity_type == "POST":
                cursor.execute(
                    """
                    SELECT author_member_id, created_at
                    FROM posts
                    WHERE post_id = %s
                    """,
                    (source_id,)
                )

                post = cursor.fetchone()

                # 작성자 확인
                if post is None or post[0] != member_id:
                    return {
                        "awarded": False,
                        "reason": "INVALID_POST"
                    }

                # 작성일 확인
                if post[1] is None or post[1].date() != today:
                    return {
                        "awarded": False,
                        "reason": "INVALID_POST_DATE"
                    }

            
            # 댓글 및 대댓글 검증
            if activity_type in ("COMMENT", "REPLY"):
                cursor.execute(
                    """
                    SELECT
                        author_member_id,
                        created_at,
                        deleted_at,
                        parent_comment_id
                    FROM comments
                    WHERE comment_id = %s
                    """,
                    (source_id,)
                )

                comment = cursor.fetchone()

                # 댓글 존재 및 작성자 확인
                if comment is None or comment[0] != member_id:
                    return {"awarded": False, "reason": "INVALID_COMMENT"}

                # 삭제된 댓글 제외
                if comment[2] is not None:
                    return {"awarded": False, "reason": "DELETED_COMMENT"}

                # 작성 날짜 확인
                if comment[1] is None or comment[1].date() != today:
                    return {"awarded": False, "reason": "INVALID_COMMENT_DATE"}

                # 일반 댓글과 대댓글 구분
                is_reply = comment[3] is not None

                if (activity_type == "REPLY") != is_reply:
                    return {"awarded": False, "reason": "INVALID_COMMENT_TYPE"}




            # 최초 활동 회원의 레벨 정보 생성
            cursor.execute(
                """
                INSERT INTO member_levels (member_id)
                VALUES (%s)
                ON CONFLICT (member_id) DO NOTHING
                """,
                (member_id,)
            )

            # 동시 요청 시 XP 중복 처리 방지
            cursor.execute(
                """
                SELECT total_xp
                FROM member_levels
                WHERE member_id = %s
                FOR UPDATE
                """,
                (member_id,)
            )
            total_xp = cursor.fetchone()[0]

            # 같은 활동으로 이미 지급받았는지 확인
            cursor.execute(
                """
                SELECT 1 FROM member_xp_history
                WHERE member_id = %s AND event_key = %s
                """,
                (member_id, event_key)
            )
            if cursor.fetchone():
                return {"awarded": False, "reason": "DUPLICATE"}

            # 하루 지급 횟수 제한
            if activity_type in ("POST", "COMMENT", "REPLY"):
                types = ["POST"] if activity_type == "POST" else ["COMMENT", "REPLY"]
                limit = 3 if activity_type == "POST" else 10

                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM member_xp_history
                    WHERE member_id = %s
                        AND activity_date = %s
                        AND activity_type = ANY(%s)
                        AND xp_change > 0
                    """,
                    (member_id, today, types)
                )

                if cursor.fetchone()[0] >= limit:
                    return {"awarded": False, "reason": "DAILY_LIMIT"}

            # XP 지급 이력 기록
            cursor.execute(
                """
                INSERT INTO member_xp_history
                (member_id, activity_type, source_type,
                source_id, event_key, xp_change, activity_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (member_id, activity_type, source_type,
                source_id, event_key, xp, today)
            )

            
            # 연속 출석 보너스 계산
            bonus_xp = 0

            if activity_type == "ATTEND":
                bonus_xp = grant_attendance_bonus(
                    cursor, member_id, today
                )


            # 누적 XP 및 종합 레벨 변경
            new_xp = total_xp + xp + bonus_xp
            new_level = calculate_level(new_xp)

            cursor.execute(
                """
                UPDATE member_levels
                SET total_xp = %s,
                    level = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE member_id = %s
                """,
                (new_xp, new_level, member_id)
            )

    return {
        "awarded": True,
        "earned_xp": xp,
        "bonus_xp": bonus_xp,
        "total_xp": new_xp,
        "level": new_level
    }

# 게시글·댓글 삭제 시 XP 회수
def revoke_xp(
    cursor,
    member_id: int,
    source_type: str,
    source_id: int
) -> bool:

    if source_type not in ("POST", "COMMENT"):
        raise ValueError("지원하지 않는 활동 유형입니다.")

    if member_id <= 0 or source_id <= 0:
        return False

    # 원래 지급했던 활동 키
    event_key = f"{source_type}:{source_id}"
    revoke_key = f"REVOKE:{event_key}"

    # 회원 XP 잠금
    cursor.execute(
        """
        SELECT total_xp
        FROM member_levels
        WHERE member_id = %s
        FOR UPDATE
        """,
        (member_id,)
    )

    level_row = cursor.fetchone()

    if level_row is None:
        return False

    # 기존 XP 지급 내역 확인
    cursor.execute(
        """
        SELECT xp_change
        FROM member_xp_history
        WHERE member_id = %s
          AND event_key = %s
          AND xp_change > 0
        """,
        (member_id, event_key)
    )

    history = cursor.fetchone()

    if history is None:
        return False

    # 중복 회수 방지
    cursor.execute(
        """
        SELECT 1
        FROM member_xp_history
        WHERE member_id = %s
          AND event_key = %s
        """,
        (member_id, revoke_key)
    )

    if cursor.fetchone() is not None:
        return False

    # 회수 후 XP 및 레벨 계산
    new_xp = level_row["total_xp"] - history["xp_change"]

    if new_xp < 0:
        raise ValueError("회수할 XP가 현재 XP보다 많습니다.")

    new_level = calculate_level(new_xp)

    today = datetime.now(ZoneInfo("Asia/Seoul")).date()

    # XP 회수 이력 저장
    cursor.execute(
        """
        INSERT INTO member_xp_history
        (
            member_id, activity_type, source_type,
            source_id, event_key, xp_change, activity_date
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            member_id,
            "REVOKE",
            source_type,
            source_id,
            revoke_key,
            -history["xp_change"],
            today
        )
    )

    # 회원 XP 및 레벨 갱신
    cursor.execute(
        """
        UPDATE member_levels
        SET total_xp = %s,
            level = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE member_id = %s
        """,
        (new_xp, new_level, member_id)
    )

    return True


# 연속 출석 일수 계산
def calculate_attendance_streak(
    attendance_dates: set[date],
    today: date
) -> int:
    streak = 0
    current_day = today

    while current_day in attendance_dates:
        streak += 1
        current_day -= timedelta(days=1)

    return streak


# 연속 출석 보너스 계산
def calculate_attendance_bonus(streak: int) -> int:
    if streak == 7:
        return 5

    if streak == 30:
        return 20

    return 0


# 연속 출석 달성 보너스 지급
def grant_attendance_bonus(cursor, member_id: int, today: date) -> int:

    # 최근 30일 출석 기록 조회
    cursor.execute(
        """
        SELECT activity_date
        FROM member_xp_history
        WHERE member_id = %s
          AND activity_type = 'ATTEND'
          AND xp_change > 0
          AND activity_date BETWEEN %s AND %s
        """,
        (member_id, today - timedelta(days=29), today)
    )

    dates = {row[0] for row in cursor.fetchall()}

    # 연속 출석 일수 및 보너스 계산
    streak = calculate_attendance_streak(dates, today)
    bonus = calculate_attendance_bonus(streak)

    if bonus == 0:
        return 0

    # 보너스 이력 저장 및 중복 지급 방지
    event_key = f"STREAK:{streak}:{today}"

    cursor.execute(
        """
        INSERT INTO member_xp_history
        (member_id, activity_type, event_key, xp_change, activity_date)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (member_id, event_key) DO NOTHING
        RETURNING xp_change
        """,
        (member_id, f"STREAK_{streak}", event_key, bonus, today)
    )

    return bonus if cursor.fetchone() else 0
