from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.db_connect import db_cursor  # noqa: E402


def main() -> None:
    with db_cursor() as cursor:
        cursor.execute("SELECT current_database() AS database, current_user AS username")
        connection = cursor.fetchone()
        cursor.execute(
            """SELECT table_name FROM information_schema.tables
               WHERE table_schema='public'
                 AND table_name = ANY(%s)
               ORDER BY table_name""",
            (["members", "posts", "recruits", "boards", "comments"],),
        )
        tables = [row["table_name"] for row in cursor.fetchall()]
    print(f"연결 성공: database={connection['database']}, user={connection['username']}")
    print("확인된 테이블: " + ", ".join(tables))


if __name__ == "__main__":
    main()
