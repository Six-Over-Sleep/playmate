"""PostgreSQL 연결 설정과, 알림 / 공식 채널 기능 저장소가 함께 쓰는 연결.

새 기능은 모임 저장소(PostgresMeetingRepository)와 연결을 공유하지 않는다. 새 기능의 쿼리가
느리거나 실패해도 모임 동기화·lifecycle 쪽 연결과 락에 영향을 주지 않게 하기 위해서다.
"""
import threading
from typing import Any, Callable


def connect_from_env():
    """환경변수(DB_*)로 연결한다: autocommit, 서울 시간대, 서버 statement_timeout. 두 저장소가 함께 쓴다."""
    import psycopg
    import config

    return psycopg.connect(
        host=config.DB_HOST, port=int(config.DB_PORT), user=config.DB_USER,
        password=config.DB_PASSWORD, dbname=config.DB_NAME,
        sslmode=config.DB_SSLMODE, connect_timeout=10, autocommit=True,
        options=(
            "-c TimeZone=Asia/Seoul "
            f"-c statement_timeout={config.DB_STATEMENT_TIMEOUT_MS}"
        ),
    )


class Database:
    """연결 하나를 처음 쿼리할 때 열고(lazy), 한 번에 SQL 하나만 실행한다."""

    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect
        self._conn = None
        self._lock = threading.RLock()

    @classmethod
    def from_env(cls):
        """실제 연결은 첫 쿼리 때 연다."""
        return cls(connect_from_env)

    def _reset(self) -> None:
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        self._conn = None

    def execute(self, sql: str, params: tuple = (), *, fetch: str | None = None, write: bool = False):
        """SQL 한 개를 실행한다.

        fetch=None: 쓰기. 영향 받은 행 수를 돌려주며 재시도하지 않는다.
        fetch="one"/"all": 읽기. 연결이 끊겼으면 다시 연결해서 한 번 재시도한다.
        write=True: RETURNING이 있는 쓰기. 결과 행을 돌려주지만 재시도하지 않는다
            (응답만 유실되고 실제로는 commit되었을 수 있기 때문).
        """
        import psycopg

        attempts = 1 if fetch is None or write else 2
        with self._lock:
            for attempt in range(1, attempts + 1):
                try:
                    if self._conn is None or self._conn.closed:
                        self._conn = self._connect()
                    with self._conn.cursor() as cur:
                        cur.execute(sql, params)
                        rowcount = cur.rowcount
                        names = [d.name for d in cur.description] if cur.description else []
                        rows = cur.fetchall() if fetch and cur.description else []
                    if fetch is None:
                        return rowcount
                    dicts = [dict(zip(names, row)) for row in rows]
                    if fetch == "one":
                        return dicts[0] if dicts else None
                    return dicts
                except psycopg.OperationalError:
                    self._reset()
                    if attempt == attempts:
                        raise

    def transaction(self, work: Callable[[Any], Any]) -> Any:
        """work(cursor)를 한 트랜잭션에서 실행한다 (행은 dict). 예외가 나면 rollback하며 재시도하지 않는다.

        여러 SQL을 원자적으로 묶어야 할 때만 쓴다 (예: advisory lock + 집계 + 선점).
        """
        import psycopg
        from psycopg.rows import dict_row

        with self._lock:
            try:
                if self._conn is None or self._conn.closed:
                    self._conn = self._connect()
                with self._conn.transaction():
                    with self._conn.cursor(row_factory=dict_row) as cur:
                        return work(cur)
            except psycopg.OperationalError:
                self._reset()
                raise

    def table_exists(self, table_name: str) -> bool:
        """public 스키마에 테이블이 있는지 확인한다. 없는 테이블을 조회해 오류를 내지 않기 위해 쓴다."""
        row = self.execute(
            "SELECT to_regclass(%s) IS NOT NULL AS present",
            (f"public.{table_name}",), fetch="one",
        )
        return bool(row and row["present"])
