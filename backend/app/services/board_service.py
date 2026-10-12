from typing import Any

from psycopg2 import errors
from fastapi import HTTPException

from app.core.db_connect import db_cursor

BOARD_POST_TYPE = "BOARD"

def _board_post_guard(alias: str = "p") -> str:
    return f"{alias}.deleted_at IS NULL AND NOT EXISTS (SELECT 1 FROM recruits r WHERE r.post_id={alias}.post_id)"

def _images(cursor, post_id: int) -> list[dict[str, Any]]:
    cursor.execute("SELECT image_id AS id, '/uploads/' || stored_name AS url, original_name FROM post_images WHERE post_id=%s ORDER BY display_order,image_id", (post_id,))
    return list(cursor.fetchall())

def list_boards() -> list[dict[str, Any]]:
    with db_cursor() as cursor:
        cursor.execute("""SELECT board_id AS id, board_name AS name, description, category, created_at
                            FROM boards ORDER BY is_default DESC, created_at, board_id""")
        return list(cursor.fetchall())

def create_board(name: str, category: str, description: str | None, creation_reason: str | None, member_id: int) -> dict[str, Any]:
    try:
        with db_cursor(commit=True) as cursor:
            cursor.execute("INSERT INTO boards(board_name,category,description,creation_reason,created_by) VALUES(%s,%s,%s,%s,%s) RETURNING board_id", (name, category, description or None, creation_reason or None, member_id))
            board_id = cursor.fetchone()["board_id"]
    except errors.UniqueViolation as exc:
        raise HTTPException(status_code=409, detail="이미 같은 이름의 게시판이 있습니다.") from exc
    return get_board(board_id)

def get_board(board_id: int) -> dict[str, Any]:
    with db_cursor() as cursor:
        cursor.execute("SELECT board_id AS id,board_name AS name,description,category,created_at FROM boards WHERE board_id=%s", (board_id,))
        row = cursor.fetchone()
        if row is None: raise HTTPException(status_code=404, detail="게시판을 찾을 수 없습니다.")
        return row

def list_posts(board_id: int, q: str | None, sort: str, member_id: int) -> list[dict[str, Any]]:
    if sort != "latest": raise HTTPException(status_code=422, detail="sort는 latest만 지원합니다.")
    get_board(board_id)
    search = (q or "").strip()
    params: list[Any] = [member_id, board_id]
    condition = ""
    if search:
        condition = " AND (p.title ILIKE %s OR p.body ILIKE %s)"
        params += [f"%{search}%", f"%{search}%"]
    with db_cursor() as cursor:
        cursor.execute(f"""SELECT p.post_id AS id,p.board_id,p.title,COALESCE(p.body,'') AS body,
                 p.author_member_id AS author_id,COALESCE(m.public_anonymous_id,'익명') AS author_name,
                 p.created_at,p.updated_at,
                 COUNT(c.comment_id) FILTER (WHERE c.deleted_at IS NULL)::int AS comment_count,
                 (p.author_member_id=%s) AS is_owner
            FROM posts p JOIN members m ON m.member_id=p.author_member_id
            LEFT JOIN comments c ON c.post_id=p.post_id
           WHERE p.board_id=%s AND {_board_post_guard()} {condition}
           GROUP BY p.post_id,p.board_id,p.title,p.body,p.author_member_id,m.public_anonymous_id,p.created_at,p.updated_at
           ORDER BY p.created_at DESC,p.post_id DESC""", params)
        rows = list(cursor.fetchall())
        for row in rows: row["images"] = _images(cursor, row["id"])
        return rows

def create_post(board_id: int, title: str, body: str, member_id: int, images: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    get_board(board_id)
    with db_cursor(commit=True) as cursor:
        cursor.execute("""INSERT INTO posts(board_id,author_member_id,post_type,title,body,source_type,post_status,published_at)
                          VALUES(%s,%s,%s,%s,%s,'USER','PUBLISHED',CURRENT_TIMESTAMP) RETURNING post_id""", (board_id, member_id, BOARD_POST_TYPE, title, body))
        post_id = cursor.fetchone()["post_id"]
        for order, image in enumerate(images or []):
            cursor.execute("INSERT INTO post_images(post_id,stored_name,original_name,content_type,file_size,display_order) VALUES(%s,%s,%s,%s,%s,%s)", (post_id,image["stored_name"],image["original_name"],image["content_type"],image["file_size"],order))
    return get_post(board_id, post_id, member_id)

def get_post(board_id: int, post_id: int, member_id: int) -> dict[str, Any]:
    with db_cursor() as cursor:
        cursor.execute(f"""SELECT p.post_id AS id,p.board_id,p.title,COALESCE(p.body,'') AS body,
                 p.author_member_id AS author_id,COALESCE(m.public_anonymous_id,'익명') AS author_name,
                 p.created_at,p.updated_at,
                 (SELECT COUNT(*) FROM comments c WHERE c.post_id=p.post_id AND c.deleted_at IS NULL) AS comment_count,
                 (p.author_member_id=%s) AS is_owner
            FROM posts p JOIN members m ON m.member_id=p.author_member_id
           WHERE p.board_id=%s AND p.post_id=%s AND {_board_post_guard()}""", (member_id,board_id,post_id))
        row = cursor.fetchone()
        if row is None: raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
        row["images"] = _images(cursor, post_id)
        return row

def update_post(board_id: int, post_id: int, title: str, body: str, member_id: int) -> dict[str, Any]:
    with db_cursor(commit=True) as cursor:
        cursor.execute(f"UPDATE posts AS p SET title=%s,body=%s,updated_at=CURRENT_TIMESTAMP WHERE p.board_id=%s AND p.post_id=%s AND p.author_member_id=%s AND {_board_post_guard()}", (title,body,board_id,post_id,member_id))
        if cursor.rowcount == 0: _raise_post_permission(cursor,board_id,post_id)
    return get_post(board_id,post_id,member_id)

def delete_post(board_id: int, post_id: int, member_id: int) -> None:
    with db_cursor(commit=True) as cursor:
        cursor.execute(f"UPDATE posts AS p SET deleted_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE p.board_id=%s AND p.post_id=%s AND p.author_member_id=%s AND {_board_post_guard()}", (board_id,post_id,member_id))
        if cursor.rowcount == 0: _raise_post_permission(cursor,board_id,post_id)

def _raise_post_permission(cursor, board_id: int, post_id: int) -> None:
    cursor.execute(f"SELECT 1 FROM posts p WHERE p.board_id=%s AND p.post_id=%s AND {_board_post_guard()}",(board_id,post_id))
    if cursor.fetchone(): raise HTTPException(status_code=403, detail="작성자만 수정하거나 삭제할 수 있습니다.")
    raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")

def list_comments(board_id: int, post_id: int, member_id: int) -> list[dict[str, Any]]:
    get_post(board_id,post_id,member_id)
    with db_cursor() as cursor:
        cursor.execute("""SELECT c.comment_id AS id,c.post_id,c.body,c.author_member_id AS author_id,
            COALESCE(m.public_anonymous_id,'익명') AS author_name,c.created_at,c.updated_at,(c.author_member_id=%s) AS is_owner
            FROM comments c JOIN members m ON m.member_id=c.author_member_id
            WHERE c.post_id=%s AND c.deleted_at IS NULL ORDER BY c.created_at,c.comment_id""",(member_id,post_id))
        return list(cursor.fetchall())

def create_comment(board_id: int, post_id: int, body: str, member_id: int) -> dict[str, Any]:
    get_post(board_id,post_id,member_id)
    with db_cursor(commit=True) as cursor:
        cursor.execute("INSERT INTO comments(post_id,author_member_id,body) VALUES(%s,%s,%s) RETURNING comment_id",(post_id,member_id,body)); comment_id=cursor.fetchone()["comment_id"]
    return get_comment(comment_id,member_id)

def get_comment(comment_id: int, member_id: int) -> dict[str, Any]:
    with db_cursor() as cursor:
        cursor.execute("""SELECT c.comment_id AS id,c.post_id,c.body,c.author_member_id AS author_id,
            COALESCE(m.public_anonymous_id,'익명') AS author_name,c.created_at,c.updated_at,(c.author_member_id=%s) AS is_owner
            FROM comments c JOIN members m ON m.member_id=c.author_member_id WHERE c.comment_id=%s AND c.deleted_at IS NULL""",(member_id,comment_id))
        row=cursor.fetchone()
        if row is None: raise HTTPException(status_code=404, detail="댓글을 찾을 수 없습니다.")
        return row

def update_comment(comment_id: int, body: str, member_id: int) -> dict[str, Any]:
    with db_cursor(commit=True) as cursor:
        cursor.execute("UPDATE comments SET body=%s,updated_at=CURRENT_TIMESTAMP WHERE comment_id=%s AND author_member_id=%s AND deleted_at IS NULL",(body,comment_id,member_id))
        if cursor.rowcount == 0: _raise_comment_permission(cursor,comment_id)
    return get_comment(comment_id,member_id)

def delete_comment(comment_id: int, member_id: int) -> None:
    with db_cursor(commit=True) as cursor:
        cursor.execute("UPDATE comments SET deleted_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE comment_id=%s AND author_member_id=%s AND deleted_at IS NULL",(comment_id,member_id))
        if cursor.rowcount == 0: _raise_comment_permission(cursor,comment_id)

def _raise_comment_permission(cursor, comment_id: int) -> None:
    cursor.execute("SELECT 1 FROM comments WHERE comment_id=%s AND deleted_at IS NULL",(comment_id,))
    if cursor.fetchone(): raise HTTPException(status_code=403, detail="작성자만 수정하거나 삭제할 수 있습니다.")
    raise HTTPException(status_code=404, detail="댓글을 찾을 수 없습니다.")
