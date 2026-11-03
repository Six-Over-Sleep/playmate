"""연속 출석 보너스 지급과 중복 지급 방지를 검증한다(로컬 일회용 PostgreSQL 전용).

PLAYMATE_LOCAL_TEST_DB_URL에 로컬이고 이름에 test가 들어간 DB를 지정했을 때만 실행한다.
public.member_xp_history 구조를 복제한 임시 테이블만 사용하고 끝나면 롤백한다.
import나 직접 실행만으로는 DB에 접속하지 않는다.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.app.services.xp_service import grant_attendance_bonus
from backend.tests.local_test_db import require_local_test_db_url, skip_unless_tables


@pytest.mark.parametrize("days,expected_xp", [(7, 5), (30, 20)])
def test_attendance_bonus_granted_once(days, expected_xp):
    """연속 출석 일수별 보너스가 한 번만 지급되는지 확인한다."""
    url = require_local_test_db_url()  # 접속 전에 로컬 테스트 DB인지 검사
    import psycopg

    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    conn = psycopg.connect(url)
    try:
        with conn.cursor() as cursor:
            skip_unless_tables(cursor, "member_xp_history")
            # 실제 테이블과 구조가 같은 임시 테이블 생성
            cursor.execute(
                """
                CREATE TEMP TABLE member_xp_history
                (LIKE public.member_xp_history INCLUDING ALL)
                ON COMMIT DROP
                """
            )
            cursor.execute("SET LOCAL search_path TO pg_temp, public")

            # 연속 출석 기록 생성
            for i in range(days):
                attendance_date = today - timedelta(days=i)
                cursor.execute(
                    """
                    INSERT INTO member_xp_history
                    (member_id, activity_type, event_key, xp_change, activity_date)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (1, "ATTEND", f"ATTEND:{attendance_date}", 1, attendance_date),
                )

            # 최초 보너스 지급 후 같은 보너스 중복 지급 시도
            first = grant_attendance_bonus(cursor, 1, today)
            second = grant_attendance_bonus(cursor, 1, today)

            assert first == expected_xp
            assert second == 0
    finally:
        # 테스트 변경 사항 폐기
        conn.rollback()
        conn.close()
