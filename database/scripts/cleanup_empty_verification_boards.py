"""Delete only empty CODEX_VERIFY_* boards left by a failed live test."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.db_connect import db_cursor  # noqa: E402

def main() -> None:
    with db_cursor(commit=True) as cursor:
        cursor.execute("""DELETE FROM boards b
          WHERE LEFT(b.board_name, 13)='CODEX_VERIFY_'
            AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.board_id=b.board_id)
          RETURNING board_id""")
        removed = cursor.fetchall()
    print(f"빈 검증용 게시판 정리: {len(removed)}개")

if __name__ == "__main__": main()
