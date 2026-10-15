"""게시판용 psycopg2 연결과 프로세스별 소규모 풀을 관리한다.

db_cursor는 인증·업무마다 연결을 빌리되, 정리한 연결을 다음 호출에 재사용한다.
DB_POOL_MAX_CONNECTIONS는 프로세스당 1~4개(기본 2), DB_POOL_WAIT_SECONDS는
풀 대기 0.1~5초(기본 2)이다. 유휴 연결은 1개만 유지한다. 설정 변경은 재시작한다.
풀은 첫 사용 때 생성하므로 worker별로 독립적이다. 이미 사용한 풀을 상속하는
fork는 거부한다. worker 생성 전에 DB에 접속하지 않는다.
"""

import atexit
import os
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import BoundedSemaphore, Lock

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor
from psycopg2.extensions import (
    TRANSACTION_STATUS_IDLE,
    TRANSACTION_STATUS_INERROR,
    TRANSACTION_STATUS_INTRANS,
)
from psycopg2.pool import PoolError, ThreadedConnectionPool

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")
logger = logging.getLogger(__name__)
_pool_lock = Lock()
_pool_state = None


class CommitOutcomeUnknownError(RuntimeError):
    """COMMIT 응답 유실로 저장 성공 여부를 확인할 수 없는 오류.

    DB가 이미 참조할 수 있으므로 호출자는 관련 업로드 파일을 삭제하면 안 된다.
    """


def _sslmode() -> str:
    mode = os.getenv("DB_SSLMODE", "require").lower()
    app_env = os.getenv("APP_ENV", "production").lower()
    if mode in {"disable", "false", "0"} and app_env not in {"development", "test"}:
        raise RuntimeError("운영 환경에서는 DB_SSLMODE=require만 사용할 수 있습니다.")
    return "disable" if mode in {"disable", "false", "0"} else mode


def _connection_settings() -> dict:
    """기존 환경변수·SSL·접속 시간 제한을 한 곳에서 검증한다."""
    required = ["DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"누락된 DB 환경변수: {', '.join(missing)}")
    return {
        "host": os.environ["DB_HOST"],
        "port": int(os.getenv("DB_PORT", "5432")),
        "user": os.environ["DB_USER"],
        "password": os.environ["DB_PASSWORD"],
        "dbname": os.environ["DB_NAME"],
        "sslmode": _sslmode(),
        "connect_timeout": 5,
    }


def get_connection():
    """환경변수를 검증하고 시간 제한이 있는 게시판 DB 연결을 생성한다.

    필수 설정 누락과 접속 실패는 RuntimeError로 전달한다. 접속 실패 응답에는
    서버 주소·사용자 등 드라이버 내부 진단을 포함하지 않는다.
    """
    try:
        return psycopg2.connect(**_connection_settings())
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


@dataclass
class _PoolState:
    pool: ThreadedConnectionPool
    slots: BoundedSemaphore
    pid: int
    active: int = 0
    retired: bool = False


def _pool_limits() -> tuple[int, float]:
    """공유 DB 연결 수와 대기를 제한할 보수적인 설정을 반환한다."""
    try:
        maximum = int(os.getenv("DB_POOL_MAX_CONNECTIONS", "2"))
        wait = float(os.getenv("DB_POOL_WAIT_SECONDS", "2"))
    except ValueError as exc:
        raise RuntimeError("DB 연결 풀 설정이 올바르지 않습니다.") from exc
    if not 1 <= maximum <= 4 or not 0.1 <= wait <= 5:
        raise RuntimeError("DB 연결 풀 설정이 허용 범위를 벗어났습니다.")
    return maximum, wait


def _finish_retired_pool(state: _PoolState) -> None:
    """잠금을 보유한 상태에서 사용자가 없는 폐기 풀을 종료한다."""
    global _pool_state
    if state.retired and state.active == 0:
        if not state.pool.closed:
            state.pool.closeall()
        if _pool_state is state:
            _pool_state = None


def close_pool() -> None:
    """서버 종료 시 풀을 닫는다. 사용 중인 업무는 반환 후 닫아 중단하지 않는다."""
    if _pool_state is None or _pool_state.pid != os.getpid():
        return
    with _pool_lock:
        if _pool_state is not None and _pool_state.pid == os.getpid():
            _pool_state.retired = True
            _finish_retired_pool(_pool_state)


def _get_pool_state(wait: float, maximum: int) -> _PoolState:
    """첫 사용에만 풀을 생성한다. 프로세스 상속·종료 중 재사용은 거부한다."""
    global _pool_state
    if _pool_state is not None and _pool_state.pid != os.getpid():
        raise RuntimeError("상속된 DB 연결 풀을 사용할 수 없습니다.")
    if not _pool_lock.acquire(timeout=wait):
        raise RuntimeError("DB 연결 풀 준비 대기 시간이 초과되었습니다.")
    try:
        if _pool_state is not None:
            if _pool_state.pid != os.getpid():
                raise RuntimeError("상속된 DB 연결 풀을 사용할 수 없습니다.")
            if _pool_state.retired:
                raise RuntimeError("DB 연결 풀을 정리 중입니다.")
        else:
            try:
                pool = ThreadedConnectionPool(1, maximum, **_connection_settings())
            except psycopg2.Error as exc:
                logger.warning(
                    "PostgreSQL pool connection failed (%s)", type(exc).__name__
                )
                raise RuntimeError("PostgreSQL 연결에 실패했습니다.") from exc
            _pool_state = _PoolState(pool, BoundedSemaphore(maximum), os.getpid())
        return _pool_state
    finally:
        _pool_lock.release()


def _close_connection(connection) -> None:
    """정리 오류가 원래 업무 결과를 덮어쓰지 않도록 연결 종료를 시도한다."""
    try:
        connection.close()
    except psycopg2.Error as exc:
        logger.warning("PostgreSQL connection close failed (%s)", type(exc).__name__)


@dataclass
class _ConnectionLease:
    connection: object
    state: _PoolState | None

    def release(self, *, discard: bool = False) -> None:
        """열린 트랜잭션을 롤백하고 정상 연결만 반환한다. 고장 연결은 폐기한다."""
        if self.state is None:
            _close_connection(self.connection)
            return
        state = self.state
        try:
            if not discard and not self.connection.closed:
                status = self.connection.info.transaction_status
                if status in {TRANSACTION_STATUS_INTRANS, TRANSACTION_STATUS_INERROR}:
                    self.connection.rollback()
                discard = (
                    self.connection.info.transaction_status != TRANSACTION_STATUS_IDLE
                )
            state.pool.putconn(
                self.connection, close=discard or bool(self.connection.closed)
            )
        except (psycopg2.Error, PoolError) as exc:
            logger.warning("PostgreSQL pool return failed (%s)", type(exc).__name__)
            with _pool_lock:
                state.retired = True
            _close_connection(self.connection)
        finally:
            with _pool_lock:
                state.active -= 1
                _finish_retired_pool(state)
            state.slots.release()


def _acquire_connection() -> _ConnectionLease:
    """제한 시간 안에 독점 연결을 빌린다. 손상된 유휴 연결만 한 번 교체한다."""
    maximum, wait = _pool_limits()
    state = _get_pool_state(wait, maximum)
    if not state.slots.acquire(timeout=wait):
        raise RuntimeError("사용 가능한 DB 연결 대기 시간이 초과되었습니다.")
    with _pool_lock:
        if state.retired:
            state.slots.release()
            raise RuntimeError("DB 연결 풀을 정리 중입니다.")
        state.active += 1
    handed_off = False
    try:
        for _ in range(2):
            connection = state.pool.getconn()
            if (
                not connection.closed
                and connection.info.transaction_status == TRANSACTION_STATUS_IDLE
            ):
                handed_off = True
                return _ConnectionLease(connection, state)
            state.pool.putconn(connection, close=True)
        raise RuntimeError("정상적인 DB 연결을 확보하지 못했습니다.")
    except (psycopg2.Error, PoolError) as exc:
        with _pool_lock:
            state.retired = True
        raise RuntimeError("PostgreSQL 연결에 실패했습니다.") from exc
    finally:
        # 정상 대여는 release가 슬롯을 반환한다. 예외 경로만 여기에서 반환한다.
        if not handed_off:
            with _pool_lock:
                state.active -= 1
                _finish_retired_pool(state)
            state.slots.release()


atexit.register(close_pool)


@contextmanager
def db_cursor(*, commit: bool = False):
    """업무 단위의 커서를 제공하고 선택적으로 커밋한 뒤 풀에 반환한다.

    commit=True인 경우 응답 조회까지 성공해야 커밋한다. 본문·커밋 실패는
    롤백하며, 읽기 전용 연결도 finally에서 롤백 후 반환한다. COMMIT 중 연결이
    끊기면 결과 불명확 오류로 구분한다. 정리 오류는 원래 예외·성공을 덮지 않는다.
    """
    lease = _acquire_connection()
    connection = lease.connection
    discard = False
    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            yield cursor
        if commit:
            try:
                connection.commit()
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as exc:
                if exc.pgcode is not None:
                    # 서버가 명시적으로 거부한 커밋은 기존 실패·파일 정리 흐름을 따른다.
                    raise
                discard = True
                raise CommitOutcomeUnknownError(
                    "DB 저장 결과를 확인하지 못했습니다."
                ) from exc
    except BaseException as exc:
        discard = (
            discard or isinstance(exc, psycopg2.Error) or not isinstance(exc, Exception)
        )
        try:
            connection.rollback()
        except psycopg2.Error as rollback_error:
            discard = True
            logger.warning(
                "PostgreSQL rollback failed (%s)", type(rollback_error).__name__
            )
        if (
            isinstance(exc, (psycopg2.OperationalError, psycopg2.InterfaceError))
            and exc.pgcode is None
        ):
            raise RuntimeError("PostgreSQL 연결이 종료되었습니다.") from exc
        raise
    finally:
        lease.release(discard=discard)
