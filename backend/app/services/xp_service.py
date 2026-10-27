from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from uuid import uuid4

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
                    SELECT author_member_id, created_at, post_type, deleted_at
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

                # 일반 게시판 글만 +5XP 지급 (CAREER 후기와 중복 방지)
                if post[2] != "BOARD" or post[3] is not None:
                    return {"awarded": False, "reason": "NOT_BOARD_POST"}

                # 한국 시간 기준으로 작성일 확인
                created_date = (
                    post[1].astimezone(ZoneInfo("Asia/Seoul")).date()
                    if post[1] is not None else None
                )
                if created_date != today:
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

# 취준 도감 후기별 보상 규칙
# 미정: CODING_ASSIGNMENT, FINAL은 보상 정책이 확정될 때까지 지급하지 않음.
def get_career_review_reward(
    subcategory: str,
    process_stage: str,
    process_result: str,
) -> tuple[str, int] | None:
    """정책이 확정된 후기 유형에 대해서만 (활동 유형, XP)를 반환한다."""

    if subcategory == "DOCUMENT" and process_stage == "DOCUMENT":
        if process_result in ("PASS", "FAIL"):
            return "CAREER_DOCUMENT", 30

    if subcategory == "INTERVIEW" and process_stage == "INTERVIEW":
        return "CAREER_INTERVIEW", 50

    if subcategory == "SUCCESS" and process_stage == "FINAL":
        if process_result == "PASS":
            return "CAREER_SUCCESS", 50

    return None


def grant_career_review_xp(member_id: int, post_id: int) -> dict:
    """저장된 취준 도감 후기를 검증한 뒤 해당 게시글에 XP를 최초 1회 지급한다."""

    if member_id <= 0 or post_id <= 0:
        return {"awarded": False, "reason": "INVALID_ID"}

    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    event_key = f"POST:{post_id}"  # 일반 게시글 XP와 같은 키로 중복 지급 차단

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # 게시글 행을 잠가서 동시 삭제와 보상 지급이 엇갈리지 않게 처리
            cursor.execute(
                """
                SELECT
                    p.author_member_id,
                    cp.subcategory_code,
                    cr.process_stage,
                    cr.process_result,
                    LENGTH(BTRIM(p.body))
                FROM posts AS p
                JOIN career_posts AS cp ON cp.post_id = p.post_id
                JOIN career_reviews AS cr ON cr.post_id = p.post_id
                WHERE p.post_id = %s
                  AND p.post_type = 'CAREER'
                  AND cp.category_code = 'reviews'
                  AND p.post_status = 'PUBLISHED'
                  AND p.deleted_at IS NULL
                FOR UPDATE OF p
                """,
                (post_id,),
            )
            review = cursor.fetchone()
            if review is None or review[0] != member_id:
                return {"awarded": False, "reason": "INVALID_REVIEW"}

            if review[4] < 500:
                return {"awarded": False, "reason": "BODY_TOO_SHORT"}

            reward = get_career_review_reward(
                subcategory=review[1],
                process_stage=review[2],
                process_result=review[3],
            )
            if reward is None:
                return {"awarded": False, "reason": "UNSUPPORTED_REVIEW_TYPE"}

            activity_type, xp = reward

            # 회원 레벨 생성 및 동시 지급 요청 직렬화
            cursor.execute(
                """
                INSERT INTO member_levels (member_id)
                VALUES (%s)
                ON CONFLICT (member_id) DO NOTHING
                """,
                (member_id,),
            )
            cursor.execute(
                """
                SELECT total_xp
                FROM member_levels
                WHERE member_id = %s
                FOR UPDATE
                """,
                (member_id,),
            )
            total_xp = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT 1 FROM member_xp_history
                WHERE member_id = %s AND event_key = %s
                """,
                (member_id, event_key),
            )
            if cursor.fetchone():
                return {"awarded": False, "reason": "DUPLICATE"}

            cursor.execute(
                """
                INSERT INTO member_xp_history
                    (member_id, activity_type, source_type,
                     source_id, event_key, xp_change, activity_date)
                VALUES (%s, %s, 'POST', %s, %s, %s, %s)
                """,
                (member_id, activity_type, post_id, event_key, xp, today),
            )

            new_xp = total_xp + xp
            new_level = calculate_level(new_xp)
            cursor.execute(
                """
                UPDATE member_levels
                SET total_xp = %s,
                    level = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE member_id = %s
                """,
                (new_xp, new_level, member_id),
            )

    return {
        "awarded": True,
        "earned_xp": xp,
        "total_xp": new_xp,
        "level": new_level,
    }


# 후기 수정 시 보상 차액 반영
# 예: 서류 후기 30XP -> 면접 후기 50XP = +20XP
# 같은 값을 여러 번 저장해도 추가 XP를 주지 않는다.
def reconcile_career_review_xp(cursor, member_id: int, post_id: int) -> dict:
    """업데이트된 후기 내용을 기준으로 누적 지급 XP를 정산한다.

    career_service.update_review()의 DB 트랜잭션 안에서만 호출한다.
    """
    if member_id <= 0 or post_id <= 0:
        raise ValueError("유효하지 않은 회원 또는 게시글 ID입니다.")

    # 작성자와 현재 후기의 실제 유형을 확인한다.
    cursor.execute(
        """
        SELECT p.author_member_id,
               cp.subcategory_code,
               cr.process_stage,
               cr.process_result,
               LENGTH(BTRIM(p.body)) AS body_length
        FROM posts AS p
        JOIN career_posts AS cp ON cp.post_id = p.post_id
        JOIN career_reviews AS cr ON cr.post_id = p.post_id
        WHERE p.post_id = %s
          AND p.post_type = 'CAREER'
          AND cp.category_code = 'reviews'
          AND p.deleted_at IS NULL
        FOR UPDATE OF p
        """,
        (post_id,),
    )
    review = cursor.fetchone()
    if review is None or review["author_member_id"] != member_id:
        raise ValueError("XP 정산 대상 후기가 없거나 작성자가 다릅니다.")

    # 후기 정책을 충족하지 못하면 목표 보상은 0이다.
    reward = get_career_review_reward(
        review["subcategory_code"],
        review["process_stage"],
        review["process_result"],
    )
    target_xp = reward[1] if reward and review["body_length"] >= 500 else 0

    # 회원 XP 행을 잠근 뒤 이력 합산 및 레벨 변경을 한 트랜잭션에서 처리한다.
    cursor.execute(
        """
        INSERT INTO member_levels (member_id)
        VALUES (%s)
        ON CONFLICT (member_id) DO NOTHING
        """,
        (member_id,),
    )
    cursor.execute(
        """
        SELECT total_xp FROM member_levels
        WHERE member_id = %s FOR UPDATE
        """,
        (member_id,),
    )
    total_xp = cursor.fetchone()["total_xp"]

    # 후기 최초 지급 + 기존 수정 차액을 합산한다. 기타 보상은 합산하지 않는다.
    cursor.execute(
        """
        SELECT COALESCE(SUM(xp_change), 0) AS review_xp
        FROM member_xp_history
        WHERE member_id = %s
          AND source_type = 'POST'
          AND source_id = %s
          AND activity_type IN (
              'CAREER_DOCUMENT', 'CAREER_INTERVIEW',
              'CAREER_SUCCESS', 'CAREER_ADJUST'
          )
        """,
        (member_id, post_id),
    )
    current_xp = int(cursor.fetchone()["review_xp"])
    difference = target_xp - current_xp
    if difference == 0:
        return {"adjusted": False, "xp_change": 0, "total_xp": total_xp}

    # 삭제되어 이미 회수된 게시글에 추가 XP가 지급되지 않도록 검사한다.
    cursor.execute(
        """
        SELECT 1 FROM member_xp_history
        WHERE member_id = %s AND event_key = %s
        """,
        (member_id, f"REVOKE:POST:{post_id}"),
    )
    if cursor.fetchone():
        raise ValueError("이미 XP를 회수한 후기는 수정 정산할 수 없습니다.")

    new_total = total_xp + difference
    if new_total < 0:
        raise ValueError("XP 정산 후 누적 XP가 음수가 됩니다.")

    # 원래 지급 기록을 덮어쓰지 않고 차액을 별도 이력으로 남긴다.
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    event_key = f"ADJUST:POST:{post_id}:{uuid4().hex}"
    cursor.execute(
        """
        INSERT INTO member_xp_history
            (member_id, activity_type, source_type,
             source_id, event_key, xp_change, activity_date)
        VALUES (%s, 'CAREER_ADJUST', 'POST', %s, %s, %s, %s)
        """,
        (member_id, post_id, event_key, difference, today),
    )
    cursor.execute(
        """
        UPDATE member_levels
        SET total_xp = %s, level = %s, updated_at = CURRENT_TIMESTAMP
        WHERE member_id = %s
        """,
        (new_total, calculate_level(new_total), member_id),
    )
    return {"adjusted": True, "xp_change": difference, "total_xp": new_total}


# 게시글 좋아요로 작성자에게 +1XP 지급
# 호출자는 같은 트랜잭션에서 새 좋아요 INSERT가 성공한 경우에만 이 함수를 호출한다.
def grant_post_like_xp(cursor, post_id: int, liker_member_id: int) -> dict:
    """다른 회원의 새로운 좋아요에 대해 글당 최대 10XP를 지급한다."""
    if post_id <= 0 or liker_member_id <= 0:
        return {"awarded": False, "reason": "INVALID_ID"}

    # 같은 게시글의 좋아요 보상과 삭제 처리를 직렬화한다.
    cursor.execute(
        """
        SELECT author_member_id
        FROM posts
        WHERE post_id = %s
          AND post_status = 'PUBLISHED'
          AND deleted_at IS NULL
        FOR UPDATE
        """,
        (post_id,),
    )
    post = cursor.fetchone()
    if post is None:
        return {"awarded": False, "reason": "INVALID_POST"}

    author_id = post["author_member_id"]
    if author_id is None or author_id <= 0:
        return {"awarded": False, "reason": "INVALID_AUTHOR"}
    if author_id == liker_member_id:
        return {"awarded": False, "reason": "SELF_LIKE"}

    # 실제로 좋아요가 등록되어 있는지 확인한다.
    cursor.execute(
        """
        SELECT 1 FROM post_likes
        WHERE post_id = %s AND member_id = %s
        """,
        (post_id, liker_member_id),
    )
    if cursor.fetchone() is None:
        return {"awarded": False, "reason": "LIKE_NOT_FOUND"}

    # 같은 회원이 좋아요를 취소하고 다시 눌러도 최초 한 번만 보상한다.
    event_key = f"POST_LIKE:{post_id}:{liker_member_id}"

    cursor.execute(
        """
        INSERT INTO member_levels (member_id)
        VALUES (%s)
        ON CONFLICT (member_id) DO NOTHING
        """,
        (author_id,),
    )
    cursor.execute(
        """
        SELECT total_xp FROM member_levels
        WHERE member_id = %s FOR UPDATE
        """,
        (author_id,),
    )
    total_xp = cursor.fetchone()["total_xp"]

    cursor.execute(
        """
        SELECT 1 FROM member_xp_history
        WHERE member_id = %s AND event_key = %s
        """,
        (author_id, event_key),
    )
    if cursor.fetchone():
        return {"awarded": False, "reason": "DUPLICATE"}

    # 동일 게시글에서 좋아요 보상은 최대 10번까지만 지급한다.
    cursor.execute(
        """
        SELECT COUNT(*) AS reward_count
        FROM member_xp_history
        WHERE member_id = %s
          AND activity_type = 'POST_LIKE'
          AND source_type = 'POST'
          AND source_id = %s
          AND xp_change > 0
        """,
        (author_id, post_id),
    )
    if cursor.fetchone()["reward_count"] >= 10:
        return {"awarded": False, "reason": "POST_LIKE_LIMIT"}

    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    cursor.execute(
        """
        INSERT INTO member_xp_history
            (member_id, activity_type, source_type,
             source_id, event_key, xp_change, activity_date)
        VALUES (%s, 'POST_LIKE', 'POST', %s, %s, 1, %s)
        """,
        (author_id, post_id, event_key, today),
    )

    new_total = total_xp + 1
    cursor.execute(
        """
        UPDATE member_levels
        SET total_xp = %s,
            level = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE member_id = %s
        """,
        (new_total, calculate_level(new_total), author_id),
    )
    return {
        "awarded": True,
        "earned_xp": 1,
        "receiver_member_id": author_id,
        "total_xp": new_total,
    }


# 게시글·댓글 삭제 시 해당 작성 보상을 한 번만 회수한다.
# 후기 수정으로 추가되거나 차감된 XP까지 순액 기준으로 회수한다.
def revoke_xp(cursor, member_id: int, source_type: str, source_id: int) -> bool:
    if source_type not in ("POST", "COMMENT"):
        raise ValueError("지원하지 않는 활동 유형입니다.")
    if member_id <= 0 or source_id <= 0:
        return False

    event_key = f"{source_type}:{source_id}"
    revoke_key = f"REVOKE:{event_key}"

    cursor.execute(
        """
        SELECT total_xp FROM member_levels
        WHERE member_id = %s FOR UPDATE
        """,
        (member_id,),
    )
    level_row = cursor.fetchone()
    if level_row is None:
        return False

    cursor.execute(
        """
        SELECT 1 FROM member_xp_history
        WHERE member_id = %s AND event_key = %s
        """,
        (member_id, revoke_key),
    )
    if cursor.fetchone():
        return False

    # 일반 게시글, 취업 후기, 댓글·대댓글의 작성 보상만 회수한다.
    reward_types = (
        ["POST", "CAREER_DOCUMENT", "CAREER_INTERVIEW", "CAREER_SUCCESS", "CAREER_ADJUST"]
        if source_type == "POST" else ["COMMENT", "REPLY"]
    )
    cursor.execute(
        """
        SELECT COALESCE(SUM(xp_change), 0) AS earned_xp
        FROM member_xp_history
        WHERE member_id = %s
          AND source_type = %s
          AND source_id = %s
          AND activity_type = ANY(%s)
        """,
        (member_id, source_type, source_id, reward_types),
    )
    earned_xp = int(cursor.fetchone()["earned_xp"])
    if earned_xp <= 0:
        return False

    new_total = level_row["total_xp"] - earned_xp
    if new_total < 0:
        raise ValueError("회수할 XP가 현재 XP보다 많습니다.")

    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    cursor.execute(
        """
        INSERT INTO member_xp_history
            (member_id, activity_type, source_type,
             source_id, event_key, xp_change, activity_date)
        VALUES (%s, 'REVOKE', %s, %s, %s, %s, %s)
        """,
        (member_id, source_type, source_id, revoke_key, -earned_xp, today),
    )
    cursor.execute(
        """
        UPDATE member_levels
        SET total_xp = %s, level = %s, updated_at = CURRENT_TIMESTAMP
        WHERE member_id = %s
        """,
        (new_total, calculate_level(new_total), member_id),
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
