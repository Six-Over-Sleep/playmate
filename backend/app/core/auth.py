import os

from fastapi import Header, HTTPException, Request, status

from app.core.db_connect import db_cursor


def get_current_member_id(
    request: Request,
    x_dev_member_id: int | None = Header(default=None),
) -> int:
    """서명된 Discord 로그인 세션을 우선하여 현재 회원 ID를 반환한다.

    request의 회원 ID와 Discord ID가 DB에서 일치해야 인증한다. 세션이 있으면
    개발 헤더로 덮어쓸 수 없다. 세션이 없는 개발·테스트 환경에서만 기존
    X-Dev-Member-ID를 허용한다. 누락·잘못된 세션·없는 회원은 401이다.
    """
    member_id = request.session.get("member_id")
    if member_id is not None:
        user = request.session.get("user")
        if (
            type(member_id) is not int
            or not isinstance(user, dict)
            or not user.get("discord_id")
        ):
            raise HTTPException(
                status_code=401, detail="유효하지 않은 로그인 세션입니다."
            )
        with db_cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM members
                WHERE member_id = %s
                    AND discord_id = %s
                """,
                (member_id, str(user["discord_id"])),
            )
            if cursor.fetchone() is None:
                raise HTTPException(
                    status_code=401, detail="유효하지 않은 로그인 세션입니다."
                )
        return member_id
    app_env = os.getenv("APP_ENV", "production").lower()
    if app_env not in {"development", "test"}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다."
        )
    if x_dev_member_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="개발 환경에서는 X-Dev-Member-ID 헤더가 필요합니다.",
        )
    with db_cursor() as cursor:
        cursor.execute("SELECT 1 FROM members WHERE member_id = %s", (x_dev_member_id,))
        if cursor.fetchone() is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="존재하지 않는 개발용 사용자입니다.",
            )
    return x_dev_member_id
