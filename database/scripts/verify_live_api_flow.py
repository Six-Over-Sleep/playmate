"""Verify the live API against PostgreSQL and remove only its own test rows."""
import os
from pathlib import Path
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.db_connect import db_cursor  # noqa: E402

def main() -> None:
    name = f"CODEX_VERIFY_{int(time.time())}"
    image_path = Path(os.environ["VERIFY_IMAGE_PATH"])
    board_id = post_id = comment_id = None
    with db_cursor() as cursor:
        cursor.execute("SELECT member_id FROM members ORDER BY member_id LIMIT 1")
        member_id = cursor.fetchone()["member_id"]
    headers = {"X-Dev-Member-ID": str(member_id)}
    try:
        with httpx.Client(base_url="http://127.0.0.1:8000", timeout=20) as client:
            response = client.post("/api/boards", headers=headers, json={"name": name, "category": "자유", "description": "통합 검증용", "creation_reason": "자동 검증"})
            response.raise_for_status(); board_id = response.json()["id"]
            with image_path.open("rb") as image:
                response = client.post(f"/api/boards/{board_id}/posts", headers=headers, data={"title": name, "body": "PostgreSQL 통합 검증 본문\n줄바꿈 유지"}, files={"images": (image_path.name, image, "image/png")})
            response.raise_for_status(); post_id = response.json()["id"]
            response = client.post(f"/api/boards/{board_id}/posts/{post_id}/comments", headers=headers, json={"body": "PostgreSQL 통합 검증 댓글"})
            response.raise_for_status(); comment_id = response.json()["id"]
            post = client.get(f"/api/boards/{board_id}/posts/{post_id}", headers=headers); post.raise_for_status()
            comments = client.get(f"/api/boards/{board_id}/posts/{post_id}/comments", headers=headers); comments.raise_for_status()
            assert post.json()["title"] == name and len(post.json()["images"]) == 1
            assert len(comments.json()) == 1 and comments.json()[0]["body"] == "PostgreSQL 통합 검증 댓글"
            print("live_flow=ok board=created post=created image=stored comment=created reread=ok")
    finally:
        stored_names: list[str] = []
        with db_cursor(commit=True) as cursor:
            if post_id:
                cursor.execute("SELECT stored_name FROM post_images WHERE post_id=%s", (post_id,))
                stored_names = [row["stored_name"] for row in cursor.fetchall()]
                if comment_id: cursor.execute("DELETE FROM comments WHERE comment_id=%s AND post_id=%s", (comment_id, post_id))
                cursor.execute("DELETE FROM post_images WHERE post_id=%s", (post_id,))
                cursor.execute("DELETE FROM posts WHERE post_id=%s AND title=%s AND NOT EXISTS (SELECT 1 FROM recruits WHERE recruits.post_id=posts.post_id)", (post_id, name))
            if board_id:
                cursor.execute("DELETE FROM boards WHERE board_id=%s AND board_name=%s AND NOT EXISTS (SELECT 1 FROM posts WHERE posts.board_id=boards.board_id)", (board_id, name))
        for stored_name in stored_names:
            path = (ROOT / "uploads" / stored_name).resolve()
            if ROOT / "uploads" in path.parents: path.unlink(missing_ok=True)

if __name__ == "__main__": main()
