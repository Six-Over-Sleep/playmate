"""운영·개발 DB 연결 확인 스크립트(테스트 아님, pytest 수집 대상 아님).

.env에 설정된 DB에 실제로 접속해 현재 DB·계정 이름과 public 테이블 목록을 출력한다.
읽기 전용 조회만 수행하며, 접속 대상을 확인한 사람이 명시적으로 실행할 때만 사용한다.

사용: 프로젝트 루트에서  python -m backend.scripts.check_db_connection
(기존 backend/tests/test_database.py를 테스트에서 분리한 것)
"""

from sqlalchemy import text


def main() -> None:
    """설정된 DB에 접속해 연결 정보와 public 테이블 목록을 출력한다."""
    from backend.app.core.database import engine

    with engine.connect() as conn:
        result = conn.execute(text("SELECT current_database(), current_user"))
        print("DB 연결 성공:", result.fetchone())

        tables = conn.execute(text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
        """))

        for table in tables:
            print(table[0])


if __name__ == "__main__":
    main()
