from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.db_connect import db_cursor  # noqa: E402

def main() -> None:
    with db_cursor() as cursor:
        cursor.execute("""SELECT tc.table_name, tc.constraint_name, tc.constraint_type
          FROM information_schema.table_constraints tc
          WHERE tc.table_schema='public' AND tc.table_name = ANY(%s)
          ORDER BY tc.table_name, tc.constraint_type, tc.constraint_name""", (["boards","posts","comments","recruits"],))
        print("[constraints]")
        for row in cursor.fetchall(): print(f"{row['table_name']} {row['constraint_type']} {row['constraint_name']}")
        cursor.execute("SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE lower(board_name)=lower('자유게시판')) AS free_count FROM boards")
        print("[boards]", dict(cursor.fetchone()))
        for table in ("members","posts","comments","recruits","post_images"):
            cursor.execute(f"SELECT COUNT(*) AS total FROM {table}")
            print(f"[{table}] total={cursor.fetchone()['total']}")
        cursor.execute("""SELECT COUNT(*) AS orphan_count FROM posts p LEFT JOIN boards b ON b.board_id=p.board_id
                          WHERE p.board_id IS NOT NULL AND b.board_id IS NULL""")
        print("[post_board_orphans]", cursor.fetchone()["orphan_count"])

if __name__ == "__main__": main()
