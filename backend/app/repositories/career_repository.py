"""PLAYMATE 취업 후기 DB 조회·저장 함수.

트랜잭션은 career_service.py의 db_cursor(commit=True)가 담당한다.
이 파일에서는 commit/rollback하지 않는다.
"""


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
    return cursor.fetchone()

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
        "items": items,
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