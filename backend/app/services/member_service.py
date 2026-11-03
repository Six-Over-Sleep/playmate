# PLAYMATE_COMMENT_AVATAR_V1
# PLAYMATE_BOARD_REPORTS_V1
"""Discord 회원 조회·가입과 과정/기수별 게시판 자동 생성."""

from app.core.db_connect import db_cursor
from app.schemas.member import MemberSignup


COURSE_NAMES = {
    "family-ai": "패밀리 AI",
    "multi-agent": "멀티 에이전트",
    "data-engineering": "데이터 엔지니어링",
    "data-ml": "데이터·머신러닝",
}


def get_member(discord_id: str) -> dict | None:
    """Discord ID에 해당하는 PLAYMATE 회원을 조회합니다."""
    with db_cursor(read_only=True) as cursor:
        cursor.execute(
            """
            SELECT
                member_id,
                discord_id,
                nickname,
                course,
                cohort,
                role_code,
                profile_image_url
            FROM members
            WHERE discord_id = %s
              AND member_status = 'ACTIVE'
            """,
            (discord_id,),
        )
        row = cursor.fetchone()
    return dict(row) if row else None


def sync_member_avatar(member_id: int, avatar_url: str | None) -> None:
    """로그인한 회원의 Discord 아바타 URL만 저장합니다."""
    with db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            UPDATE members
            SET profile_image_url = %s
            WHERE member_id = %s
              AND profile_image_url IS DISTINCT FROM %s
            """,
            (avatar_url, member_id, avatar_url),
        )


def ensure_course_board(cursor, course: str, cohort: int) -> None:
    """과정·기수 조합에 해당하는 게시판을 한 번만 만듭니다.

    회원가입과 동일한 트랜잭션에서 실행해 데이터 불일치를 방지합니다.
    이미 존재하는 게시판은 수정하거나 덮어쓰지 않습니다.
    """
    course_name = COURSE_NAMES.get(course)
    if course_name is None or cohort < 1:
        raise ValueError("올바르지 않은 과정 또는 기수입니다.")

    board_name = f"{course_name} {cohort}기"
    cursor.execute(
        """
        INSERT INTO boards (
            board_name, description, creation_reason, created_by,
            course_code, cohort, is_default
        )
        VALUES (%s, %s, %s, NULL, %s, %s, FALSE)
        ON CONFLICT DO NOTHING
        """,
        (
            board_name,
            "같은 과정·기수 수강생을 위한 게시판입니다. 다른 과정에서는 열람만 가능합니다.",
            "회원 과정·기수 기준 자동 생성",
            course,
            cohort,
        ),
    )
    # 기존 일반 게시판과 이름이 겹치면 ON CONFLICT로 생성되지 않을 수 있습니다.
    # 가입만 성공하고 게시판이 없는 상태를 막기 위해 실제 연결을 확인합니다.
    cursor.execute(
        """
        SELECT board_id FROM boards
        WHERE course_code = %s AND cohort = %s
        """,
        (course, cohort),
    )
    if cursor.fetchone() is None:
        raise RuntimeError(
            "과정 게시판 생성에 실패했습니다. 동일한 이름의 기존 게시판을 확인해주세요."
        )



def announce_course_board(cursor, course: str, cohort: int) -> None:
    """신규 과정 게시판 공지를 한번만 생성합니다. 잠금으로 중복 생성 방지."""
    # 게시판 행 자체를 잠그면 동시 가입도 공지 중복 없이 직렬화됩니다.
    cursor.execute(
        "SELECT board_id, board_name, description FROM boards "
        "WHERE course_code = %s AND cohort = %s FOR UPDATE",
        (course, cohort),
    )
    board = cursor.fetchone()
    if board is None:
        raise RuntimeError("과정 게시판을 찾을 수 없습니다.")
    cursor.execute("SELECT 1 FROM board_notice_posts WHERE board_id = %s", (board["board_id"],))
    if cursor.fetchone() is not None:
        return

    cursor.execute("SELECT board_id FROM boards WHERE board_name = '공지사항' LIMIT 1")
    notice = cursor.fetchone()
    cursor.execute(
        "SELECT member_id FROM members WHERE UPPER(TRIM(COALESCE(role_code, ''))) = 'ADMIN' "
        "ORDER BY member_id LIMIT 1"
    )
    admin = cursor.fetchone()
    if notice is None or admin is None:
        # 게시판 개설을 막지 않습니다. 누락 공지는 019 SQL 재실행으로 보충할 수 있습니다.
        import logging
        logging.getLogger(__name__).warning("과정 공지를 생성하지 못함: 공지사항 또는 ADMIN 없음")
        return

    cursor.execute(
        """
        INSERT INTO posts (
            board_id, author_member_id, post_type, title, body,
            source_type, post_status, published_at, is_anonymous
        ) VALUES (%s, %s, 'BOARD', %s, %s, 'SYSTEM', 'PUBLISHED', CURRENT_TIMESTAMP, FALSE)
        RETURNING post_id
        """,
        (
            notice["board_id"], admin["member_id"],
            f'[게시판 안내] {board["board_name"]}',
            f'{board["board_name"]} 게시판이 개설되었습니다.\n\n'
            f'{board["description"] or ""}\n\n'
            '열람은 모든 회원에게 열려 있으며 글과 댓글은 해당 과정·기수 회원만 작성할 수 있습니다.',
        ),
    )
    post_id = cursor.fetchone()["post_id"]
    cursor.execute(
        "INSERT INTO board_notice_posts (board_id, post_id) VALUES (%s, %s)",
        (board["board_id"], post_id),
    )

def register_member(discord_id: str, signup_data: MemberSignup) -> dict:
    """회원 가입 시 같은 과정·기수의 게시판도 자동 생성합니다.

    Discord DM 알림(external_dm_opt_in)은 기본 ON으로 저장합니다.
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
        ensure_course_board(cursor, row["course"], row["cohort"])
        announce_course_board(cursor, row["course"], row["cohort"])
    return dict(row)


# PLAYMATE_85_AUTO_FIX

def withdraw_member(member_id: int, discord_id: str) -> bool:
    """회원 식별정보를 비식별화하고 게시글/댓글의 회원 FK를 보존한다.

    동일한 DB 트랜잭션에서 처리되므로 일부 처리만 반영되지 않습니다.
    """
    with db_cursor(commit=True) as cursor:
        cursor.execute(
            """
            UPDATE members
            SET discord_id = 'w' || member_id::text,
                nickname = substring(md5('withdrawn:' || member_id::text), 1, 20),
                member_status = 'WITHDRAWN',
                role_code = 'USER',
                course = 'withdrawn',
                cohort = 0,
                profile_image_url = NULL,
                external_dm_opt_in = FALSE,
                updated_at = CURRENT_TIMESTAMP
            WHERE member_id = %s
              AND discord_id = %s
              AND member_status = 'ACTIVE'
            RETURNING member_id
            """,
            (member_id, discord_id),
        )
        if cursor.fetchone() is None:
            return False

        # 개인 프로필 데이터 및 다른 사람에게 남긴 반응/스크랩 제거.
        cursor.execute("DELETE FROM member_career_specs WHERE member_id = %s", (member_id,))
        cursor.execute(
            "DELETE FROM notifications WHERE receiver_member_id = %s OR actor_member_id = %s",
            (member_id, member_id),
        )
        cursor.execute("DELETE FROM post_likes WHERE member_id = %s", (member_id,))
        cursor.execute("DELETE FROM post_scraps WHERE member_id = %s", (member_id,))
    return True
