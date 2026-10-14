import os
import logging
from contextlib import contextmanager
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")
logger = logging.getLogger(__name__)


def _sslmode() -> str:
    mode = os.getenv("DB_SSLMODE", "require").lower()
    app_env = os.getenv("APP_ENV", "production").lower()
    if mode in {"disable", "false", "0"} and app_env not in {"development", "test"}:
        raise RuntimeError("운영 환경에서는 DB_SSLMODE=require만 사용할 수 있습니다.")
    return "disable" if mode in {"disable", "false", "0"} else mode


def get_connection():
    """환경변수를 검증하고 시간 제한이 있는 게시판 DB 연결을 생성한다.

    필수 설정 누락과 접속 실패는 RuntimeError로 전달한다. 접속 실패 응답에는
    서버 주소·사용자 등 드라이버 내부 진단을 포함하지 않는다.
    """
    required = ["DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"누락된 DB 환경변수: {', '.join(missing)}")
    try:
        return psycopg2.connect(
            host=os.environ["DB_HOST"],
            port=int(os.getenv("DB_PORT", "5432")),
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            dbname=os.environ["DB_NAME"],
            sslmode=_sslmode(),
            connect_timeout=5,
        )
    except psycopg2.Error as exc:
        diagnostic = (
            getattr(getattr(exc, "diag", None), "message_primary", None)
            or str(exc).splitlines()[0]
        )
        logger.error(
            "PostgreSQL connection failed (%s, pgcode=%s): %s",
            type(exc).__name__,
            getattr(exc, "pgcode", None),
            diagnostic,
        )
        raise RuntimeError("PostgreSQL 연결에 실패했습니다.") from exc


@contextmanager
def db_cursor(*, commit: bool = False):
    """업무 단위의 커서를 제공하고 선택적으로 커밋한 뒤 연결을 닫는다.

    commit=True인 경우 응답 조회까지 성공해야 커밋한다. 본문·커밋 실패는
    롤백하며, 읽기 전용 연결도 finally에서 항상 닫는다.
    """
    connection = get_connection()
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            yield cursor
        if commit:
            connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
