from backend.app.core.database import get_db_connection

# 스킬 레벨 계산

def calculate_skill_level(total_xp: int) -> int:
    if total_xp < 0:
        raise ValueError("스킬 XP는 음수일 수 없습니다.")

    if total_xp >= 500:
        return 5
    elif total_xp >= 300:
        return 4
    elif total_xp >= 150:
        return 3
    elif total_xp >= 50:
        return 2
    else:
        return 1


# 학습 활동별 XP 지급 기준
SKILL_XP_RULES = {
    "QUIZ": 5,        # 객관식·단답형 정답
    "PRACTICE": 10,   # 코드 실습 완료
    "ADVANCED": 20    # 심화 문제 해결
}

# 지원하는 스킬
SKILL_CODES = {
    "PYTHON", "SQL", "GIT", "REACT", "LANGCHAIN"
}


def grant_skill_xp(
    member_id: int,
    skill_code: str,
    activity_type: str,
    problem_id: int,
    topic_code: str | None = None
):
    """검증된 학습 문제에 대해 스킬 XP 지급"""

    if member_id <= 0 or problem_id <= 0:
        raise ValueError("회원 ID 또는 문제 ID가 올바르지 않습니다.")

    if skill_code not in SKILL_CODES:
        raise ValueError("지원하지 않는 스킬입니다.")

    if activity_type not in SKILL_XP_RULES:
        raise ValueError("지원하지 않는 학습 활동입니다.")

    xp = SKILL_XP_RULES[activity_type]
    event_key = f"PROBLEM:{problem_id}"

    with get_db_connection() as conn:
        with conn.cursor() as cursor:

            # 1. 회원 스킬 정보가 없으면 생성
            cursor.execute(
                """
                INSERT INTO member_skill_levels
                    (member_id, skill_code)
                VALUES (%s, %s)
                ON CONFLICT (member_id, skill_code)
                DO NOTHING
                """,
                (member_id, skill_code)
            )

            # 2. 현재 XP 조회 및 동시 요청 방지
            cursor.execute(
                """
                SELECT total_xp
                FROM member_skill_levels
                WHERE member_id = %s
                  AND skill_code = %s
                FOR UPDATE
                """,
                (member_id, skill_code)
            )

            total_xp = cursor.fetchone()[0]

            # 3. XP 이력 저장 (동일 문제 중복 지급 방지)
            cursor.execute(
                """
                INSERT INTO member_skill_xp_history
                    (member_id, skill_code, activity_type,
                     topic_code, event_key, xp_change)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (member_id, skill_code, event_key)
                DO NOTHING
                RETURNING history_id
                """,
                (
                    member_id, skill_code, activity_type,
                    topic_code, event_key, xp
                )
            )

            if cursor.fetchone() is None:
                return {
                    "awarded": False,
                    "reason": "DUPLICATE"
                }

            # 4. 스킬 XP 및 레벨 갱신
            new_xp = total_xp + xp
            new_level = calculate_skill_level(new_xp)

            cursor.execute(
                """
                UPDATE member_skill_levels
                SET total_xp = %s,
                    level = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE member_id = %s
                    AND skill_code = %s
                """,
                (new_xp, new_level, member_id, skill_code)
            )

    return {
        "awarded": True,
        "earned_xp": xp,
        "skill_code": skill_code,
        "total_xp": new_xp,
        "level": new_level
    }
