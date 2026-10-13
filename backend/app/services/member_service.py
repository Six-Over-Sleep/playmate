
from psycopg.rows import dict_row

from app.core.database import get_db_connection
from app.schemas.member import MemberSignup


# 1. Discord ID로 기존 회원 조회
def get_member(discord_id: str) -> dict | None:
    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
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

            return cur.fetchone()


# 2. 신규 회원 등록
def register_member(
    discord_id: str,
    signup_data: MemberSignup,
) -> dict:

    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:

            # 신규 회원정보 저장
            cur.execute(
                """
                INSERT INTO members (
                    discord_id,
                    nickname,
                    course,
                    cohort,
                    role_code
                )
                VALUES (%s, %s, %s, %s, %s)
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

            member = cur.fetchone()

        conn.commit()

    return member
