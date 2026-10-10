"""Remove only CODEX_VERIFY_* rows created by the live verification flow."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.db_connect import db_cursor  # noqa: E402

def main() -> None:
    board_id = int(os.environ["VERIFY_BOARD_ID"])
    post_id = int(os.environ["VERIFY_POST_ID"]) if os.getenv("VERIFY_POST_ID") else None
    comment_id = int(os.environ["VERIFY_COMMENT_ID"]) if os.getenv("VERIFY_COMMENT_ID") else None
    stored_names: list[str] = []
    with db_cursor(commit=True) as cursor:
        cursor.execute("SELECT board_name FROM boards WHERE board_id=%s FOR UPDATE", (board_id,))
        board = cursor.fetchone()
        if not board or not board["board_name"].startswith("CODEX_VERIFY_"):
            raise RuntimeError("검증용 게시판 이름이 아니므로 정리를 중단합니다.")
        if post_id is None:
            cursor.execute("SELECT 1 FROM posts WHERE board_id=%s", (board_id,))
            if cursor.fetchone(): raise RuntimeError("게시글이 있는 게시판이므로 정리를 중단합니다.")
            cursor.execute("DELETE FROM boards WHERE board_id=%s", (board_id,))
            print("검증용 빈 게시판 정리 완료")
            return
        cursor.execute("SELECT title FROM posts WHERE post_id=%s AND board_id=%s FOR UPDATE", (post_id, board_id))
        post = cursor.fetchone()
        if not post or not post["title"].startswith("CODEX_VERIFY_"):
            raise RuntimeError("검증용 게시글 제목이 아니므로 정리를 중단합니다.")
        cursor.execute("SELECT 1 FROM recruits WHERE post_id=%s", (post_id,))
        if cursor.fetchone(): raise RuntimeError("모임 참조가 있어 정리를 중단합니다.")
        cursor.execute("SELECT stored_name FROM post_images WHERE post_id=%s", (post_id,))
        stored_names = [row["stored_name"] for row in cursor.fetchall()]
        if comment_id is not None:
            cursor.execute("DELETE FROM comments WHERE comment_id=%s AND post_id=%s", (comment_id, post_id))
        cursor.execute("DELETE FROM post_images WHERE post_id=%s", (post_id,))
        cursor.execute("DELETE FROM posts WHERE post_id=%s AND board_id=%s", (post_id, board_id))
        cursor.execute("DELETE FROM boards WHERE board_id=%s", (board_id,))
    for stored_name in stored_names:
        path = (ROOT / "uploads" / stored_name).resolve()
        if ROOT / "uploads" in path.parents: path.unlink(missing_ok=True)
    print("검증용 데이터 정리 완료")

if __name__ == "__main__": main()
