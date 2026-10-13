import os

from fastapi import Header, HTTPException, status

from app.core.db_connect import db_cursor


def get_current_member_id(x_dev_member_id: int | None = Header(default=None)) -> int:
    """Temporary adapter point for the Discord OAuth dependency.

    X-Dev-Member-ID is accepted only in development/test. The referenced member
    must already exist, so an arbitrary id never gains write permission.
    """
    app_env = os.getenv("APP_ENV", "production").lower()
    if app_env not in {"development", "test"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다.")
    if x_dev_member_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="개발 환경에서는 X-Dev-Member-ID 헤더가 필요합니다.",
        )
    with db_cursor() as cursor:
        cursor.execute("SELECT 1 FROM members WHERE member_id = %s", (x_dev_member_id,))
        if cursor.fetchone() is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="존재하지 않는 개발용 사용자입니다.")
    return x_dev_member_id
