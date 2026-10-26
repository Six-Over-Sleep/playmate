"""PLAYMATE 취업 후기 DB 조회·저장 함수.

트랜잭션은 career_service.py의 db_cursor(commit=True)가 담당한다.
이 파일에서는 commit/rollback하지 않는다.
"""

from app.repositories import board_repository

def create_review(cursor, member_id: int, data: dict) -> int:
    """posts → career_posts → career_reviews 순서로 후기 저장 후 ID 반환."""
    cursor.execute(
        """
        INSERT INTO posts (
            board_id, author_member_id, post_type, title, body,
            source_type, post_status, published_at
        )
        VALUES (NULL, %s, 'CAREER', %s, %s, 'USER', 'PUBLISHED', CURRENT_TIMESTAMP)
        RETURNING post_id
        """,
        (member_id, data["title"], data["body"]),
    )
    post_id = cursor.fetchone()["post_id"]

    cursor.execute(
        """
        INSERT INTO career_posts (
            post_id, category_code, subcategory_code, is_anonymous
        )
        VALUES (%s, 'reviews', %s, %s)
        """,
        (post_id, data["subcategory_code"], data.get("is_anonymous", True)),
    )

    cursor.execute(
        """
        INSERT INTO career_reviews (
            post_id, company_name, is_company_private,
            job_category_code, application_type,
            process_stage, process_result, process_date, interview_format
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            post_id,
            data.get("company_name"),
            data.get("is_company_private", False),
            data["job_category_code"],
            data.get("application_type"),
            data["process_stage"],
            data["process_result"],
            data.get("process_date"),
            data.get("interview_format"),
        ),
    )

    return post_id


def get_review(cursor, post_id: int, member_id: int) -> dict | None:
    """삭제되지 않은 후기 상세를 조회한다. 익명·비공개 기업명 설정을 반영한다."""
    cursor.execute(
        """
        SELECT
            p.post_id AS id,
            p.title,
            p.body,
            p.created_at,
            p.updated_at,
            (p.author_member_id = %s) AS is_owner,
            CASE
                WHEN cp.is_anonymous THEN '익명'
                ELSE COALESCE(NULLIF(m.nickname, ''), '익명')
            END AS author_name,
            cp.category_code,
            cp.subcategory_code,
            cp.is_anonymous,
            CASE
                WHEN cr.is_company_private AND p.author_member_id <> %s THEN NULL
                ELSE cr.company_name
            END AS company_name,
            cr.is_company_private,
            cr.job_category_code,
            cr.application_type,
            cr.process_stage,
            cr.process_result,
            cr.process_date,
            cr.interview_format
        FROM posts AS p
        JOIN members AS m ON m.member_id = p.author_member_id
        JOIN career_posts AS cp ON cp.post_id = p.post_id
        JOIN career_reviews AS cr ON cr.post_id = p.post_id
        WHERE p.post_id = %s
          AND p.post_type = 'CAREER'
          AND cp.category_code = 'reviews'
          AND p.deleted_at IS NULL
        """,
        (member_id, member_id, post_id),
    )
    return attach_post_reactions(cursor, cursor.fetchone(), member_id)

def list_reviews(
    cursor,
    member_id: int,
    q: str | None = None,
    subcategory_code: str | None = None,
    job_category_code: str | None = None,
    process_stage: str | None = None,
    process_result: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict:
    """취준 도감 후기 목록을 검색하고 페이지 단위로 조회한다."""

    conditions = [
        "p.post_type = 'CAREER'",
        "p.deleted_at IS NULL",
        "cp.category_code = 'reviews'",
    ]

    params = []

    # 하위 카테고리 필터
    if subcategory_code:
        conditions.append("cp.subcategory_code = %s")
        params.append(subcategory_code)

    # 직무 필터
    if job_category_code:
        conditions.append("cr.job_category_code = %s")
        params.append(job_category_code)

    # 전형 단계 필터
    if process_stage:
        conditions.append("cr.process_stage = %s")
        params.append(process_stage)

    # 전형 결과 필터
    if process_result:
        conditions.append("cr.process_result = %s")
        params.append(process_result)

    # 검색: 비공개 기업명은 작성자만 검색 가능
    if q and q.strip():
        keyword = f"%{q.strip()}%"

        conditions.append(
            """
            (
                p.title ILIKE %s
                OR p.body ILIKE %s
                OR (
                    (cr.is_company_private = FALSE
                     OR p.author_member_id = %s)
                    AND cr.company_name ILIKE %s
                )
            )
            """
        )

        params.extend([
            keyword,
            keyword,
            member_id,
            keyword,
        ])

    where_sql = " AND ".join(conditions)

    from_sql = """
        FROM posts AS p
        JOIN career_posts AS cp
            ON cp.post_id = p.post_id
        JOIN career_reviews AS cr
            ON cr.post_id = p.post_id
        JOIN members AS m
            ON m.member_id = p.author_member_id
    """

    # 1. 검색 조건에 해당하는 전체 게시글 수
    cursor.execute(
        f"""
        SELECT COUNT(*) AS total
        {from_sql}
        WHERE {where_sql}
        """,
        params,
    )

    total = cursor.fetchone()["total"]

    # 2. 페이지네이션
    offset = (page - 1) * page_size

    # 3. 목록 조회
    cursor.execute(
        f"""
        SELECT
            p.post_id AS id,
            p.title,
            LEFT(COALESCE(p.body, ''), 150) AS body_preview,
            p.created_at,

            (p.author_member_id = %s) AS is_owner,

            CASE
                WHEN cp.is_anonymous THEN '익명'
                ELSE COALESCE(NULLIF(m.nickname, ''), '익명')
            END AS author_name,

            cp.subcategory_code,

            CASE
                WHEN cr.is_company_private
                     AND p.author_member_id <> %s
                THEN NULL
                ELSE cr.company_name
            END AS company_name,

            cr.job_category_code,
            cr.process_stage,
            cr.process_result

        {from_sql}
        WHERE {where_sql}

        ORDER BY
            p.created_at DESC NULLS LAST,
            p.post_id DESC

        LIMIT %s OFFSET %s
        """,
        [member_id, member_id, *params, page_size, offset],
    )

    items = list(cursor.fetchall())

    return {
        "items": attach_list_reactions(cursor, items),
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# =========================================
# 취준 도감 - 수정 권한 확인
# =========================================

def get_review_author_for_update(cursor, post_id: int) -> int | None:
    """후기를 잠그고 실제 작성자 ID를 조회한다."""

    cursor.execute(
        """
        SELECT p.author_member_id
        FROM posts AS p
        JOIN career_posts AS cp
            ON cp.post_id = p.post_id
        JOIN career_reviews AS cr
            ON cr.post_id = p.post_id
        WHERE p.post_id = %s
            AND p.post_type = 'CAREER'
            AND cp.category_code = 'reviews'
            AND p.deleted_at IS NULL
        FOR UPDATE OF p
        """,
        (post_id,),
    )

    row = cursor.fetchone()

    if row is None:
        return None

    return row["author_member_id"]


# =========================================
# 취준 도감 - 후기 수정
# =========================================

def update_review(cursor, post_id: int, changes: dict) -> None:
    """변경된 필드만 각 테이블에 반영한다.

    호출한 Service에서 작성자 권한을 먼저 검증해야 한다.
    테이블명과 컬럼명은 아래 고정 목록에서만 사용한다.
    """

    table_columns = {
        "posts": (
            "title",
            "body",
        ),
        "career_posts": (
            "subcategory_code",
            "is_anonymous",
        ),
        "career_reviews": (
            "company_name",
            "is_company_private",
            "job_category_code",
            "application_type",
            "process_stage",
            "process_result",
            "process_date",
            "interview_format",
        ),
    }

    # 변경된 컬럼만 UPDATE
    for table_name, allowed_columns in table_columns.items():

        columns = [
            column
            for column in allowed_columns
            if column in changes
        ]

        if not columns:
            continue

        assignments = [
            f"{column} = %s"
            for column in columns
        ]

        values = [
            changes[column]
            for column in columns
        ]

        # posts 수정 시 수정일 갱신
        if table_name == "posts":
            assignments.append("updated_at = CURRENT_TIMESTAMP")

        sql = f"""
            UPDATE {table_name}
            SET {", ".join(assignments)}
            WHERE post_id = %s
        """

        cursor.execute(sql, (*values, post_id))

    # 후기 상세 정보만 수정했더라도 게시글 수정일 갱신
    if "title" not in changes and "body" not in changes:
        cursor.execute(
            """
            UPDATE posts
            SET updated_at = CURRENT_TIMESTAMP
            WHERE post_id = %s
            """,
            (post_id,),
        )


# =========================================
# 취준 도감 - 후기 논리 삭제
# =========================================

def delete_review(cursor, post_id: int, member_id: int) -> bool:
    """작성자 본인의 취업 후기를 논리 삭제한다."""

    cursor.execute(
        """
        UPDATE posts
        SET
            deleted_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE post_id = %s
            AND author_member_id = %s
            AND post_type = 'CAREER'
            AND deleted_at IS NULL
        """,
        (post_id, member_id),
    )

    return cursor.rowcount > 0



# =========================================
# 커리어 톡톡 - 게시글 등록
# =========================================

def create_talk(cursor, member_id: int, data: dict) -> int:
    """게시글과 커리어 톡톡 상세 정보를 저장한다."""

    # 1. 공통 게시글 저장
    cursor.execute(
        """
        INSERT INTO posts (
            board_id,
            author_member_id,
            post_type,
            title,
            body,
            source_type,
            post_status,
            published_at
        )
        VALUES (
            NULL, %s, 'CAREER', %s, %s,
            'USER', 'PUBLISHED', CURRENT_TIMESTAMP
        )
        RETURNING post_id
        """,
        (
            member_id,
            data["title"],
            data["body"],
        ),
    )

    post_id = cursor.fetchone()["post_id"]

    # 2. 취업 게시판 공통 분류 저장
    cursor.execute(
        """
        INSERT INTO career_posts (
            post_id,
            category_code,
            subcategory_code,
            is_anonymous
        )
        VALUES (%s, 'talk', %s, %s)
        """,
        (
            post_id,
            data["subcategory_code"],
            data.get("is_anonymous", True),
        ),
    )

    # 3. 커리어 톡톡 추가 정보 저장
    cursor.execute(
        """
        INSERT INTO career_talks (
            post_id,
            job_category_code,
            current_status
        )
        VALUES (%s, %s, %s)
        """,
        (
            post_id,
            data.get("job_category_code"),
            data.get("current_status"),
        ),
    )

    return post_id


# =========================================
# 커리어 톡톡 - 게시글 상세 조회
# =========================================

def get_talk(cursor, post_id: int, member_id: int) -> dict | None:
    """삭제되지 않은 커리어 톡톡 게시글을 조회한다."""

    cursor.execute(
        """
        SELECT
            p.post_id AS id,
            p.title,
            p.body,
            p.created_at,
            p.updated_at,

            (p.author_member_id = %s) AS is_owner,

            CASE
                WHEN cp.is_anonymous THEN '익명'
                ELSE COALESCE(NULLIF(m.nickname, ''), '익명')
            END AS author_name,

            cp.category_code,
            cp.subcategory_code,
            cp.is_anonymous,

            ct.job_category_code,
            ct.current_status

        FROM posts AS p

        JOIN members AS m
            ON m.member_id = p.author_member_id

        JOIN career_posts AS cp
            ON cp.post_id = p.post_id

        JOIN career_talks AS ct
            ON ct.post_id = p.post_id

        WHERE p.post_id = %s
            AND p.post_type = 'CAREER'
            AND cp.category_code = 'talk'
            AND p.deleted_at IS NULL
        """,
        (member_id, post_id),
    )

    return attach_post_reactions(cursor, cursor.fetchone(), member_id)


# =========================================
# 커리어 톡톡 - 게시글 목록 조회
# =========================================

def list_talks(
    cursor,
    member_id: int,
    q: str | None = None,
    subcategory_code: str | None = None,
    job_category_code: str | None = None,
    current_status: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict:
    """검색 조건과 페이지네이션을 적용해 게시글 목록을 반환한다."""

    conditions = [
        "p.post_type = 'CAREER'",
        "p.deleted_at IS NULL",
        "cp.category_code = 'talk'",
    ]

    params = []

    # 1. 하위 카테고리 필터
    if subcategory_code:
        conditions.append("cp.subcategory_code = %s")
        params.append(subcategory_code)

    # 2. 직무 필터
    if job_category_code:
        conditions.append("ct.job_category_code = %s")
        params.append(job_category_code)

    # 3. 취업 상태 필터
    if current_status:
        conditions.append("ct.current_status = %s")
        params.append(current_status)

    # 4. 제목 및 본문 검색
    if q and q.strip():
        keyword = f"%{q.strip()}%"

        conditions.append(
            "(p.title ILIKE %s OR p.body ILIKE %s)"
        )

        params.extend([keyword, keyword])

    where_sql = " AND ".join(conditions)

    from_sql = """
        FROM posts AS p

        JOIN members AS m
            ON m.member_id = p.author_member_id

        JOIN career_posts AS cp
            ON cp.post_id = p.post_id

        JOIN career_talks AS ct
            ON ct.post_id = p.post_id
    """

    # 5. 전체 게시글 수 확인
    cursor.execute(
        f"""
        SELECT COUNT(*) AS total
        {from_sql}
        WHERE {where_sql}
        """,
        params,
    )

    total = cursor.fetchone()["total"]

    # 6. 페이지 계산
    offset = (page - 1) * page_size

    # 7. 게시글 목록 조회
    cursor.execute(
        f"""
        SELECT
            p.post_id AS id,
            p.title,
            LEFT(COALESCE(p.body, ''), 150) AS body_preview,
            p.created_at,

            (p.author_member_id = %s) AS is_owner,

            CASE
                WHEN cp.is_anonymous THEN '익명'
                ELSE COALESCE(NULLIF(m.nickname, ''), '익명')
            END AS author_name,

            cp.subcategory_code,
            cp.is_anonymous,

            ct.job_category_code,
            ct.current_status

        {from_sql}

        WHERE {where_sql}

        ORDER BY
            p.created_at DESC NULLS LAST,
            p.post_id DESC

        LIMIT %s OFFSET %s
        """,
        [
            member_id,
            *params,
            page_size,
            offset,
        ],
    )

    return {
        "items": attach_list_reactions(cursor, list(cursor.fetchall())),
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# =========================================
# 커리어 톡톡 - 수정 및 삭제 권한 확인
# =========================================

def get_talk_author_for_update(
    cursor,
    post_id: int,
) -> int | None:
    """게시글 행을 잠그고 작성자 ID를 조회한다."""

    cursor.execute(
        """
        SELECT
            p.author_member_id

        FROM posts AS p

        JOIN career_posts AS cp
            ON cp.post_id = p.post_id

        JOIN career_talks AS ct
            ON ct.post_id = p.post_id

        WHERE p.post_id = %s
            AND p.post_type = 'CAREER'
            AND cp.category_code = 'talk'
            AND p.deleted_at IS NULL

        FOR UPDATE OF p
        """,
        (post_id,),
    )

    row = cursor.fetchone()

    if row is None:
        return None

    return row["author_member_id"]


# =========================================
# 커리어 톡톡 - 게시글 수정
# =========================================

def update_talk(
    cursor,
    post_id: int,
    changes: dict,
) -> None:
    """전달된 필드만 수정한다.

    Service에서 작성자 권한을 먼저 검사한 후 호출한다.
    """

    # 테이블별 수정 가능한 컬럼만 허용
    table_columns = {
        "posts": (
            "title",
            "body",
        ),
        "career_posts": (
            "subcategory_code",
            "is_anonymous",
        ),
        "career_talks": (
            "job_category_code",
            "current_status",
        ),
    }

    # 변경된 필드를 각 테이블에 반영
    for table_name, allowed_columns in table_columns.items():

        columns = [
            column
            for column in allowed_columns
            if column in changes
        ]

        if not columns:
            continue

        assignments = [
            f"{column} = %s"
            for column in columns
        ]

        values = [
            changes[column]
            for column in columns
        ]

        if table_name == "posts":
            assignments.append(
                "updated_at = CURRENT_TIMESTAMP"
            )

        sql = f"""
            UPDATE {table_name}
            SET {", ".join(assignments)}
            WHERE post_id = %s
        """

        cursor.execute(
            sql,
            (*values, post_id),
        )

    # 게시글의 수정일은 모든 변경에 대해 갱신
    if "title" not in changes and "body" not in changes:
        cursor.execute(
            """
            UPDATE posts
            SET updated_at = CURRENT_TIMESTAMP
            WHERE post_id = %s
            """,
            (post_id,),
        )


# =========================================
# 커리어 톡톡 - 게시글 논리 삭제
# =========================================

def delete_talk(
    cursor,
    post_id: int,
    member_id: int,
) -> bool:
    """작성자 본인의 게시글을 논리 삭제한다."""

    cursor.execute(
        """
        UPDATE posts AS p

        SET
            deleted_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP

        WHERE p.post_id = %s
            AND p.author_member_id = %s
            AND p.post_type = 'CAREER'
            AND p.deleted_at IS NULL
            AND EXISTS (
                SELECT 1
                FROM career_posts AS cp
                JOIN career_talks AS ct
                    ON ct.post_id = cp.post_id
                WHERE cp.post_id = p.post_id
                    AND cp.category_code = 'talk'
            )
        """,
        (post_id, member_id),
    )

    return cursor.rowcount > 0



# =========================================================
# 커리어 톡톡 - 첨부파일 Repository
# =========================================================


# =========================================================
# 1. 첨부파일 목록 조회
# =========================================================

def list_talk_attachments(cursor, post_id: int) -> list:
    """게시글에 첨부된 파일 목록을 조회한다."""

    cursor.execute(
        """
        SELECT
            a.attachment_id,
            a.post_id,
            a.original_filename,
            a.attachment_type,
            a.content_type,
            a.file_size_bytes,
            a.display_order,
            a.created_at

        FROM career_talk_attachments AS a

        JOIN career_talks AS ct
            ON ct.post_id = a.post_id

        JOIN career_posts AS cp
            ON cp.post_id = ct.post_id

        JOIN posts AS p
            ON p.post_id = cp.post_id

        WHERE a.post_id = %s
            AND cp.category_code = 'talk'
            AND p.deleted_at IS NULL

        ORDER BY a.display_order ASC
        """,
        (post_id,),
    )

    return list(cursor.fetchall())


# =========================================================
# 2. 다음 첨부 순서 조회
# =========================================================

def get_next_talk_attachment_order(
    cursor,
    post_id: int,
) -> int | None:
    """사용 가능한 첨부 순서(1~5)를 반환한다.

    첨부파일이 이미 5개라면 None을 반환한다.

    동시 업로드 충돌을 막기 위해 Service에서
    게시글 행을 FOR UPDATE로 잠근 뒤 호출해야 한다.
    """

    cursor.execute(
        """
        SELECT slot.display_order

        FROM generate_series(1, 5)
            AS slot(display_order)

        WHERE NOT EXISTS (
            SELECT 1
            FROM career_talk_attachments AS a
            WHERE a.post_id = %s
                AND a.display_order = slot.display_order
        )

        ORDER BY slot.display_order

        LIMIT 1
        """,
        (post_id,),
    )

    row = cursor.fetchone()

    if row is None:
        return None

    return row["display_order"]


# =========================================================
# 3. 첨부파일 정보 등록
# =========================================================

def create_talk_attachment(
    cursor,
    post_id: int,
    original_filename: str,
    stored_path: str,
    attachment_type: str,
    content_type: str,
    file_size_bytes: int,
    display_order: int,
) -> dict:
    """서버에 저장된 파일의 메타데이터를 DB에 등록한다."""

    cursor.execute(
        """
        INSERT INTO career_talk_attachments (
            post_id,
            original_filename,
            stored_path,
            attachment_type,
            content_type,
            file_size_bytes,
            display_order
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s
        )

        RETURNING
            attachment_id,
            post_id,
            original_filename,
            attachment_type,
            content_type,
            file_size_bytes,
            display_order,
            created_at
        """,
        (
            post_id,
            original_filename,
            stored_path,
            attachment_type,
            content_type,
            file_size_bytes,
            display_order,
        ),
    )

    return cursor.fetchone()


# =========================================================
# 4. 첨부파일 단건 조회
# =========================================================

def get_talk_attachment(
    cursor,
    post_id: int,
    attachment_id: int,
) -> dict | None:
    """파일 ID로 메타데이터와 실제 저장 경로를 조회한다."""

    cursor.execute(
        """
        SELECT
            a.attachment_id,
            a.post_id,
            a.original_filename,
            a.stored_path,
            a.attachment_type,
            a.content_type,
            a.file_size_bytes,
            a.display_order,
            a.created_at

        FROM career_talk_attachments AS a

        JOIN career_talks AS ct
            ON ct.post_id = a.post_id

        JOIN career_posts AS cp
            ON cp.post_id = ct.post_id

        JOIN posts AS p
            ON p.post_id = cp.post_id

        WHERE a.attachment_id = %s
            AND a.post_id = %s
            AND cp.category_code = 'talk'
            AND p.deleted_at IS NULL
        """,
        (attachment_id, post_id),
    )

    return cursor.fetchone()


# =========================================================
# 5. 첨부파일 정보 삭제
# =========================================================

def delete_talk_attachment(
    cursor,
    post_id: int,
    attachment_id: int,
) -> dict | None:
    """첨부파일 메타데이터를 DB에서 삭제한다.

    실제 파일 삭제는 Service에서 처리한다.
    반드시 작성자 권한을 먼저 확인해야 한다.
    """

    cursor.execute(
        """
        DELETE FROM career_talk_attachments

        WHERE attachment_id = %s
            AND post_id = %s

        RETURNING
            attachment_id,
            post_id,
            original_filename,
            stored_path
        """,
        (attachment_id, post_id),
    )

    return cursor.fetchone()



# =========================================================
# 현직자 라운지 Repository
# =========================================================


# =========================================================
# 1. 현직자 라운지 게시글 등록
# =========================================================

def create_lounge(
    cursor,
    member_id: int,
    data: dict,
) -> int:
    """게시글과 현직자 라운지 정보를 저장한다."""

    # 1. 공통 게시글 등록
    cursor.execute(
        """
        INSERT INTO posts (
            board_id,
            author_member_id,
            post_type,
            title,
            body,
            source_type,
            post_status,
            published_at
        )
        VALUES (
            NULL, %s, 'CAREER', %s, %s,
            'USER', 'PUBLISHED', CURRENT_TIMESTAMP
        )
        RETURNING post_id
        """,
        (
            member_id,
            data["title"],
            data["body"],
        ),
    )

    post_id = cursor.fetchone()["post_id"]

    # 2. 취업 게시판 분류 등록
    cursor.execute(
        """
        INSERT INTO career_posts (
            post_id,
            category_code,
            subcategory_code,
            is_anonymous
        )
        VALUES (%s, 'lounge', %s, %s)
        """,
        (
            post_id,
            data["subcategory_code"],
            data["is_anonymous"],
        ),
    )

    # 3. 현직자 라운지 추가 정보 등록
    cursor.execute(
        """
        INSERT INTO career_lounges (
            post_id,
            job_category_code,
            experience_years,
            company_name
        )
        VALUES (%s, %s, %s, %s)
        """,
        (
            post_id,
            data.get("job_category_code"),
            data.get("experience_years"),
            data.get("company_name"),
        ),
    )

    return post_id


# =========================================================
# 2. 현직자 라운지 상세 조회
# =========================================================

def get_lounge(
    cursor,
    post_id: int,
    member_id: int,
) -> dict | None:
    """게시글 ID를 이용해 현직자 라운지 상세 정보를 조회한다."""

    cursor.execute(
        """
        SELECT
            p.post_id AS id,
            p.title,
            p.body,
            p.created_at,
            p.updated_at,

            (p.author_member_id = %s) AS is_owner,

            CASE
                WHEN cp.is_anonymous THEN '익명'
                ELSE COALESCE(
                    NULLIF(m.nickname, ''),
                    '익명'
                )
            END AS author_name,

            cp.category_code,
            cp.subcategory_code,
            cp.is_anonymous,

            cl.job_category_code,
            cl.experience_years,
            cl.company_name

        FROM posts AS p

        JOIN members AS m
            ON m.member_id = p.author_member_id

        JOIN career_posts AS cp
            ON cp.post_id = p.post_id

        JOIN career_lounges AS cl
            ON cl.post_id = p.post_id

        WHERE p.post_id = %s
            AND p.post_type = 'CAREER'
            AND cp.category_code = 'lounge'
            AND p.deleted_at IS NULL
        """,
        (member_id, post_id),
    )

    return attach_post_reactions(cursor, cursor.fetchone(), member_id)


# =========================================================
# 3. 현직자 라운지 목록 조회
# =========================================================

def list_lounges(
    cursor,
    member_id: int,
    q: str | None = None,
    subcategory_code: str | None = None,
    job_category_code: str | None = None,
    experience_years: int | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict:
    """검색, 필터, 페이지네이션을 적용하여 목록을 조회한다."""

    conditions = [
        "p.post_type = 'CAREER'",
        "p.deleted_at IS NULL",
        "cp.category_code = 'lounge'",
    ]

    params = []

    # 1. 하위 카테고리 필터
    if subcategory_code:
        conditions.append(
            "cp.subcategory_code = %s"
        )
        params.append(subcategory_code)

    # 2. 직무 필터
    if job_category_code:
        conditions.append(
            "cl.job_category_code = %s"
        )
        params.append(job_category_code)

    # 3. 경력 연차 필터
    if experience_years is not None:
        conditions.append(
            "cl.experience_years = %s"
        )
        params.append(experience_years)

    # 4. 제목 및 본문 검색
    if q and q.strip():
        keyword = f"%{q.strip()}%"

        conditions.append(
            "(p.title ILIKE %s OR p.body ILIKE %s)"
        )

        params.extend([keyword, keyword])

    where_sql = " AND ".join(conditions)

    from_sql = """
        FROM posts AS p

        JOIN members AS m
            ON m.member_id = p.author_member_id

        JOIN career_posts AS cp
            ON cp.post_id = p.post_id

        JOIN career_lounges AS cl
            ON cl.post_id = p.post_id
    """

    # 5. 전체 게시글 수 조회
    cursor.execute(
        f"""
        SELECT
            COUNT(*) AS total

        {from_sql}

        WHERE {where_sql}
        """,
        params,
    )

    total = cursor.fetchone()["total"]

    # 6. 페이지 시작 위치
    offset = (page - 1) * page_size

    # 7. 게시글 목록 조회
    cursor.execute(
        f"""
        SELECT
            p.post_id AS id,
            p.title,
            LEFT(
                COALESCE(p.body, ''),
                150
            ) AS body_preview,
            p.created_at,

            (p.author_member_id = %s) AS is_owner,

            CASE
                WHEN cp.is_anonymous THEN '익명'
                ELSE COALESCE(
                    NULLIF(m.nickname, ''),
                    '익명'
                )
            END AS author_name,

            cp.subcategory_code,
            cp.is_anonymous,

            cl.job_category_code,
            cl.experience_years,
            cl.company_name

        {from_sql}

        WHERE {where_sql}

        ORDER BY
            p.created_at DESC NULLS LAST,
            p.post_id DESC

        LIMIT %s OFFSET %s
        """,
        (
            member_id,
            *params,
            page_size,
            offset,
        ),
    )

    return {
        "items": attach_list_reactions(cursor, list(cursor.fetchall())),
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# =========================================================
# 4. 현직자 라운지 작성자 확인
# =========================================================

def get_lounge_author_for_update(
    cursor,
    post_id: int,
) -> int | None:
    """게시글 행을 잠그고 작성자 ID를 조회한다."""

    cursor.execute(
        """
        SELECT
            p.author_member_id

        FROM posts AS p

        JOIN career_posts AS cp
            ON cp.post_id = p.post_id

        JOIN career_lounges AS cl
            ON cl.post_id = p.post_id

        WHERE p.post_id = %s
            AND p.post_type = 'CAREER'
            AND cp.category_code = 'lounge'
            AND p.deleted_at IS NULL

        FOR UPDATE OF p
        """,
        (post_id,),
    )

    row = cursor.fetchone()

    if row is None:
        return None

    return row["author_member_id"]


# =========================================================
# 5. 현직자 라운지 게시글 수정
# =========================================================

def update_lounge(
    cursor,
    post_id: int,
    changes: dict,
) -> None:
    """변경 요청에 포함된 필드만 수정한다.

    작성자 권한 검사는 Service에서 먼저 처리한다.
    """

    # 테이블별 수정 가능한 컬럼
    table_columns = {
        "posts": (
            "title",
            "body",
        ),
        "career_posts": (
            "subcategory_code",
            "is_anonymous",
        ),
        "career_lounges": (
            "job_category_code",
            "experience_years",
            "company_name",
        ),
    }

    for table_name, allowed_columns in table_columns.items():

        # 실제 변경 요청에 포함된 필드
        columns = [
            column
            for column in allowed_columns
            if column in changes
        ]

        if not columns:
            continue

        # UPDATE할 컬럼 목록 생성
        assignments = [
            f"{column} = %s"
            for column in columns
        ]

        # UPDATE할 값 목록 생성
        values = [
            changes[column]
            for column in columns
        ]

        if table_name == "posts":
            assignments.append(
                "updated_at = CURRENT_TIMESTAMP"
            )

        cursor.execute(
            f"""
            UPDATE {table_name}

            SET {", ".join(assignments)}

            WHERE post_id = %s
            """,
            (
                *values,
                post_id,
            ),
        )

    # 제목과 본문 외의 정보만 수정한 경우에도
    # 최종 수정일을 갱신한다.
    if "title" not in changes and "body" not in changes:
        cursor.execute(
            """
            UPDATE posts
            SET updated_at = CURRENT_TIMESTAMP
            WHERE post_id = %s
            """,
            (post_id,),
        )


# =========================================================
# 6. 현직자 라운지 게시글 논리 삭제
# =========================================================

def delete_lounge(
    cursor,
    post_id: int,
    member_id: int,
) -> bool:
    """게시글을 논리 삭제한다.

    실제 DB 행을 삭제하지 않고 deleted_at을 갱신한다.
    """

    cursor.execute(
        """
        UPDATE posts AS p

        SET
            deleted_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP

        WHERE p.post_id = %s
            AND p.author_member_id = %s
            AND p.post_type = 'CAREER'
            AND p.deleted_at IS NULL

            AND EXISTS (
                SELECT 1

                FROM career_posts AS cp

                JOIN career_lounges AS cl
                    ON cl.post_id = cp.post_id

                WHERE cp.post_id = p.post_id
                    AND cp.category_code = 'lounge'
            )
        """,
        (post_id, member_id),
    )

    return cursor.rowcount > 0


# =========================================================
# 커리어 연구소 Repository
# =========================================================


# =========================================================
# 1. 커리어 연구소 게시글 등록
# =========================================================

def create_lab(
    cursor,
    member_id: int,
    data: dict,
) -> int:
    """질문·토론 게시글과 투표 선택지를 등록한다."""

    # 1. 공통 게시글 생성
    cursor.execute(
        """
        INSERT INTO posts (
            board_id,
            author_member_id,
            post_type,
            title,
            body,
            source_type,
            post_status,
            published_at
        )
        VALUES (
            NULL, %s, 'CAREER', %s, %s,
            'USER', 'PUBLISHED', CURRENT_TIMESTAMP
        )
        RETURNING post_id
        """,
        (
            member_id,
            data["title"],
            data["body"],
        ),
    )

    post_id = cursor.fetchone()["post_id"]

    # 2. 취업 게시판 공통 분류 저장
    cursor.execute(
        """
        INSERT INTO career_posts (
            post_id,
            category_code,
            subcategory_code,
            is_anonymous
        )
        VALUES (%s, 'lab', %s, %s)
        """,
        (
            post_id,
            data["subcategory_code"],
            data["is_anonymous"],
        ),
    )

    # 3. 커리어 연구소 상세 정보 저장
    cursor.execute(
        """
        INSERT INTO career_labs (
            post_id,
            post_type,
            is_resolved
        )
        VALUES (%s, %s, FALSE)
        """,
        (
            post_id,
            data["post_type"],
        ),
    )

    # 4. 토론 게시글의 투표 선택지 저장
    poll_options = data.get("poll_options", [])

    for index, option_text in enumerate(
        poll_options,
        start=1,
    ):
        cursor.execute(
            """
            INSERT INTO career_lab_poll_options (
                post_id,
                option_text,
                display_order
            )
            VALUES (%s, %s, %s)
            """,
            (
                post_id,
                option_text,
                index,
            ),
        )

    return post_id


# =========================================================
# 2. 커리어 연구소 게시글 상세 조회
# =========================================================

def get_lab(
    cursor,
    post_id: int,
    member_id: int,
) -> dict | None:
    """게시글 상세 내용과 투표 현황을 조회한다."""

    # 1. 게시글 기본 정보
    cursor.execute(
        """
        SELECT
            p.post_id AS id,
            p.title,
            p.body,
            p.created_at,
            p.updated_at,

            (p.author_member_id = %s) AS is_owner,

            CASE
                WHEN cp.is_anonymous THEN '익명'
                ELSE COALESCE(
                    NULLIF(m.nickname, ''),
                    '익명'
                )
            END AS author_name,

            cp.category_code,
            cp.subcategory_code,
            cp.is_anonymous,

            cl.post_type,
            cl.is_resolved

        FROM posts AS p

        JOIN members AS m
            ON m.member_id = p.author_member_id

        JOIN career_posts AS cp
            ON cp.post_id = p.post_id

        JOIN career_labs AS cl
            ON cl.post_id = p.post_id

        WHERE p.post_id = %s
            AND p.post_type = 'CAREER'
            AND cp.category_code = 'lab'
            AND p.deleted_at IS NULL
        """,
        (
            member_id,
            post_id,
        ),
    )

    lab = cursor.fetchone()

    if lab is None:
        return None

    # 2. 투표 선택지와 선택지별 투표 수
    cursor.execute(
        """
        SELECT
            po.option_id,
            po.option_text,
            po.display_order,

            COUNT(pv.member_id) AS vote_count

        FROM career_lab_poll_options AS po

        LEFT JOIN career_lab_poll_votes AS pv
            ON pv.post_id = po.post_id
            AND pv.option_id = po.option_id

        WHERE po.post_id = %s

        GROUP BY
            po.option_id,
            po.option_text,
            po.display_order

        ORDER BY po.display_order
        """,
        (post_id,),
    )

    options = list(cursor.fetchall())

    # 3. 전체 투표 수
    total_votes = sum(
        option["vote_count"]
        for option in options
    )

    # 4. 현재 회원이 투표한 선택지
    cursor.execute(
        """
        SELECT option_id

        FROM career_lab_poll_votes

        WHERE post_id = %s
            AND member_id = %s
        """,
        (
            post_id,
            member_id,
        ),
    )

    my_vote = cursor.fetchone()

    # 5. 스키마에 맞게 결과 구성
    result = dict(lab)

    result["poll_options"] = options
    result["total_votes"] = total_votes
    result["my_vote_option_id"] = (
        my_vote["option_id"]
        if my_vote is not None
        else None
    )

    return attach_post_reactions(cursor, result, member_id)


# =========================================================
# 3. 커리어 연구소 게시글 목록 조회
# =========================================================

def list_labs(
    cursor,
    member_id: int,
    q: str | None = None,
    subcategory_code: str | None = None,
    post_type: str | None = None,
    is_resolved: bool | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict:
    """검색·게시글 유형·해결 여부별 목록을 조회한다."""

    # 1. 기본 조회 조건
    conditions = [
        "p.post_type = 'CAREER'",
        "p.deleted_at IS NULL",
        "cp.category_code = 'lab'",
    ]

    params = []

    # 2. 하위 카테고리 필터
    if subcategory_code:
        conditions.append(
            "cp.subcategory_code = %s"
        )
        params.append(subcategory_code)

    # 3. 질문·토론 유형 필터
    if post_type:
        conditions.append(
            "cl.post_type = %s"
        )
        params.append(post_type)

    # 4. 해결 여부 필터
    if is_resolved is not None:
        conditions.append(
            "cl.is_resolved = %s"
        )
        params.append(is_resolved)

    # 5. 제목·본문 검색
    if q and q.strip():
        keyword = f"%{q.strip()}%"

        conditions.append(
            "(p.title ILIKE %s OR p.body ILIKE %s)"
        )

        params.extend([
            keyword,
            keyword,
        ])

    where_sql = " AND ".join(conditions)

    from_sql = """
        FROM posts AS p

        JOIN members AS m
            ON m.member_id = p.author_member_id

        JOIN career_posts AS cp
            ON cp.post_id = p.post_id

        JOIN career_labs AS cl
            ON cl.post_id = p.post_id
    """

    # 6. 전체 게시글 개수
    cursor.execute(
        f"""
        SELECT COUNT(*) AS total

        {from_sql}

        WHERE {where_sql}
        """,
        params,
    )

    total = cursor.fetchone()["total"]

    # 7. 페이지 시작 위치
    offset = (page - 1) * page_size

    # 8. 게시글 목록 조회
    cursor.execute(
        f"""
        SELECT
            p.post_id AS id,
            p.title,

            LEFT(
                COALESCE(p.body, ''),
                150
            ) AS body_preview,

            p.created_at,

            (p.author_member_id = %s) AS is_owner,

            CASE
                WHEN cp.is_anonymous THEN '익명'
                ELSE COALESCE(
                    NULLIF(m.nickname, ''),
                    '익명'
                )
            END AS author_name,

            cp.subcategory_code,
            cp.is_anonymous,

            cl.post_type,
            cl.is_resolved

        {from_sql}

        WHERE {where_sql}

        ORDER BY
            p.created_at DESC NULLS LAST,
            p.post_id DESC

        LIMIT %s OFFSET %s
        """,
        (
            member_id,
            *params,
            page_size,
            offset,
        ),
    )

    return {
        "items": attach_list_reactions(cursor, list(cursor.fetchall())),
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# =========================================================
# 4. 작성자 확인 및 게시글 잠금
# =========================================================

def get_lab_author_for_update(
    cursor,
    post_id: int,
) -> int | None:
    """게시글을 잠그고 작성자 ID를 조회한다."""

    cursor.execute(
        """
        SELECT
            p.author_member_id

        FROM posts AS p

        JOIN career_posts AS cp
            ON cp.post_id = p.post_id

        JOIN career_labs AS cl
            ON cl.post_id = p.post_id

        WHERE p.post_id = %s
            AND p.post_type = 'CAREER'
            AND cp.category_code = 'lab'
            AND p.deleted_at IS NULL

        FOR UPDATE OF p
        """,
        (post_id,),
    )

    row = cursor.fetchone()

    if row is None:
        return None

    return row["author_member_id"]


# =========================================================
# 5. 커리어 연구소 게시글 수정
# =========================================================

def update_lab(
    cursor,
    post_id: int,
    changes: dict,
) -> None:
    """제목·본문·분류·익명 여부를 수정한다.

    게시글 유형과 투표 선택지는 수정할 수 없다.
    작성자 권한 검사는 Service에서 수행한다.
    """

    # 수정 가능한 필드만 허용
    table_columns = {
        "posts": (
            "title",
            "body",
        ),
        "career_posts": (
            "subcategory_code",
            "is_anonymous",
        ),
    }

    for table_name, allowed_columns in table_columns.items():

        columns = [
            column
            for column in allowed_columns
            if column in changes
        ]

        if not columns:
            continue

        assignments = [
            f"{column} = %s"
            for column in columns
        ]

        values = [
            changes[column]
            for column in columns
        ]

        # 수정 시각 갱신
        if table_name == "posts":
            assignments.append(
                "updated_at = CURRENT_TIMESTAMP"
            )

        cursor.execute(
            f"""
            UPDATE {table_name}

            SET {", ".join(assignments)}

            WHERE post_id = %s
            """,
            (
                *values,
                post_id,
            ),
        )

    # 분류·익명 여부만 수정한 경우
    if "title" not in changes and "body" not in changes:
        cursor.execute(
            """
            UPDATE posts
            SET updated_at = CURRENT_TIMESTAMP
            WHERE post_id = %s
            """,
            (post_id,),
        )


# =========================================================
# 6. 커리어 연구소 게시글 논리 삭제
# =========================================================

def delete_lab(
    cursor,
    post_id: int,
    member_id: int,
) -> bool:
    """게시글을 논리 삭제한다."""

    cursor.execute(
        """
        UPDATE posts AS p

        SET
            deleted_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP

        WHERE p.post_id = %s
            AND p.author_member_id = %s
            AND p.post_type = 'CAREER'
            AND p.deleted_at IS NULL

            AND EXISTS (
                SELECT 1

                FROM career_posts AS cp

                JOIN career_labs AS cl
                    ON cl.post_id = cp.post_id

                WHERE cp.post_id = p.post_id
                    AND cp.category_code = 'lab'
            )
        """,
        (
            post_id,
            member_id,
        ),
    )

    return cursor.rowcount > 0


# =========================================================
# 커리어 연구소 - 투표 및 질문 해결 상태 Repository
# =========================================================


# =========================================================
# 1. 질문 해결 상태 변경
# =========================================================

def update_lab_resolved(
    cursor,
    post_id: int,
    is_resolved: bool,
) -> bool:
    """질문 게시글의 해결 상태를 변경한다.

    작성자 권한 검사는 Service에서 수행한다.
    QUESTION 유형만 수정할 수 있다.
    """

    # 1. 질문 해결 상태 변경
    cursor.execute(
        """
        UPDATE career_labs
        SET is_resolved = %s
        WHERE post_id = %s
            AND post_type = 'QUESTION'
        RETURNING post_id
        """,
        (
            is_resolved,
            post_id,
        ),
    )

    row = cursor.fetchone()

    # 질문 게시글이 아니면 변경 실패
    if row is None:
        return False

    # 2. 게시글 최종 수정 시각 갱신
    cursor.execute(
        """
        UPDATE posts
        SET updated_at = CURRENT_TIMESTAMP
        WHERE post_id = %s
        """,
        (post_id,),
    )

    return True


# =========================================================
# 2. 투표 대상 게시글 확인 및 잠금
# =========================================================

def get_lab_poll_for_update(
    cursor,
    post_id: int,
) -> dict | None:
    """투표 대상 게시글을 조회하고 행을 잠근다.

    동일 게시글에 대한 동시 요청을 순서대로 처리한다.
    삭제된 게시글은 조회하지 않는다.
    """

    cursor.execute(
        """
        SELECT
            p.post_id,
            cl.post_type

        FROM posts AS p

        JOIN career_posts AS cp
            ON cp.post_id = p.post_id

        JOIN career_labs AS cl
            ON cl.post_id = p.post_id

        WHERE p.post_id = %s
            AND p.post_type = 'CAREER'
            AND cp.category_code = 'lab'
            AND p.deleted_at IS NULL

        FOR UPDATE OF p
        """,
        (post_id,),
    )

    return cursor.fetchone()


# =========================================================
# 3. 투표 선택지 유효성 확인
# =========================================================

def lab_poll_option_exists(
    cursor,
    post_id: int,
    option_id: int,
) -> bool:
    """선택지가 해당 게시글에 속하는지 확인한다."""

    cursor.execute(
        """
        SELECT 1

        FROM career_lab_poll_options

        WHERE post_id = %s
            AND option_id = %s
        """,
        (
            post_id,
            option_id,
        ),
    )

    return cursor.fetchone() is not None


# =========================================================
# 4. 회원 투표 등록
# =========================================================

def create_lab_vote(
    cursor,
    post_id: int,
    member_id: int,
    option_id: int,
) -> bool:
    """회원의 투표를 등록한다.

    동일 회원은 동일 게시글에 한 번만 투표할 수 있다.

    선택지 검증과 게시글 잠금은
    Service에서 먼저 수행해야 한다.
    """

    cursor.execute(
        """
        INSERT INTO career_lab_poll_votes (
            post_id,
            member_id,
            option_id
        )
        VALUES (%s, %s, %s)

        ON CONFLICT (post_id, member_id)
        DO NOTHING

        RETURNING option_id
        """,
        (
            post_id,
            member_id,
            option_id,
        ),
    )

    # 최초 투표라면 True
    # 이미 투표한 회원이면 False
    return cursor.fetchone() is not None


# =========================================
# 취업 게시글 공통 - 좋아요·스크랩·댓글 연결
# =========================================

def career_post_exists(cursor, post_id: int) -> bool:
    """삭제되지 않은 취업 게시글(4종 공통)인지 확인한다.

    취업 글은 board_id가 NULL이라 게시판 존재 확인을 쓸 수 없으므로
    posts.post_type과 career_posts 연결로 대상 여부를 판단한다.
    """
    cursor.execute(
        """
        SELECT 1
        FROM posts AS p
        JOIN career_posts AS cp ON cp.post_id = p.post_id
        WHERE p.post_id = %s
          AND p.post_type = 'CAREER'
          AND p.deleted_at IS NULL
        """,
        (post_id,),
    )
    return cursor.fetchone() is not None


def attach_post_reactions(cursor, row: dict | None, member_id: int) -> dict | None:
    """상세 응답에 좋아요 수·내 좋아요 여부·내 스크랩 여부를 붙인다.

    게시판(#27)의 좋아요·스크랩 조회 함수를 그대로 재사용한다.
    """
    if row is None:
        return None

    like = board_repository.get_post_like(cursor, row["id"], member_id)
    scrap = board_repository.get_post_scrap(cursor, row["id"], member_id)
    row["like_count"] = like["like_count"]
    row["liked_by_me"] = like["liked_by_me"]
    row["scrapped_by_me"] = scrap["scrapped_by_me"]
    return row


def attach_list_reactions(cursor, items: list[dict]) -> list[dict]:
    """목록 항목에 좋아요 수와 댓글 수를 한 번의 조회로 붙인다.

    댓글 수는 게시판과 같이 삭제되지 않은 댓글만 센다. (삭제 자리표시 제외)
    """
    post_ids = [item["id"] for item in items]
    if not post_ids:
        return items

    cursor.execute(
        """
        SELECT
            p.post_id,
            (
                SELECT COUNT(*)
                FROM post_likes AS l
                WHERE l.post_id = p.post_id
            )::int AS like_count,
            (
                SELECT COUNT(*)
                FROM comments AS c
                WHERE c.post_id = p.post_id
                  AND c.deleted_at IS NULL
            )::int AS comment_count
        FROM posts AS p
        WHERE p.post_id = ANY(%s)
        """,
        (post_ids,),
    )
    counts = {row["post_id"]: row for row in cursor.fetchall()}
    for item in items:
        item["like_count"] = counts[item["id"]]["like_count"]
        item["comment_count"] = counts[item["id"]]["comment_count"]
    return items
