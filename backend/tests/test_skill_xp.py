"""스킬 XP 최초 지급·중복 차단·레벨 계산을 검증한다(로컬 일회용 PostgreSQL 전용).

PLAYMATE_LOCAL_TEST_DB_URL에 로컬이고 이름에 test가 들어간 DB를 지정했을 때만 실행한다.
public 스킬 테이블 구조를 복제한 임시 테이블만 사용하고 끝나면 롤백한다.
import나 직접 실행만으로는 DB에 접속하지 않는다.
"""

from contextlib import nullcontext
from unittest.mock import patch

from backend.app.services import skill_xp_service
from backend.tests.local_test_db import require_local_test_db_url, skip_unless_tables


def test_skill_xp_first_grant_duplicate_and_level():
    """첫 정답 지급, 같은 문제 중복 차단, 10문제 완료 후 누적 XP·레벨을 확인한다."""
    url = require_local_test_db_url()  # 접속 전에 로컬 테스트 DB인지 검사
    import psycopg

    conn = psycopg.connect(url)
    try:
        with conn.cursor() as cursor:
            skip_unless_tables(cursor, "member_skill_levels", "member_skill_xp_history")
            # 실제 테이블 대신 임시 테이블 사용
            cursor.execute(
                """
                CREATE TEMP TABLE member_skill_levels
                (LIKE public.member_skill_levels INCLUDING ALL)
                ON COMMIT DROP
                """
            )
            cursor.execute(
                """
                CREATE TEMP TABLE member_skill_xp_history
                (LIKE public.member_skill_xp_history INCLUDING ALL)
                ON COMMIT DROP
                """
            )
            cursor.execute("SET LOCAL search_path TO pg_temp, public")

        # 서비스가 테스트 DB의 같은 연결(임시 테이블)을 쓰도록 한다.
        with patch.object(skill_xp_service, "get_db_connection", return_value=nullcontext(conn)):
            first = skill_xp_service.grant_skill_xp(1, "PYTHON", "QUIZ", 10001, "VARIABLES")
            duplicate = skill_xp_service.grant_skill_xp(1, "PYTHON", "QUIZ", 10001, "VARIABLES")
            for problem_id in range(10002, 10011):
                result = skill_xp_service.grant_skill_xp(1, "PYTHON", "QUIZ", problem_id, "VARIABLES")

        assert first["earned_xp"] == 5
        assert duplicate["reason"] == "DUPLICATE"
        assert result["total_xp"] == 50
        assert result["level"] == 2
    finally:
        # 테스트 변경 사항 폐기
        conn.rollback()
        conn.close()
