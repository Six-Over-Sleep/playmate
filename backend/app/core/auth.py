
"""Discord OAuth 세션 기반 회원 인증."""

from fastapi import HTTPException, Request

from .db_connect import db_cursor



def get_current_member_id(request: Request) -> int:
    """서명 세션의 회원 ID와 RDS 세션 버전을 함께 검증합니다."""
    member_id = request.session.get("member_id")
    if member_id is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    version = request.session.get("session_version")
    user = request.session.get("user")
    if (
        type(member_id) is not int
        or type(version) is not int
        or version < 0
        or not isinstance(user, dict)
        or not isinstance(user.get("discord_id"), str)
        or not user["discord_id"]
    ):
        request.session.clear()
        raise HTTPException(status_code=401, detail="유효하지 않은 로그인 세션입니다.")

    with db_cursor(read_only=True) as cursor:
        cursor.execute(
            """
            SELECT 1 FROM public.members
            WHERE member_id = %s
              AND discord_id = %s
              AND member_status = 'ACTIVE'
              AND session_version = %s
            """,
            (member_id, user["discord_id"], version),
        )
        if cursor.fetchone() is None:
            request.session.clear()
            raise HTTPException(status_code=401, detail="로그인 세션이 만료되었습니다.")
    return member_id
