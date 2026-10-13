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
        diagnostic = getattr(getattr(exc, "diag", None), "message_primary", None) or str(exc).splitlines()[0]
        logger.error("PostgreSQL connection failed (%s, pgcode=%s): %s", type(exc).__name__, getattr(exc, "pgcode", None), diagnostic)
        raise RuntimeError(f"PostgreSQL 연결에 실패했습니다: {diagnostic}") from exc


@contextmanager
def db_cursor(*, commit: bool = False):
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
