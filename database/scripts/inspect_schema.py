from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.db_connect import db_cursor  # noqa: E402

TABLES = ("members", "posts", "recruits", "boards", "comments", "post_images")

def main() -> None:
    with db_cursor() as cursor:
        cursor.execute("SELECT current_database() AS database_name, version() AS server_version")
        server = cursor.fetchone()
        print(f"database={server['database_name']}; server={server['server_version'].split('-')[0]}")
        cursor.execute(
            """SELECT table_name, column_name, data_type, is_nullable,
                         CASE WHEN column_name IN (
                           SELECT kcu.column_name FROM information_schema.table_constraints tc
                           JOIN information_schema.key_column_usage kcu
                             ON tc.constraint_name=kcu.constraint_name AND tc.table_schema=kcu.table_schema
                           WHERE tc.constraint_type='PRIMARY KEY' AND tc.table_schema='public'
                         ) THEN 'PRI' ELSE '' END AS column_key
                  FROM information_schema.columns
                 WHERE table_schema='public' AND table_name = ANY(%s)
                 ORDER BY table_name, ordinal_position""",
            (list(TABLES),),
        )
        rows = cursor.fetchall()
    current = None
    for row in rows:
        if row["table_name"] != current:
            current = row["table_name"]
            print(f"[{current}]")
        print(f"  {row['column_name']} {row['data_type']} nullable={row['is_nullable']} key={row['column_key'] or '-'}")

if __name__ == "__main__":
    main()
