"""관리자용 읽기·쓰기 SQL. 인증 및 트랜잭션은 서비스에서 담당한다."""


def is_admin(cursor, member_id: int) -> bool:
    cursor.execute(
        """
        SELECT 1 FROM members
        WHERE member_id = %s
          AND UPPER(COALESCE(role_code, '')) = 'ADMIN'
        """,
        (member_id,),
    )
    return cursor.fetchone() is not None


def get_dashboard(cursor) -> dict:
    cursor.execute("SELECT COUNT(*)::int AS count FROM members WHERE member_id > 0")
    members = cursor.fetchone()["count"]
    cursor.execute("SELECT COUNT(*)::int AS count FROM posts WHERE deleted_at IS NULL")
    posts = cursor.fetchone()["count"]
    cursor.execute("SELECT COUNT(*)::int AS count FROM recruits")
    recruits = cursor.fetchone()["count"]
    cursor.execute(
        """
        SELECT COUNT(*)::int AS count
        FROM posts AS p JOIN boards AS b ON b.board_id = p.board_id
        WHERE b.board_name = '공지사항' AND p.deleted_at IS NULL
        """
    )
    notices = cursor.fetchone()["count"]
    return {"members": members, "posts": posts, "recruits": recruits, "notices": notices}


def get_notice_board_id(cursor) -> int | None:
    cursor.execute("SELECT board_id FROM boards WHERE board_name = '공지사항' ORDER BY board_id LIMIT 1")
    row = cursor.fetchone()
    return row["board_id"] if row else None


def list_notices(cursor) -> list[dict]:
    cursor.execute(
        """
        SELECT p.post_id AS id, p.board_id, p.title,
               COALESCE(p.body, '') AS body, p.created_at,
               p.updated_at, COALESCE(NULLIF(m.nickname, ''), '관리자') AS author_name
        FROM posts AS p
        JOIN boards AS b ON b.board_id = p.board_id
        JOIN members AS m ON m.member_id = p.author_member_id
        WHERE b.board_name = '공지사항'
          AND p.post_type = 'BOARD'
          AND p.deleted_at IS NULL
        ORDER BY p.created_at DESC NULLS LAST, p.post_id DESC
        LIMIT 200
        """
    )
    return list(cursor.fetchall())


def get_notice(cursor, post_id: int) -> dict | None:
    cursor.execute(
        """
        SELECT p.post_id AS id, p.board_id, p.title, COALESCE(p.body, '') AS body,
               p.created_at, p.updated_at,
               COALESCE(NULLIF(m.nickname, ''), '관리자') AS author_name
        FROM posts AS p
        JOIN boards AS b ON b.board_id = p.board_id
        JOIN members AS m ON m.member_id = p.author_member_id
        WHERE p.post_id = %s AND b.board_name = '공지사항'
          AND p.post_type = 'BOARD' AND p.deleted_at IS NULL
        """,
        (post_id,),
    )
    return cursor.fetchone()


def create_notice(cursor, board_id: int, member_id: int, title: str, body: str) -> int:
    cursor.execute(
        """
        INSERT INTO posts (
            board_id, author_member_id, post_type, title, body,
            source_type, post_status, published_at
        )
        VALUES (%s, %s, 'BOARD', %s, %s, 'USER', 'PUBLISHED', CURRENT_TIMESTAMP)
        RETURNING post_id
        """,
        (board_id, member_id, title, body),
    )
    return cursor.fetchone()["post_id"]


def update_notice(cursor, post_id: int, title: str, body: str) -> bool:
    cursor.execute(
        """
        UPDATE posts AS p SET title = %s, body = %s, updated_at = CURRENT_TIMESTAMP
        WHERE p.post_id = %s AND p.deleted_at IS NULL AND p.post_type = 'BOARD'
          AND EXISTS (
              SELECT 1 FROM boards b WHERE b.board_id = p.board_id AND b.board_name = '공지사항'
          )
        """,
        (title, body, post_id),
    )
    return cursor.rowcount == 1


def delete_notice(cursor, post_id: int) -> bool:
    cursor.execute(
        """
        UPDATE posts AS p
        SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE p.post_id = %s AND p.deleted_at IS NULL AND p.post_type = 'BOARD'
          AND EXISTS (
              SELECT 1 FROM boards b WHERE b.board_id = p.board_id AND b.board_name = '공지사항'
          )
        """,
        (post_id,),
    )
    return cursor.rowcount == 1


def list_board_posts(cursor, search: str) -> list[dict]:
    cursor.execute(
        """
        SELECT p.post_id AS id, p.title, p.board_id,
               b.board_name AS board_name,
               COALESCE(NULLIF(m.nickname, ''), '익명') AS author_name,
               p.created_at, p.post_status,
               (UPPER(COALESCE(p.post_status, 'PUBLISHED')) = 'HIDDEN') AS hidden
        FROM posts AS p
        JOIN boards AS b ON b.board_id = p.board_id
        JOIN members AS m ON m.member_id = p.author_member_id
        WHERE p.post_type = 'BOARD' AND p.deleted_at IS NULL
          AND b.board_name <> '공지사항'
          AND (%s = '' OR p.title ILIKE %s)
        ORDER BY p.created_at DESC NULLS LAST, p.post_id DESC
        LIMIT 200
        """,
        (search, f"%{search}%"),
    )
    return list(cursor.fetchall())


def set_post_hidden(cursor, post_id: int, hidden: bool) -> bool:
    cursor.execute(
        """
        UPDATE posts AS p SET post_status = %s, updated_at = CURRENT_TIMESTAMP
        WHERE p.post_id = %s AND p.post_type = 'BOARD' AND p.deleted_at IS NULL
          AND EXISTS (
              SELECT 1 FROM boards b WHERE b.board_id = p.board_id AND b.board_name <> '공지사항'
          )
        """,
        ('HIDDEN' if hidden else 'PUBLISHED', post_id),
    )
    return cursor.rowcount == 1


def list_members(cursor) -> list[dict]:
    cursor.execute(
        """
        SELECT member_id, nickname, role_code, created_at
        FROM members
        WHERE member_id > 0
        ORDER BY member_id DESC
        LIMIT 200
        """
    )
    return list(cursor.fetchall())
