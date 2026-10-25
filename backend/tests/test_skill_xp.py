
from contextlib import nullcontext
from unittest.mock import patch

from backend.app.core.database import get_db_connection
from backend.app.services import skill_xp_service


conn = get_db_connection()

try:
    with conn.cursor() as cursor:
        # 실제 테이블 대신 임시 테이블 사용
        cursor.execute("""
            CREATE TEMP TABLE member_skill_levels
            (LIKE public.member_skill_levels INCLUDING ALL)
            ON COMMIT DROP
        """)

        cursor.execute("""
            CREATE TEMP TABLE member_skill_xp_history
            (LIKE public.member_skill_xp_history INCLUDING ALL)
            ON COMMIT DROP
        """)

        cursor.execute("SET LOCAL search_path TO pg_temp, public")

    # 테스트에서는 기존 DB 연결 대신 임시 테이블 연결 사용
    with patch.object(
        skill_xp_service,
        "get_db_connection",
        return_value=nullcontext(conn)
    ):
        # 최초 정답
        first = skill_xp_service.grant_skill_xp(
            1, "PYTHON", "QUIZ", 10001, "VARIABLES"
        )

        # 같은 문제 중복 정답
        duplicate = skill_xp_service.grant_skill_xp(
            1, "PYTHON", "QUIZ", 10001, "VARIABLES"
        )

        # 나머지 9문제 정답
        for problem_id in range(10002, 10011):
            result = skill_xp_service.grant_skill_xp(
                1, "PYTHON", "QUIZ", problem_id, "VARIABLES"
            )

        print("최초 지급:", first)
        print("중복 지급:", duplicate)
        print("10문제 완료:", result)

        assert first["earned_xp"] == 5
        assert duplicate["reason"] == "DUPLICATE"
        assert result["total_xp"] == 50
        assert result["level"] == 2

    print("스킬 XP 테스트 통과!")

finally:
    # 테스트 데이터 롤백
    conn.rollback()
    conn.close()
