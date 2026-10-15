"""실제 ThreadedConnectionPool에 가짜 연결을 주어 재사용·격리·고장 복구를 검증한다."""

from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context
import os
from threading import Barrier, Event
from time import perf_counter
from types import SimpleNamespace

from fastapi.testclient import TestClient
import psycopg2
from psycopg2.extensions import (
    TRANSACTION_STATUS_IDLE,
    TRANSACTION_STATUS_INERROR,
    TRANSACTION_STATUS_INTRANS,
    TRANSACTION_STATUS_UNKNOWN,
)
import pytest

from app.core import db_connect as db
from app.main import app


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, *args, **kwargs):
        self.conn.info.transaction_status = TRANSACTION_STATUS_INTRANS
        if self.conn.query_error:
            self.conn.info.transaction_status = TRANSACTION_STATUS_UNKNOWN
            raise self.conn.query_error

    def fetchone(self):
        return {"database_name": "test", "connected": 1}


class FakeConnection:
    def __init__(self):
        self.closed = False
        self.info = SimpleNamespace(transaction_status=TRANSACTION_STATUS_IDLE)
        self.rollbacks = 0
        self.commits = 0
        self.query_error = None
        self.rollback_error = None
        self.commit_error = None

    def cursor(self, **kwargs):
        return FakeCursor(self)

    def rollback(self):
        self.rollbacks += 1
        if self.rollback_error:
            raise self.rollback_error
        self.info.transaction_status = TRANSACTION_STATUS_IDLE

    def commit(self):
        self.commits += 1
        if self.commit_error:
            raise self.commit_error
        self.info.transaction_status = TRANSACTION_STATUS_IDLE

    def close(self):
        self.closed = True


class Factory:
    def __init__(self):
        self.created = []
        self.error = None

    def __call__(self, *args, **kwargs):
        if self.error:
            raise self.error
        connection = FakeConnection()
        self.created.append(connection)
        return connection


@pytest.fixture
def pool(monkeypatch):
    """실DB 연결을 차단하고 테스트마다 풀을 새로 시작한다."""
    db.close_pool()
    monkeypatch.setenv("DB_POOL_MAX_CONNECTIONS", "2")
    monkeypatch.setenv("DB_POOL_WAIT_SECONDS", "0.1")
    monkeypatch.setenv("DB_SSLMODE", "require")
    factory = Factory()
    monkeypatch.setattr(db.psycopg2, "connect", factory)
    yield factory
    db.close_pool()
    assert db._pool_state is None


def test_pool_is_lazy_and_reads_rollback_before_reuse(pool):
    assert not pool.created
    with db.db_cursor() as cursor:
        cursor.execute("SELECT 1")
        connection = cursor.conn
    assert len(pool.created) == 1 and connection.rollbacks == 1
    assert connection.info.transaction_status == TRANSACTION_STATUS_IDLE
    with db.db_cursor() as cursor:
        assert cursor.conn is connection
        cursor.execute("SELECT 1")
    assert len(pool.created) == 1 and connection.rollbacks == 2
    assert not connection.closed


def test_successful_commit_is_not_rolled_back(pool):
    with db.db_cursor(commit=True) as cursor:
        cursor.execute("INSERT placeholder")
        connection = cursor.conn
    assert connection.commits == 1 and connection.rollbacks == 0
    assert connection.info.transaction_status == TRANSACTION_STATUS_IDLE


def test_business_error_rolls_back_before_next_request(pool):
    with pytest.raises(ValueError):
        with db.db_cursor() as cursor:
            cursor.execute("SELECT 1")
            connection = cursor.conn
            raise ValueError("business failure")
    with db.db_cursor() as cursor:
        assert cursor.conn is connection
        assert connection.info.transaction_status == TRANSACTION_STATUS_IDLE
    assert connection.rollbacks == 1


def test_disconnected_query_is_discarded_and_next_request_recovers(pool):
    with pytest.raises(RuntimeError, match="연결이 종료"):
        with db.db_cursor() as cursor:
            connection = cursor.conn
            connection.query_error = psycopg2.OperationalError("socket lost")
            cursor.execute("SELECT 1")
    assert connection.closed
    with db.db_cursor() as cursor:
        assert cursor.conn is not connection
    assert len(pool.created) == 2


def test_ambiguous_commit_connection_is_never_reused(pool):
    with pytest.raises(db.CommitOutcomeUnknownError):
        with db.db_cursor(commit=True) as cursor:
            connection = cursor.conn
            cursor.execute("INSERT placeholder")
            connection.commit_error = psycopg2.OperationalError("acknowledgement lost")
            connection.rollback_error = psycopg2.InterfaceError("closed")
    assert connection.closed
    with db.db_cursor() as cursor:
        assert cursor.conn is not connection


def test_return_rollback_failure_retires_pool(pool):
    with db.db_cursor() as cursor:
        cursor.execute("SELECT 1")
        connection = cursor.conn
        connection.rollback_error = psycopg2.InterfaceError("closed")
        old_state = db._pool_state
    assert old_state.pool.closed and db._pool_state is None
    with db.db_cursor() as cursor:
        assert cursor.conn is not connection


@pytest.mark.parametrize(
    "status",
    [
        TRANSACTION_STATUS_UNKNOWN,
        TRANSACTION_STATUS_INTRANS,
        TRANSACTION_STATUS_INERROR,
    ],
)
def test_bad_idle_state_is_replaced_before_user_sql(pool, status):
    with db.db_cursor() as cursor:
        connection = cursor.conn
    connection.info.transaction_status = status
    with db.db_cursor() as cursor:
        assert cursor.conn is not connection
        assert cursor.conn.info.transaction_status == TRANSACTION_STATUS_IDLE
    assert connection.closed


def test_closed_idle_connection_is_replaced(pool):
    with db.db_cursor() as cursor:
        connection = cursor.conn
    connection.close()
    with db.db_cursor() as cursor:
        assert cursor.conn is not connection


def test_concurrent_leases_are_exclusive_and_exhaustion_is_bounded(pool):
    entered = Barrier(3)
    finish = Event()

    def worker():
        with db.db_cursor() as cursor:
            connection = cursor.conn
            entered.wait(timeout=3)
            assert finish.wait(timeout=3)
            return id(connection)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker) for _ in range(2)]
        try:
            entered.wait(timeout=3)
            start = perf_counter()
            with pytest.raises(RuntimeError, match="대기 시간이 초과"):
                with db.db_cursor():
                    pass
            assert 0.08 <= perf_counter() - start < 2
            assert len(pool.created) == 2
        finally:
            finish.set()
        assert len({future.result(timeout=3) for future in futures}) == 2
    assert db._pool_state.active == 0
    with db.db_cursor() as cursor:
        assert not cursor.conn.closed


def test_shutdown_defers_close_until_active_lease_returns(pool):
    with db.db_cursor() as cursor:
        connection = cursor.conn
        db.close_pool()
        assert not connection.closed
        with pytest.raises(RuntimeError, match="정리 중"):
            with db.db_cursor():
                pass
    assert connection.closed and db._pool_state is None


def test_fastapi_shutdown_closes_idle_pool(pool):
    with TestClient(app) as client:
        assert client.get("/health/db").status_code == 200
        connection = pool.created[0]
        assert not connection.closed
    assert connection.closed and db._pool_state is None
    with TestClient(app) as client:
        assert client.get("/health/db").status_code == 200
        assert pool.created[-1] is not connection
    assert len(pool.created) == 2 and all(conn.closed for conn in pool.created)


def test_pool_creation_failure_releases_initialization_lock(pool):
    pool.error = psycopg2.OperationalError("unavailable")
    with pytest.raises(RuntimeError, match="연결에 실패"):
        with db.db_cursor():
            pass
    assert db._pool_state is None
    pool.error = None
    with db.db_cursor() as cursor:
        assert not cursor.conn.closed


def test_inherited_pool_is_not_shared_between_processes(pool, monkeypatch):
    with db.db_cursor():
        pass
    original = os.getpid()
    with monkeypatch.context() as patch:
        patch.setattr(db.os, "getpid", lambda: original + 1)
        with pytest.raises(RuntimeError, match="상속된"):
            with db.db_cursor():
                pass
        db.close_pool()
    assert not pool.created[0].closed


@pytest.mark.parametrize(
    "key,value",
    [
        ("DB_POOL_MAX_CONNECTIONS", "0"),
        ("DB_POOL_MAX_CONNECTIONS", "5"),
        ("DB_POOL_WAIT_SECONDS", "nan"),
        ("DB_POOL_WAIT_SECONDS", "0"),
        ("DB_POOL_MAX_CONNECTIONS", "bad"),
    ],
)
def test_invalid_pool_limits_fail_without_connecting(pool, monkeypatch, key, value):
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError):
        with db.db_cursor():
            pass
    assert not pool.created


def _worker_pool(queue):
    """spawn된 worker가 자신의 풀만 생성·종료하는지 확인한다. 실제 DB는 사용하지 않는다."""
    factory = Factory()
    db.psycopg2.connect = factory
    with db.db_cursor():
        pool_pid = db._pool_state.pid
    db.close_pool()
    queue.put(
        (
            os.getpid(),
            pool_pid,
            len(factory.created),
            all(c.closed for c in factory.created),
        )
    )


def test_spawned_workers_have_independent_pools(pool):
    context = get_context("spawn")
    queue = context.Queue()
    workers = [context.Process(target=_worker_pool, args=(queue,)) for _ in range(2)]
    try:
        for worker in workers:
            worker.start()
        results = [queue.get(timeout=15) for _ in workers]
        for worker in workers:
            worker.join(timeout=15)
            assert worker.exitcode == 0
        assert len({row[0] for row in results}) == 2
        assert all(
            pid == owner and pid != os.getpid() and count == 1 and closed
            for pid, owner, count, closed in results
        )
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
        queue.close()


def test_failed_replacement_releases_capacity(pool):
    """끊어진 유휴 연결의 교체 접속까지 실패해도 슬롯을 누수하지 않는다."""
    with db.db_cursor() as cursor:
        connection = cursor.conn
    connection.close()
    pool.error = psycopg2.OperationalError("replacement unavailable")
    with pytest.raises(RuntimeError, match="연결에 실패"):
        with db.db_cursor():
            pass
    assert db._pool_state is None
    pool.error = None
    with db.db_cursor() as cursor:
        assert not cursor.conn.closed


def test_initialization_wait_is_bounded(pool):
    """다른 스레드가 풀을 준비 중이어도 무한히 기다리지 않는다."""
    db._pool_lock.acquire()
    try:
        with pytest.raises(RuntimeError, match="준비 대기 시간이 초과"):
            with db.db_cursor():
                pass
    finally:
        db._pool_lock.release()
    assert not pool.created


def test_retired_pool_does_not_close_another_active_lease(pool, monkeypatch):
    """반환 오류가 나도 다른 업무 연결은 반환될 때까지 닫지 않는다."""
    from psycopg2.pool import PoolError

    first = db._acquire_connection()
    second = db._acquire_connection()
    state = first.state
    original = state.pool.putconn

    def fail_first(connection, **kwargs):
        if connection is first.connection:
            raise PoolError("return failed")
        return original(connection, **kwargs)

    monkeypatch.setattr(state.pool, "putconn", fail_first)
    first.release()
    assert state.retired and state.active == 1
    assert not second.connection.closed
    with pytest.raises(RuntimeError, match="정리 중"):
        db._acquire_connection()
    second.release()
    assert second.connection.closed and db._pool_state is None
    with db.db_cursor() as cursor:
        assert not cursor.conn.closed
