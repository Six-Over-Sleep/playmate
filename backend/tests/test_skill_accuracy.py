
from contextlib import nullcontext
from unittest.mock import patch

from backend.app.core.database import get_db_connection
from backend.app.routers import mypage


conn = get_db_connection()

try:
    with conn.cursor() as cursor:
        # 실제 DB가 아닌 임시 테이블 사용
        cursor.execute("""
            CREATE TEMP TABLE member_skill_attempts
            (LIKE public.member_skill_attempts INCLUDING ALL)
            ON COMMIT DROP
        """)

        cursor.execute("SET LOCAL search_path TO pg_temp, public")

        # 테스트 데이터 생성
        test_data = (
            [(1, 1000+i, "PYTHON", "VARIABLES", i < 7) for i in range(10)]
            + [(1, 2000+i, "PYTHON", "FUNCTIONS", i < 1) for i in range(4)]
            + [(1, 3000+i, "SQL", "JOIN", i < 4) for i in range(5)]
        )

        cursor.executemany("""
            INSERT INTO member_skill_attempts
            (member_id, problem_id, skill_code, topic_code, is_correct)
            VALUES (%s, %s, %s, %s, %s)
        """, test_data)

    # 실제 조회 함수로 정답률 검증
    with patch.object(
        mypage,
        "get_db_connection",
        return_value=nullcontext(conn)
    ):
        results = mypage.get_my_skill_accuracy(member_id=1)

    expected = {
        ("PYTHON", "VARIABLES"): 70.0,
        ("PYTHON", "FUNCTIONS"): 25.0,
        ("SQL", "JOIN"): 80.0,
    }

    assert len(results) == 3

    for row in results:
        key = (row["skill_code"], row["topic_code"])
        print(key, "정답률:", row["accuracy_percent"], "%")
        assert row["accuracy_percent"] == expected[key]

    print("스킬 정답률 테스트 통과!")

finally:
    # 테스트 변경사항 폐기
    conn.rollback()
    conn.close()
