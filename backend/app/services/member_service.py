"""Discord 회원 조회와 가입을 공통 PostgreSQL 연결 풀로 처리한다.

인증이 사용하는 연결을 게시판/마이페이지와 공유하여 제한된 DB 연결을 절약한다.
"""

from app.core.db_connect import db_cursor
from app.schemas.member import MemberSignup


def get_member(discord_id: str) -> dict | None:
    """Discord ID에 해당하는 PLAYMATE 회원을 조회한다."""
    with db_cursor(read_only=True) as cursor:
        cursor.execute(
            """
            SELECT
                member_id,
                discord_id,
                nickname,
                course,
                cohort,
                role_code
            FROM members
            WHERE discord_id = %s
            """,
            (discord_id,),
        )
        row = cursor.fetchone()
    return dict(row) if row else None


def register_member(discord_id: str, signup_data: MemberSignup) -> dict:
    """신규 회원을 등록한다. 성공 시에만 트랜잭션을 커밋한다.

    Discord DM 알림(external_dm_opt_in)은 기본 ON으로 저장하고, 회원이 /알림설정으로 끌 수 있다.
    """
    with db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            INSERT INTO members (
                discord_id,
                nickname,
                course,
                cohort,
                role_code,
                external_dm_opt_in
            )
            VALUES (%s, %s, %s, %s, %s, TRUE)
            RETURNING
                member_id,
                discord_id,
                nickname,
                course,
                cohort,
                role_code
            """,
            (
                discord_id,
                signup_data.nickname,
                signup_data.track,
                signup_data.cohort,
                "USER",
            ),
        )
        row = cursor.fetchone()
    return dict(row)
