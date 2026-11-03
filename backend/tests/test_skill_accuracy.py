"""스킬·주제별 정답률 계산을 검증한다(로컬 일회용 PostgreSQL 전용).

PLAYMATE_LOCAL_TEST_DB_URL에 로컬이고 이름에 test가 들어간 DB를 지정했을 때만 실행한다.
mypage.get_my_skill_accuracy가 쓰는 db_cursor를 테스트 DB의 한 연결로 바꾸고,
public.member_skill_attempts 구조를 복제한 임시 테이블만 사용한 뒤 롤백한다.
import나 직접 실행만으로는 DB에 접속하지 않는다.
"""

from contextlib import contextmanager

from backend.app.routers import mypage
from backend.tests.local_test_db import require_local_test_db_url, skip_unless_tables


def test_skill_accuracy_per_topic(monkeypatch):
    """주제별 정답 비율이 기대한 백분율로 계산되는지 확인한다."""
    url = require_local_test_db_url()  # 접속 전에 로컬 테스트 DB인지 검사
    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn = psycopg2.connect(url)
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        skip_unless_tables(cursor, "member_skill_attempts")
        # 실제 DB가 아닌 임시 테이블 사용
        cursor.execute(
            """
            CREATE TEMP TABLE member_skill_attempts
            (LIKE public.member_skill_attempts INCLUDING ALL)
            ON COMMIT DROP
            """
        )
        cursor.execute("SET LOCAL search_path TO pg_temp, public")
        test_data = (
            [(1, 1000 + i, "PYTHON", "VARIABLES", i < 7) for i in range(10)]
            + [(1, 2000 + i, "PYTHON", "FUNCTIONS", i < 1) for i in range(4)]
            + [(1, 3000 + i, "SQL", "JOIN", i < 4) for i in range(5)]
        )
        cursor.executemany(
            """
            INSERT INTO member_skill_attempts
            (member_id, problem_id, skill_code, topic_code, is_correct)
            VALUES (%s, %s, %s, %s, %s)
            """,
            test_data,
        )

        @contextmanager
        def same_connection(*args, **kwargs):
            """조회 함수가 임시 테이블이 있는 같은 연결을 쓰도록 한다."""
            yield cursor

        monkeypatch.setattr(mypage, "db_cursor", same_connection)
        results = mypage.get_my_skill_accuracy(member_id=1)

        expected = {
            ("PYTHON", "VARIABLES"): 70.0,
            ("PYTHON", "FUNCTIONS"): 25.0,
            ("SQL", "JOIN"): 80.0,
        }
        assert len(results) == 3
        for row in results:
            assert row["accuracy_percent"] == expected[(row["skill_code"], row["topic_code"])]
    finally:
        # 테스트 변경 사항 폐기
        conn.rollback()
        conn.close()
