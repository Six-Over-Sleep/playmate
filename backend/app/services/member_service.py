"""Discord 회원 조회·가입과 전국 교육기관 소속 등록."""

import logging

from fastapi import HTTPException

from app.core.db_connect import db_cursor
from app.schemas.member import MemberSignup

logger = logging.getLogger(__name__)

# 기존 코드의 고정 과정명은 레거시 게시판 유지에만 사용합니다.
COURSE_NAMES = {
    "family-ai": "패밀리 AI",
    "multi-agent": "멀티 에이전트",
    "data-engineering": "데이터 엔지니어링",
    "data-ml": "데이터·머신러닝",
}


def get_member(discord_id: str) -> dict | None:
    with db_cursor(read_only=True) as cursor:
        cursor.execute(
            """
            SELECT member_id, discord_id, nickname, course, cohort,
                   role_code, profile_image_url
            FROM public.members
            WHERE discord_id = %s AND member_status = 'ACTIVE'
            """,
            (discord_id,),
        )
        row = cursor.fetchone()
    return dict(row) if row else None


def get_education_options() -> list[dict]:
    """현재 등록 가능한 학교/과정/기수를 한 번에 조회합니다."""
    with db_cursor(read_only=True) as cursor:
        cursor.execute(
            """
            SELECT c.cohort_id, c.cohort_no,
                   i.institution_id, i.institution_name,
                   p.program_id, p.program_name,
                   campus.campus_name
            FROM public.cohorts AS c
            JOIN public.programs AS p ON p.program_id = c.program_id
            JOIN public.institutions AS i ON i.institution_id = c.institution_id
            LEFT JOIN public.campuses AS campus ON campus.campus_id = c.campus_id
            WHERE i.status = 'ACTIVE' AND p.status = 'ACTIVE'
            ORDER BY i.institution_name, p.program_name, c.cohort_no, c.cohort_id
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def sync_member_avatar(member_id: int, avatar_url: str | None) -> None:
    with db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            UPDATE public.members
            SET profile_image_url = %s
            WHERE member_id = %s
              AND profile_image_url IS DISTINCT FROM %s
            """,
            (avatar_url, member_id, avatar_url),
        )


def _lookup_cohort(cursor, cohort_id: int) -> dict:
    """클라이언트가 넘긴 숫자를 신뢰하지 않고 실제 등록된 기수인지 검사합니다."""
    cursor.execute(
        """
        SELECT c.cohort_id, c.cohort_no, c.campus_id,
               p.program_id, p.program_code, p.program_name,
               i.institution_id, i.institution_code, i.institution_name,
               campus.campus_name
        FROM public.cohorts AS c
        JOIN public.programs AS p ON p.program_id = c.program_id
        JOIN public.institutions AS i ON i.institution_id = c.institution_id
        LEFT JOIN public.campuses AS campus ON campus.campus_id = c.campus_id
        WHERE c.cohort_id = %s
          AND i.status = 'ACTIVE'
          AND p.status = 'ACTIVE'
        """,
        (cohort_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise HTTPException(422, "가입할 수 없는 교육과정 또는 기수입니다.")
    return dict(row)


def _legacy_family_ai_board(info: dict) -> bool:
    """기존 36기 게시판 8번은 권한 전환(031) 전까지 그대로 둡니다."""
    return (
        info["institution_code"] == "playdata"
        and info["program_code"] == "family-ai"
        and info["cohort_no"] == 36
        and info["campus_id"] is None
    )


def _ensure_cohort_board(cursor, info: dict) -> None:
    """기수 행 잠금을 이용해 동시 가입에서도 게시판을 한 번만 만듭니다."""
    cursor.execute(
        "SELECT cohort_id FROM public.cohorts WHERE cohort_id = %s FOR UPDATE",
        (info["cohort_id"],),
    )
    if cursor.fetchone() is None:
        raise HTTPException(422, "가입할 수 없는 교육과정 또는 기수입니다.")

    cursor.execute(
        "SELECT board_id FROM public.boards WHERE scope_type = 'COHORT' AND cohort_id = %s",
        (info["cohort_id"],),
    )
    if cursor.fetchone():
        return

    if _legacy_family_ai_board(info):
        # 기존 36기 게시판이 이미 운영 중이므로 그대로 연결합니다.
        cursor.execute(
            """
            SELECT board_id FROM public.boards
            WHERE board_id = 8 AND course_code = 'family-ai' AND cohort = 36
            """
        )
        if cursor.fetchone() is not None:
            return

        # 신규 RDS에 레거시 게시판이 없다면
        # 아래 공통 COHORT 게시판 생성 로직으로 진행합니다.

    # 신규 과정은 LEGACY course_code를 사용하지 않아 기관 간 쓰기 권한 충돌을 방지합니다.
    campus_suffix = f" {info['campus_name']}" if info.get("campus_name") else ""
    # boards.board_name은 VARCHAR(40). 기수 ID를 접미사로 넣어 충돌을 방지합니다.
    tail = f" {info['cohort_no']}기 #{info['cohort_id']}"
    prefix = f"{info['institution_name']} {info['program_name']}{campus_suffix}"
    board_name = prefix[:40 - len(tail)] + tail
    if len(board_name) > 40 or len(tail) >= 40:
        raise HTTPException(422, "교육과정 식별자가 너무 길어 게시판을 생성할 수 없습니다.")
    cursor.execute(
        """
        INSERT INTO public.boards (
            board_name, description, creation_reason, created_by,
            scope_type, cohort_id, read_policy, write_policy, is_default
        )
        VALUES (%s, %s, '회원가입 시 기수별 자동 생성', NULL,
                'COHORT', %s, 'ALL_VERIFIED', 'SCOPE_ONLY', FALSE)
        """,
        (
            board_name,
            "가입한 기수는 글·댓글을 작성할 수 있고 다른 등록 회원도 열람할 수 있습니다.",
            info["cohort_id"],
        ),
    )


def register_member(discord_id: str, signup_data: MemberSignup) -> dict:
    """회원+소속+게시판을 단일 트랜잭션으로 저장합니다. 관리자 승인 절차는 없습니다."""
    with db_cursor(commit=True) as cursor:
        info = _lookup_cohort(cursor, signup_data.cohort_id)
        # 종전 과정 문자열은 기존 API 호환용입니다. 타 기관의 코드 충돌을 차단합니다.
        legacy_code = (
            info["program_code"] if _legacy_family_ai_board(info)
            else f"program:{info['program_id']}"
        )
        cursor.execute(
            """
            INSERT INTO public.members (
                discord_id, nickname, course, cohort, role_code, external_dm_opt_in
            ) VALUES (%s, %s, %s, %s, 'USER', TRUE)
            RETURNING member_id, discord_id, nickname, course, cohort, role_code
            """,
            (discord_id, signup_data.nickname, legacy_code, info["cohort_no"]),
        )
        member = dict(cursor.fetchone())
        cursor.execute(
            """
            INSERT INTO public.member_enrollments (
                member_id, cohort_id, enrollment_status
            ) VALUES (%s, %s, 'ACTIVE')
            """,
            (member["member_id"], info["cohort_id"]),
        )
        _ensure_cohort_board(cursor, info)
    return member


def withdraw_member(member_id: int, discord_id: str) -> bool:
    """탈퇴 시 기존 비식별화에 더해 새 교육기관 소속 정보를 정리합니다."""
    with db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            UPDATE public.members
            SET discord_id = 'w' || member_id::text,
                nickname = substring(md5('withdrawn:' || member_id::text), 1, 20),
                member_status = 'WITHDRAWN', role_code = 'USER',
                course = 'withdrawn', cohort = 0,
                profile_image_url = NULL, external_dm_opt_in = FALSE,
                updated_at = CURRENT_TIMESTAMP
            WHERE member_id = %s AND discord_id = %s AND member_status = 'ACTIVE'
            RETURNING member_id
            """,
            (member_id, discord_id),
        )
        if cursor.fetchone() is None:
            return False
        # 기존 FK의 기본 정책이 RESTRICT이므로 검증 이력부터 삭제합니다.
        cursor.execute(
            """
            DELETE FROM public.enrollment_verifications
            WHERE enrollment_id IN (
                SELECT enrollment_id FROM public.member_enrollments WHERE member_id = %s
            )
            """,
            (member_id,),
        )
        cursor.execute(
            "DELETE FROM public.member_enrollments WHERE member_id = %s",
            (member_id,),
        )
        cursor.execute("DELETE FROM public.member_career_specs WHERE member_id = %s", (member_id,))
        cursor.execute(
            "DELETE FROM public.notifications WHERE receiver_member_id = %s OR actor_member_id = %s",
            (member_id, member_id),
        )
        cursor.execute("DELETE FROM public.post_likes WHERE member_id = %s", (member_id,))
        cursor.execute("DELETE FROM public.post_scraps WHERE member_id = %s", (member_id,))
    return True
