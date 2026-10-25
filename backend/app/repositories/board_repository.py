"""게시판 SQL과 결과 매핑. 연결·권한·트랜잭션은 Service에서 관리한다."""

# Any : 게시글/댓글 조회 결과에 여러 데이터 타입이 들어올 수 있음을 나타냄
from typing import Any


# 게시글 여러 개에 첨부된 이미지를 한 번의 SQL 조회로 가져오는 함수
def images_by_post(cursor, post_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    """게시글 ID들을 한 번에 조회하여 표시 순서대로 이미지를 묶는다.

    이미지가 없는 게시글은 빈 목록이다. 빈 ID 목록은 SQL을 실행하지 않는다.
    내부 매핑용 post_id는 이미지 응답에 포함하지 않는다.
    """
    # 게시글별 이미지 목록을 저장할 딕셔너리 생성
    # 이미지가 없어도 해당 post_id의 값은 빈 리스트([])로 유지함
    images = {post_id: [] for post_id in post_ids}
    # 조회할 게시글이 없으면 DB에 쿼리하지 않고 바로 반환함
    if not post_ids:
        return images
    # ANY(%s) : 전달한 게시글 ID 목록 중 하나라도 일치하는 이미지를 조회함
    # ORDER BY : 게시글별로 이미지 표시 순서를 유지함
    # AS : DB 컬럼 이름을 프론트엔드 응답용 키(id, url)로 변경함
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
    # fetchall() : 쿼리 결과 전체 조회
    # pop("post_id") : 내부 매핑에만 쓰는 ID를 이미지 응답에서 제거함
    for image in cursor.fetchall():
        post_id = image.pop("post_id")
        images[post_id].append(image)
    return images


# 일반 게시판 글을 구분하는 고정된 post_type 값
BOARD_POST_TYPE = "BOARD"


# 삭제된 게시글과 모임 모집에 연결된 게시글을 제외하기 위한 공통 조건
def _board_post_guard(alias: str = "p") -> str:
    """내부 SQL 별칭으로 삭제·모임 게시글 제외 조건을 구성한다."""
    # deleted_at IS NULL : 삭제 처리되지 않은 글만 허용함
    # NOT EXISTS : recruits 테이블에 연결된 모임 게시글을 제외함
    # alias : 게시글 테이블의 SQL 별칭(p 등), 내부 코드에서만 전달함
    return f"""
        {alias}.deleted_at IS NULL
        AND NOT EXISTS (
            SELECT 1
            FROM recruits AS r
            WHERE r.post_id = {alias}.post_id
        )
    """


# 전체 게시판 목록 조회
def list_boards(cursor) -> list[dict[str, Any]]:
    """기본 게시판 우선·생성 시간·ID 순으로 게시판 응답 목록을 조회한다."""
    # is_default가 True인 기본 게시판을 먼저 표시하고 이후 생성 시간순 정렬함
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


# 새 게시판을 등록하고 생성된 게시판 ID를 반환함
def create_board(
    cursor,
    name: str,
    description: str | None,
    creation_reason: str | None,
    member_id: int,
) -> int:
    """게시판 입력값을 저장하고 생성 ID를 반환한다. 커밋은 호출자가 수행한다."""
    # INSERT : 게시판 이름, 설명, 생성 이유, 생성자 회원 ID 저장
    # %s : SQL에 전달할 값을 안전하게 바인딩하는 자리표시자
    # RETURNING : 새로 저장된 board_id를 바로 반환받음
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
    # fetchone() : RETURNING으로 반환된 게시판 ID 한 건을 조회함
    board_id = cursor.fetchone()["board_id"]
    return board_id


# 게시판 번호로 특정 게시판의 기본 정보를 조회함
def get_board(cursor, board_id: int) -> dict[str, Any] | None:
    """게시판 ID로 응답 필드를 조회한다. 없으면 None을 반환한다."""
    # WHERE board_id = %s : 요청한 게시판 번호와 일치하는 한 건만 조회함
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
    # 해당 게시판이 없으면 fetchone() 결과는 None임
    row = cursor.fetchone()
    return row


# 특정 게시판의 게시글 목록과 댓글 수, 첨부 이미지를 조회함
def list_posts(
    cursor, board_id: int, search: str, member_id: int
) -> list[dict[str, Any]]:
    """검색 조건으로 게시글을 조회하고 이미지를 일괄 매핑한다. 정렬·댓글 집계를 보존한다."""
    # SQL에서 사용하는 %s 자리표시자 순서대로 조회 인자를 준비함
    # member_id는 본인 작성 여부(is_owner)와 좋아요 여부(liked_by_me), board_id는 게시판 필터에 사용함
    params: list[Any] = [member_id, member_id, board_id]
    condition = ""
    # 검색어가 있을 때만 제목·본문 검색 조건을 추가함
    # ILIKE : PostgreSQL에서 대소문자 구분 없이 문자열 검색
    # %검색어% : 검색어가 포함된 글을 찾는 패턴
    if search:
        condition = " AND (p.title ILIKE %s OR p.body ILIKE %s)"
        params += [f"%{search}%", f"%{search}%"]
    # JOIN members : 작성자의 닉네임 조회
    # LEFT JOIN comments : 댓글이 없어도 게시글은 목록에 포함
    # COUNT ... FILTER : 삭제되지 않은 댓글만 집계
    # COALESCE/NULLIF : 닉네임이 없거나 빈 문자열이면 "익명" 사용
    # GROUP BY : 게시글별 댓글 수를 계산하기 위한 그룹화
    # 최신 게시글부터 조회하고 모임 모집글/삭제된 글은 제외함
    # 서브쿼리 COUNT(*) : 삭제되지 않은 댓글 개수를 계산함
    # (작성자 ID = 요청자 ID) : 글 수정/삭제 UI에 활용할 is_owner 값
    # _board_post_guard() : 삭제된 글과 모임 모집글은 조회 대상에서 제외함
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
    # 게시글 전체 조회 후, N번 조회하지 않도록 이미지 목록을 일괄 조회함
    rows = list(cursor.fetchall())
    images = images_by_post(cursor, [row["id"] for row in rows])
    # 게시글 한 건마다 해당 이미지 목록(images)을 붙여 반환함
    for row in rows:
        row["images"] = images[row["id"]]
    return rows


# 게시글을 생성하고 필요하면 첨부 이미지 메타데이터도 저장함
def create_post(
    cursor,
    board_id: int,
    title: str,
    body: str,
    member_id: int,
    images: list[dict[str, Any]] | None = None,
) -> int:
    """게시글과 이미지 메타데이터를 주어진 커서로 저장하고 게시글 ID를 반환한다."""
    # 게시글 작성자, 제목, 본문을 저장함
    # post_type=BOARD / source_type=USER / post_status=PUBLISHED로 저장함
    # CURRENT_TIMESTAMP : 게시글 공개 시간을 DB 현재 시간으로 기록함
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
    # INSERT 결과로 생성된 게시글 번호를 가져옴
    post_id = cursor.fetchone()["post_id"]
    # 이미지는 파일 자체가 아닌 저장 이름·파일 크기 등의 정보를 DB에 기록함
    # enumerate() : 첨부 순서(display_order)를 0부터 지정함
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


# 단일 게시글의 내용, 작성자, 댓글 수, 첨부 이미지를 조회함
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
    # 조회한 글이 있을 때만 이미지 정보를 함께 추가함
    row = cursor.fetchone()
    if row is not None:
        row["images"] = images_by_post(cursor, [post_id])[post_id]
    return row


# 게시글 작성자만 제목과 본문을 수정할 수 있도록 제한함
def update_post(
    cursor, board_id: int, post_id: int, title: str, body: str, member_id: int
) -> bool:
    """작성자·삭제·모임 조건으로 게시글을 수정하고 변경 여부를 반환한다."""
    # UPDATE : 제목, 본문, 마지막 수정 시간을 변경함
    # WHERE : 같은 게시판의 글 + 작성자 본인 + 미삭제 + 비모임 게시글
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
    # rowcount : 실제 변경된 행 수, 한 건 이상이면 수정 성공(True)
    return cursor.rowcount > 0


# 게시글을 물리적으로 지우지 않고 삭제 일시를 기록함
def delete_post(cursor, board_id: int, post_id: int, member_id: int) -> bool:
    """작성자·삭제·모임 조건으로 게시글을 논리 삭제하고 변경 여부를 반환한다."""
    # 논리 삭제(Soft Delete) : deleted_at에 시간만 기록하여 데이터 보존
    # 작성자 본인 글이고 아직 삭제되지 않았으며 모임 글이 아닐 때만 처리함
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
    # 처리한 글이 있으면 True, 없으면 False 반환
    return cursor.rowcount > 0


# 게시글 존재 여부만 확인하여 불필요한 데이터 조회를 줄임
def post_exists(cursor, board_id: int, post_id: int) -> bool:
    """게시판과 게시글 ID로 유효한 글 존재 여부만 조회한다."""
    # SELECT 1 : 데이터 내용은 가져오지 않고 존재 여부만 확인함
    # 삭제·모임 제외 조건은 게시글 상세 조회와 동일하게 적용함
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


# 게시글 좋아요 저장 (중복 요청은 무시)
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


# 게시글 좋아요 취소
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


# 좋아요 등록·취소 후 응답할 좋아요 수와 내 좋아요 여부 조회
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


# 게시글 스크랩 저장 (중복 요청은 무시)
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


# 게시글 스크랩 취소
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


# 스크랩 등록·취소 후 응답할 내 스크랩 여부 조회
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


# 게시글에 달린 댓글 목록을 부모 → 대댓글 순서로 조회함
def list_comments(cursor, post_id: int, member_id: int) -> list[dict[str, Any]]:
    """삭제되지 않은 댓글을 부모 댓글 작성 순서로, 대댓글은 부모 바로 뒤에 반환한다.

    삭제된 최상위 댓글은 살아 있는 대댓글이 있을 때만 본문·작성자를 비운
    삭제 표시 행으로 포함한다.
    """
    # JOIN members : 작성자의 닉네임과 작성자 ID를 함께 조회함
    # is_owner : 로그인한 회원이 해당 댓글 작성자인지 비교함 (삭제 표시 행은 False)
    # 삭제된 댓글은 제외하되, 살아 있는 대댓글이 있는 삭제된 부모는 자리표시로 포함함
    cursor.execute(
        """

        SELECT
            c.comment_id AS id,
            c.post_id,
            c.parent_comment_id,
            CASE WHEN c.deleted_at IS NULL THEN c.body ELSE '' END AS body,
            CASE WHEN c.deleted_at IS NULL THEN c.author_member_id END AS author_id,
            CASE
                WHEN c.deleted_at IS NULL
                THEN COALESCE(NULLIF(m.nickname, ''), '익명')
                ELSE ''
            END AS author_name,
            c.created_at,
            c.updated_at,
            (c.deleted_at IS NULL AND c.author_member_id = %s) AS is_owner,
            (c.deleted_at IS NOT NULL) AS is_deleted
        FROM comments AS c
        JOIN members AS m ON m.member_id = c.author_member_id
        LEFT JOIN comments AS parent ON parent.comment_id = c.parent_comment_id
        WHERE c.post_id = %s
            AND (
                c.deleted_at IS NULL
                OR (
                    c.parent_comment_id IS NULL
                    AND EXISTS (
                        SELECT 1
                        FROM comments AS r
                        WHERE r.parent_comment_id = c.comment_id
                              AND r.deleted_at IS NULL
                    )
                )
            )
        ORDER BY
            COALESCE(parent.created_at, c.created_at),
            COALESCE(parent.comment_id, c.comment_id),
            c.parent_comment_id IS NOT NULL,
            c.created_at,
            c.comment_id
        """,
        (member_id, post_id),
    )
    return list(cursor.fetchall())


# 댓글 및 대댓글 저장
def create_comment(
    cursor,
    post_id: int,
    body: str,
    member_id: int,
    parent_comment_id: int | None = None,
) -> int:
    """게시글 ID·작성자·본문·부모 댓글 ID로 댓글을 저장하고 생성 ID를 반환한다."""
    cursor.execute(
        """
        INSERT INTO comments (post_id, author_member_id, body, parent_comment_id)
        VALUES (%s, %s, %s, %s)
        RETURNING comment_id
        """,
        (post_id, member_id, body, parent_comment_id),
    )

    return cursor.fetchone()["comment_id"]


# 대댓글 작성 전 부모 댓글의 게시글·상위 댓글 ID 조회
def get_parent_comment(cursor, comment_id: int) -> dict[str, Any] | None:
    """대댓글 검증에 필요한 부모 댓글의 게시글·상위 댓글 ID를 조회한다.

    없거나 삭제된 댓글은 None이다.
    """
    cursor.execute(
        """
        SELECT
            post_id,
            parent_comment_id
        FROM comments
        WHERE comment_id = %s
            AND deleted_at IS NULL
        """,
        (comment_id,),
    )
    row = cursor.fetchone()
    return row


# 댓글 ID에 해당하는 댓글 한 건을 조회함
def get_comment(cursor, comment_id: int, member_id: int) -> dict[str, Any] | None:
    """댓글 ID로 응답 필드를 조회한다. 없거나 삭제되었으면 None이다."""
    cursor.execute(
        """
        SELECT
            c.comment_id AS id,
            c.post_id,
            c.parent_comment_id,
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


# 댓글 작성자만 본문을 수정할 수 있도록 처리함
def update_comment(cursor, comment_id: int, body: str, member_id: int) -> bool:
    """댓글 ID·작성자 조건으로 본문을 수정하고 변경 여부를 반환한다."""
    # UPDATE : 댓글 내용과 마지막 수정 시간 갱신
    # WHERE : 댓글 번호와 작성자가 일치하며 아직 삭제되지 않은 댓글만 허용
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


# 댓글 내용을 즉시 삭제하지 않고 삭제 시간을 기록함
def delete_comment(cursor, comment_id: int, member_id: int) -> bool:
    """댓글 ID·작성자 조건으로 논리 삭제하고 변경 여부를 반환한다."""
    # 논리 삭제 : deleted_at을 기록하여 댓글을 목록/상세에서 제외함
    # 다른 회원의 댓글이나 이미 삭제된 댓글은 변경하지 않음
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


# 댓글이 존재하고 삭제되지 않았는지 빠르게 확인함
def comment_exists(cursor, comment_id: int) -> bool:
    """삭제되지 않은 댓글 존재 여부를 반환하여 서비스의 403/404 판단을 돕는다."""
    # SELECT 1 : 행의 전체 데이터를 읽지 않고 존재 여부만 확인함
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
