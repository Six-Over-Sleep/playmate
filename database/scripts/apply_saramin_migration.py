"""Apply only the Saramin SQL migration using Playmate's existing db_connect.

Run from repository root: python database/scripts/apply_saramin_migration.py
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.db_connect import get_connection  # noqa: E402

SQL_PATH = ROOT / "database" / "sql" / "020_saramin_job_postings.sql"

def main():
    if not SQL_PATH.is_file():
        raise FileNotFoundError(f"마이그레이션 SQL이 없습니다: {SQL_PATH}")
    sql = SQL_PATH.read_text(encoding="utf-8")
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    print("사람인 채용공고 테이블/인덱스 생성 완료")

if __name__ == "__main__":
    main()
