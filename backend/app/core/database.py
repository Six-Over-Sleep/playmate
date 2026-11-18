"""PLAYMATE PostgreSQL 연결 관리.

- psycopg 직접 연결: 로그인 등에서 아직 직접 사용하는 기존 코드와 호환
- SQLAlchemy ORM: 공유 DB의 작은 연결 한도(예: 20)를 고려한 제한된 풀

여러 개발자가 같은 DB를 사용하면 각 서버 프로세스가 별도 풀을 갖습니다.
"""

import logging
import os
from time import perf_counter

import psycopg
from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import (
    DB_HOST,
    DB_PORT,
    DB_USER,
    DB_PASSWORD,
    DB_NAME,
)
# 운영(development·test 외)에서 DB_SSLMODE=disable을 거부하는 검증을 psycopg2 경로와 공유한다.
from .db_connect import _sslmode


# 기존 직접 연결을 사용하는 다른 API를 위한 호환 함수.
# 컨텍스트 매니저(`with`)로 사용하여 연결을 확실히 닫아야 합니다.
def get_db_connection():
    return psycopg.connect(
        host=DB_HOST,
        port=int(DB_PORT),
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME,
        sslmode=_sslmode(),
        connect_timeout=10,
        application_name=os.getenv("DB_APPLICATION_NAME", "playmate") + "_direct",
    )


DATABASE_URL = URL.create(
    drivername="postgresql+psycopg",
    username=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=int(DB_PORT),
    database=DB_NAME,
)


# 공유 DB에서는 기존 기본값(1개)을 유지하고, AWS RDS로 전환한 뒤
# 전체 연결 예산에 맞춰 환경 변수로 조정할 수 있게 한다.
# 예: DB_POOL_SIZE=2 / DB_POOL_TIMEOUT=10 (서버 프로세스마다 별도 풀)
def _bounded_int(name, default, minimum, maximum):
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{name}은 정수여야 합니다.") from None
    if not minimum <= value <= maximum:
        raise ValueError(f"{name}은 {minimum}~{maximum} 범위여야 합니다.")
    return value


DB_POOL_SIZE = _bounded_int("DB_POOL_SIZE", 1, 1, 10)
DB_POOL_TIMEOUT = _bounded_int("DB_POOL_TIMEOUT", 15, 1, 60)
DB_SLOW_QUERY_MS = _bounded_int("DB_SLOW_QUERY_MS", 500, 0, 60000)
_db_logger = logging.getLogger(__name__)

engine = create_engine(
    DATABASE_URL,
    connect_args={
        "connect_timeout": 10,
        "application_name": os.getenv("DB_APPLICATION_NAME", "playmate") + "_orm",
    },
    pool_size=DB_POOL_SIZE,
    max_overflow=0,  # 연결 폭증 방지: 여유 연결을 명시적으로 만들지 않음
    pool_timeout=DB_POOL_TIMEOUT,
    pool_pre_ping=True,
    pool_recycle=900,
)


# 연결을 만들 때마다 SSL 설정을 검증한다(가져오기 시점이 아니라 실제 접속 시점).
@event.listens_for(engine, "do_connect")
def _enforce_sslmode(dialect, conn_rec, cargs, cparams):
    cparams["sslmode"] = _sslmode()


# DB 내부 SQL 실행 시간만 기록한다(풀 대기·네트워크 연결 수립 시간 제외).
# 파라미터 및 SQL 본문은 기록하지 않아 개인정보/세션 데이터가 노출되지 않는다.
@event.listens_for(engine, "before_cursor_execute")
def _before_sql(conn, cursor, statement, parameters, context, executemany):
    if DB_SLOW_QUERY_MS > 0:
        context._playmate_sql_started = perf_counter()


@event.listens_for(engine, "after_cursor_execute")
def _after_sql(conn, cursor, statement, parameters, context, executemany):
    started = getattr(context, "_playmate_sql_started", None)
    if started is None:
        return
    duration_ms = (perf_counter() - started) * 1000
    if duration_ms >= DB_SLOW_QUERY_MS:
        _db_logger.warning("Slow DB query: %.0f ms (statement omitted)", duration_ms)


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


# FastAPI 요청마다 SQLAlchemy 세션 생성 및 반환
# Session.close() 시 정상적으로 풀에 연결을 반환합니다.
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
