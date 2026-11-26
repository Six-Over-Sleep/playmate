"""후기·톡톡·라운지·연구소의 공통 저장 로직.

필수 DB 버전: 040 적용 이후.
뉴스·채용공고·수집 데이터는 다루지 않는다.
"""

import json
from datetime import date, datetime


DETAIL_FIELDS = {
    "reviews": (
        "company_name",
        "is_company_private",
        "job_category_code",
        "application_type",
        "process_stage",
        "process_result",
        "process_date",
        "interview_format",
    ),
    "talk": (
        "job_category_code",
        "current_status",
    ),
    "lounge": (
        "job_category_code",
        "experience_years",
        "company_name",
    ),
    "lab": (
        "post_type",
        "is_resolved",
        "guide_experience",
        "guide_advice",
    ),
}

# 연구소 유형·해결 상태·선택지는 일반 수정 경로에서 변경하지 않는다.
UPDATE_DETAIL_FIELDS = {
    **DETAIL_FIELDS,
    "lab": (
        "guide_experience",
        "guide_advice",
    ),
}

COMMON_UPDATE_COLUMNS = {
    "title": "title",
    "body": "body",
    "is_anonymous": "is_anonymous",
}


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()

    raise TypeError(
        f"JSON으로 저장할 수 없는 타입입니다: {type(value).__name__}"
    )


def _encode_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        default=_json_default,
        allow_nan=False,
    )


def _validate_category(category):
    if category not in DETAIL_FIELDS:
        raise ValueError(f"지원하지 않는 취업 분류입니다: {category}")


def create_content(cursor, member_id, category, data):
    """공통 게시글과 취업 상세를 호출자의 트랜잭션에 저장한다.

    입력 검증과 회원 권한 확인은 서비스에서 먼저 수행한다.
    """
    _validate_category(category)

    details = {
        field: data.get(field)
        for field in DETAIL_FIELDS[category]
    }

    if category == "reviews":
        details["is_company_private"] = data.get(
            "is_company_private", False
        )

    if category == "lab":
        details["is_resolved"] = False

    option_texts = data.get("poll_options") or []

    if option_texts and (
        category != "lab"
        or data.get("post_type") != "DISCUSSION"
    ):
        raise ValueError("투표는 연구소 토론 글에만 추가할 수 있습니다.")

    if option_texts and not 2 <= len(option_texts) <= 10:
        raise ValueError("투표 선택지는 2개 이상 10개 이하이어야 합니다.")

    poll_options = []

    for display_order, option_text in enumerate(option_texts, start=1):
        if (
            not isinstance(option_text, str)
            or not option_text.strip()
            or len(option_text) > 200
        ):
            raise ValueError("투표 선택지는 1~200자의 문자열이어야 합니다.")

        cursor.execute(
            """
            SELECT nextval(
                'public.career_poll_option_id_seq'
            ) AS option_id
            """
        )
        option_id = cursor.fetchone()["option_id"]

        poll_options.append(
            {
                "option_id": option_id,
                "option_text": option_text,
                "display_order": display_order,
            }
        )

    # 직렬화 오류는 게시글 INSERT 전에 확인한다.
    details_json = _encode_json(details)
    poll_options_json = _encode_json(poll_options)

    cursor.execute(
        """
        INSERT INTO public.posts (
            board_id,
            author_member_id,
            post_type,
            title,
            body,
            source_type,
            post_status,
            published_at,
            is_anonymous
        )
        VALUES (
            NULL,
            %s,
            'CAREER',
            %s,
            %s,
            'USER',
            'PUBLISHED',
            CURRENT_TIMESTAMP,
            %s
        )
        RETURNING post_id
        """,
        (
            member_id,
            data["title"],
            data["body"],
            data.get("is_anonymous", True),
        ),
    )

    post_id = cursor.fetchone()["post_id"]

    cursor.execute(
        """
        INSERT INTO public.career (
            post_id,
            category_code,
            subcategory_code,
            details,
            poll_options
        )
        VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
        """,
        (
            post_id,
            category,
            data["subcategory_code"],
            details_json,
            poll_options_json,
        ),
    )

    return post_id


def update_content(cursor, post_id, category, changes):
    """허용된 필드만 수정한다.

    서비스에서 작성자 권한을 먼저 확인해야 한다.
    posts → career 순서로 잠가 기존 저장·투표 경로와 순서를 맞춘다.
    """
    _validate_category(category)

    allowed_fields = (
        set(COMMON_UPDATE_COLUMNS)
        | {"subcategory_code"}
        | set(UPDATE_DETAIL_FIELDS[category])
    )
    unknown_fields = set(changes) - allowed_fields

    if unknown_fields:
        raise ValueError(
            "수정할 수 없는 필드입니다: "
            + ", ".join(sorted(unknown_fields))
        )

    if not changes:
        raise ValueError("수정할 항목이 없습니다.")

    cursor.execute(
        """
        SELECT p.post_id
        FROM public.posts AS p
        JOIN public.career AS c
            ON c.post_id = p.post_id
        WHERE p.post_id = %s
          AND p.post_type = 'CAREER'
          AND p.deleted_at IS NULL
          AND c.category_code = %s
        FOR UPDATE OF p
        """,
        (post_id, category),
    )

    if cursor.fetchone() is None:
        raise ValueError("수정할 취업 게시글을 찾을 수 없습니다.")

    cursor.execute(
        """
        SELECT post_id
        FROM public.career
        WHERE post_id = %s
          AND category_code = %s
        FOR UPDATE
        """,
        (post_id, category),
    )

    if cursor.fetchone() is None:
        raise ValueError("취업 상세 정보를 찾을 수 없습니다.")

    detail_changes = {
        field: changes[field]
        for field in UPDATE_DETAIL_FIELDS[category]
        if field in changes
    }
    details_json = (
        _encode_json(detail_changes)
        if detail_changes
        else None
    )

    post_assignments = ["updated_at = CURRENT_TIMESTAMP"]
    post_values = []

    for field, column in COMMON_UPDATE_COLUMNS.items():
        if field in changes:
            post_assignments.append(f"{column} = %s")
            post_values.append(changes[field])

    # 컬럼명은 위 고정 목록에서만 가져온다.
    cursor.execute(
        f"""
        UPDATE public.posts
        SET {", ".join(post_assignments)}
        WHERE post_id = %s
        """,
        (*post_values, post_id),
    )

    career_assignments = []
    career_values = []

    if "subcategory_code" in changes:
        career_assignments.append("subcategory_code = %s")
        career_values.append(changes["subcategory_code"])

    if details_json is not None:
        career_assignments.append("details = details || %s::jsonb")
        career_values.append(details_json)

    if career_assignments:
        cursor.execute(
            f"""
            UPDATE public.career
            SET {", ".join(career_assignments)}
            WHERE post_id = %s
              AND category_code = %s
            """,
            (*career_values, post_id, category),
        )