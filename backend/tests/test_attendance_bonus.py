
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from backend.app.core.database import get_db_connection
from backend.app.services.xp_service import grant_attendance_bonus


today = datetime.now(ZoneInfo("Asia/Seoul")).date()

with get_db_connection() as conn:
    with conn.cursor() as cursor:

        # 실제 테이블과 구조가 같은 임시 테이블 생성
        cursor.execute("""
            CREATE TEMP TABLE member_xp_history
            (LIKE public.member_xp_history INCLUDING ALL)
            ON COMMIT DROP
        """)

        cursor.execute("SET LOCAL search_path TO pg_temp, public")

        for days, expected_xp in [(7, 5), (30, 20)]:

            # 이전 테스트 기록 초기화 (임시 테이블만)
            cursor.execute("DELETE FROM member_xp_history")

            # 연속 출석 기록 생성
            for i in range(days):
                attendance_date = today - timedelta(days=i)

                cursor.execute("""
                    INSERT INTO member_xp_history
                    (member_id, activity_type, event_key,
                    xp_change, activity_date)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    1,
                    "ATTEND",
                    f"ATTEND:{attendance_date}",
                    1,
                    attendance_date
                ))

            # 최초 보너스 지급
            first = grant_attendance_bonus(cursor, 1, today)

            # 동일 보너스 중복 지급 시도
            second = grant_attendance_bonus(cursor, 1, today)

            print(f"{days}일 연속 출석: +{first}XP")
            print(f"중복 지급 시도: +{second}XP")

            assert first == expected_xp
            assert second == 0

print("연속 출석 보너스 테스트 통과!")
