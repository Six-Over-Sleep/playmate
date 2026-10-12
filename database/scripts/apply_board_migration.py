from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.db_connect import get_connection  # noqa: E402


def main() -> None:
    migration = ROOT / "database" / "sql" / "001_board_mvp.sql"
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(migration.read_text(encoding="utf-8"))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    print("게시판 MVP 마이그레이션 적용 완료")


if __name__ == "__main__":
    main()
