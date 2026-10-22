"""게시판 SQL과 결과 매핑. 연결·권한·트랜잭션은 Service에서 관리한다."""

from typing import Any


def images_by_post(cursor, post_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """게시글 ID들을 한 번에 조회하여 표시 순서대로 이미지를 묶는다.

    이미지가 없는 게시글은 빈 목록이다. 빈 ID 목록은 SQL을 실행하지 않는다.
    내부 매핑용 post_id는 이미지 응답에 포함하지 않는다.
    """
    images = {post_id: [] for post_id in post_ids}
    if not post_ids:
        return images
    cursor.execute(
        """
        SELECT
            post_id,
            image_id AS id,
            '/uploads/' || stored_name AS url,
            original_name
        FROM post_images
        WHERE post_id = ANY(%s)
        ORDER BY post_id, display_order, image_id
        """,
        (post_ids,),
    )
    for image in cursor.fetchall():
        post_id = image.pop("post_id")
        images[post_id].append(image)
    return images


BOARD_POST_TYPE = "BOARD"


def _board_post_guard(alias: str = "p") -> str:
    """내부 SQL 별칭으로 삭제·모임 게시글 제외 조건을 구성한다."""
    return f"""
        {alias}.deleted_at IS NULL
        AND NOT EXISTS (
            SELECT 1
            FROM recruits AS r
            WHERE r.post_id = {alias}.post_id
        )
    """


def list_boards(cursor) -> list[dict[str, Any]]:
    """기본 게시판 우선·생성 시간·ID 순으로 게시판 응답 목록을 조회한다."""
    cursor.execute("""
        SELECT
            board_id AS id,
            board_name AS name,
            description,
            created_at
        FROM boards
        ORDER BY
            is_default DESC,
            created_at,
            board_id
        """)
    return list(cursor.fetchall())


def create_board(
    cursor,
    name: str,
    description: str | None,
    creation_reason: str | None,
    member_id: int,
) -> int:
    """게시판 입력값을 저장하고 생성 ID를 반환한다. 커밋은 호출자가 수행한다."""
    cursor.execute(
        """
        INSERT INTO boards (
            board_name, description, creation_reason, created_by
        )
        VALUES (%s, %s, %s, %s)
        RETURNING board_id
        """,
        (name, description or None, creation_reason or None, member_id),
    )
    board_id = cursor.fetchone()["board_id"]
    return board_id


def get_board(cursor, board_id: int) -> dict[str, Any] | None:
    """게시판 ID로 응답 필드를 조회한다. 없으면 None을 반환한다."""
    cursor.execute(
        """
        SELECT
            board_id AS id,
            board_name AS name,
            description,
            created_at
        FROM boards
        WHERE board_id = %s
        """,
        (board_id,),
    )
    row = cursor.fetchone()
    return row


def list_posts(
    cursor, board_id: int, search: str, member_id: int
) -> list[dict[str, Any]]:
    """검색 조건으로 게시글을 조회하고 이미지를 일괄 매핑한다. 정렬·댓글 집계를 보존한다."""
    params: list[Any] = [member_id, member_id, board_id]
    condition = ""
    if search:
        condition = " AND (p.title ILIKE %s OR p.body ILIKE %s)"
        params += [f"%{search}%", f"%{search}%"]
    cursor.execute(
        f"""
        SELECT
            p.post_id AS id,
            p.board_id,
            p.title,
            COALESCE(p.body, '') AS body,
            p.author_member_id AS author_id,
            COALESCE(NULLIF(m.nickname, ''), '익명') AS author_name,
            p.created_at,
            p.updated_at,
            COUNT(c.comment_id) FILTER (WHERE c.deleted_at IS NULL)::int AS comment_count,
            (p.author_member_id = %s) AS is_owner,
            (
                SELECT COUNT(*)
                FROM post_likes AS l
                WHERE l.post_id = p.post_id
            )::int AS like_count,
            EXISTS (
                SELECT 1
                FROM post_likes AS l
                WHERE l.post_id = p.post_id
                      AND l.member_id = %s
            ) AS liked_by_me
        FROM posts AS p
        JOIN members AS m ON m.member_id = p.author_member_id
        LEFT JOIN comments AS c ON c.post_id = p.post_id
        WHERE p.board_id = %s
            AND {_board_post_guard()}{condition}
        GROUP BY
            p.post_id,
            p.board_id,
            p.title,
            p.body,
            p.author_member_id,
            m.nickname,
            p.created_at,
            p.updated_at
        ORDER BY
            p.created_at DESC,
            p.post_id DESC
        """,
        params,
    )
    rows = list(cursor.fetchall())
    images = images_by_post(cursor, [row["id"] for row in rows])
    for row in rows:
        row["images"] = images[row["id"]]
    return rows


def create_post(
    cursor,
    board_id: int,
    title: str,
    body: str,
    member_id: int,
    images: list[dict[str, Any]] | None = None,
) -> int:
    """게시글과 이미지 메타데이터를 주어진 커서로 저장하고 게시글 ID를 반환한다."""
    cursor.execute(
        """
        INSERT INTO posts (
            board_id, author_member_id, post_type, title, body,
            source_type, post_status, published_at
        )
        VALUES (%s, %s, %s, %s, %s, 'USER', 'PUBLISHED', CURRENT_TIMESTAMP)
        RETURNING post_id
        """,
        (board_id, member_id, BOARD_POST_TYPE, title, body),
    )
    post_id = cursor.fetchone()["post_id"]
    for order, image in enumerate(images or []):
        cursor.execute(
            """
            INSERT INTO post_images (
                post_id, stored_name, original_name,
                content_type, file_size, display_order
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                post_id,
                image["stored_name"],
                image["original_name"],
                image["content_type"],
                image["file_size"],
                order,
            ),
        )
    return post_id


def get_post(
    cursor, board_id: int, post_id: int, member_id: int
) -> dict[str, Any] | None:
    """게시글과 댓글 수·이미지를 반환한다. 삭제·모임 게시글은 None이다."""
    cursor.execute(
        f"""
        SELECT
            p.post_id AS id,
            p.board_id,
            p.title,
            COALESCE(p.body, '') AS body,
            p.author_member_id AS author_id,
            COALESCE(NULLIF(m.nickname, ''), '익명') AS author_name,
            p.created_at,
            p.updated_at,
            (
                SELECT COUNT(*)
                FROM comments AS c
                WHERE c.post_id = p.post_id
                      AND c.deleted_at IS NULL
            ) AS comment_count,
            (p.author_member_id = %s) AS is_owner,
            (
                SELECT COUNT(*)
                FROM post_likes AS l
                WHERE l.post_id = p.post_id
            )::int AS like_count,
            EXISTS (
                SELECT 1
                FROM post_likes AS l
                WHERE l.post_id = p.post_id
                      AND l.member_id = %s
            ) AS liked_by_me,
            EXISTS (
                SELECT 1
                FROM post_scraps AS s
                WHERE s.post_id = p.post_id
                      AND s.member_id = %s
            ) AS scrapped_by_me
        FROM posts AS p
        JOIN members AS m ON m.member_id = p.author_member_id
        WHERE p.board_id = %s
            AND p.post_id = %s
            AND {_board_post_guard()}
        """,
        (member_id, member_id, member_id, board_id, post_id),
    )
    row = cursor.fetchone()
    if row is not None:
        row["images"] = images_by_post(cursor, [post_id])[post_id]
    return row


def update_post(
    cursor, board_id: int, post_id: int, title: str, body: str, member_id: int
) -> bool:
    """작성자·삭제·모임 조건으로 게시글을 수정하고 변경 여부를 반환한다."""
    cursor.execute(
        f"""
        UPDATE posts AS p
        SET title = %s,
            body = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE p.board_id = %s
            AND p.post_id = %s
            AND p.author_member_id = %s
            AND {_board_post_guard()}
        """,
        (title, body, board_id, post_id, member_id),
    )
    return cursor.rowcount > 0


def delete_post(cursor, board_id: int, post_id: int, member_id: int) -> bool:
    """작성자·삭제·모임 조건으로 게시글을 논리 삭제하고 변경 여부를 반환한다."""
    cursor.execute(
        f"""
        UPDATE posts AS p
        SET deleted_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE p.board_id = %s
            AND p.post_id = %s
            AND p.author_member_id = %s
            AND {_board_post_guard()}
        """,
        (board_id, post_id, member_id),
    )
    return cursor.rowcount > 0


def post_exists(cursor, board_id: int, post_id: int) -> bool:
    """게시판과 게시글 ID로 유효한 글 존재 여부만 조회한다."""
    cursor.execute(
        f"""
        SELECT
            1
        FROM posts AS p
        WHERE p.board_id = %s
            AND p.post_id = %s
            AND {_board_post_guard()}
        """,
        (board_id, post_id),
    )
    return cursor.fetchone() is not None


def like_post(cursor, post_id: int, member_id: int) -> None:
    """게시글 좋아요를 저장한다. 이미 좋아요한 글은 기본키 충돌을 무시한다."""
    cursor.execute(
        """
        INSERT INTO post_likes (post_id, member_id)
        VALUES (%s, %s)
        ON CONFLICT (post_id, member_id) DO NOTHING
        """,
        (post_id, member_id),
    )


def unlike_post(cursor, post_id: int, member_id: int) -> None:
    """회원의 게시글 좋아요를 삭제한다. 좋아요가 없으면 아무것도 변경하지 않는다."""
    cursor.execute(
        """
        DELETE FROM post_likes
        WHERE post_id = %s
            AND member_id = %s
        """,
        (post_id, member_id),
    )


def get_post_like(cursor, post_id: int, member_id: int) -> dict[str, Any]:
    """게시글 좋아요 수와 회원의 좋아요 여부를 응답 필드로 조회한다."""
    cursor.execute(
        """
        SELECT
            %s AS post_id,
            COUNT(*)::int AS like_count,
            COALESCE(BOOL_OR(l.member_id = %s), FALSE) AS liked_by_me
        FROM post_likes AS l
        WHERE l.post_id = %s
        """,
        (post_id, member_id, post_id),
    )
    row = cursor.fetchone()
    return row


def scrap_post(cursor, post_id: int, member_id: int) -> None:
    """게시글 스크랩을 저장한다. 이미 스크랩한 글은 기본키 충돌을 무시한다."""
    cursor.execute(
        """
        INSERT INTO post_scraps (post_id, member_id)
        VALUES (%s, %s)
        ON CONFLICT (post_id, member_id) DO NOTHING
        """,
        (post_id, member_id),
    )


def unscrap_post(cursor, post_id: int, member_id: int) -> None:
    """회원의 게시글 스크랩을 삭제한다. 스크랩이 없으면 아무것도 변경하지 않는다."""
    cursor.execute(
        """
        DELETE FROM post_scraps
        WHERE post_id = %s
            AND member_id = %s
        """,
        (post_id, member_id),
    )


def get_post_scrap(cursor, post_id: int, member_id: int) -> dict[str, Any]:
    """회원의 게시글 스크랩 여부를 응답 필드로 조회한다."""
    cursor.execute(
        """
        SELECT
            %s AS post_id,
            EXISTS (
                SELECT 1
                FROM post_scraps AS s
                WHERE s.post_id = %s
                      AND s.member_id = %s
            ) AS scrapped_by_me
        """,
        (post_id, post_id, member_id),
    )
    row = cursor.fetchone()
    return row


def list_comments(cursor, post_id: int, member_id: int) -> list[dict[str, Any]]:
    """삭제되지 않은 댓글을 작성 시간·ID 순서로 반환한다."""
    cursor.execute(
        """
        SELECT
            c.comment_id AS id,
            c.post_id,
            c.body,
            c.author_member_id AS author_id,
            COALESCE(NULLIF(m.nickname, ''), '익명') AS author_name,
            c.created_at,
            c.updated_at,
            (c.author_member_id = %s) AS is_owner
        FROM comments AS c
        JOIN members AS m ON m.member_id = c.author_member_id
        WHERE c.post_id = %s
            AND c.deleted_at IS NULL
        ORDER BY
            c.created_at,
            c.comment_id
        """,
        (member_id, post_id),
    )
    return list(cursor.fetchall())


def create_comment(cursor, post_id: int, body: str, member_id: int) -> int:
    """게시글 ID·작성자·본문으로 댓글을 저장하고 생성 ID를 반환한다."""
    cursor.execute(
        """
        INSERT INTO comments (post_id, author_member_id, body)
        VALUES (%s, %s, %s)
        RETURNING comment_id
        """,
        (post_id, member_id, body),
    )
    comment_id = cursor.fetchone()["comment_id"]
    return comment_id


def get_comment(cursor, comment_id: int, member_id: int) -> dict[str, Any] | None:
    """댓글 ID로 응답 필드를 조회한다. 없거나 삭제되었으면 None이다."""
    cursor.execute(
        """
        SELECT
            c.comment_id AS id,
            c.post_id,
            c.body,
            c.author_member_id AS author_id,
            COALESCE(NULLIF(m.nickname, ''), '익명') AS author_name,
            c.created_at,
            c.updated_at,
            (c.author_member_id = %s) AS is_owner
        FROM comments AS c
        JOIN members AS m ON m.member_id = c.author_member_id
        WHERE c.comment_id = %s
            AND c.deleted_at IS NULL
        """,
        (member_id, comment_id),
    )
    row = cursor.fetchone()
    return row


def update_comment(cursor, comment_id: int, body: str, member_id: int) -> bool:
    """댓글 ID·작성자 조건으로 본문을 수정하고 변경 여부를 반환한다."""
    cursor.execute(
        """
        UPDATE comments
        SET body = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE comment_id = %s
            AND author_member_id = %s
            AND deleted_at IS NULL
        """,
        (body, comment_id, member_id),
    )
    return cursor.rowcount > 0


def delete_comment(cursor, comment_id: int, member_id: int) -> bool:
    """댓글 ID·작성자 조건으로 논리 삭제하고 변경 여부를 반환한다."""
    cursor.execute(
        """
        UPDATE comments
        SET deleted_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE comment_id = %s
            AND author_member_id = %s
            AND deleted_at IS NULL
        """,
        (comment_id, member_id),
    )
    return cursor.rowcount > 0


def comment_exists(cursor, comment_id: int) -> bool:
    """삭제되지 않은 댓글 존재 여부를 반환하여 서비스의 403/404 판단을 돕는다."""
    cursor.execute(
        """
        SELECT
            1
        FROM comments
        WHERE comment_id = %s
            AND deleted_at IS NULL
        """,
        (comment_id,),
    )
    return cursor.fetchone() is not None
