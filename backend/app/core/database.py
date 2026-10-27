"""PLAYMATE PostgreSQL 연결 관리.

- psycopg 직접 연결: 로그인 등에서 아직 직접 사용하는 기존 코드와 호환
- SQLAlchemy ORM: 공유 DB의 작은 연결 한도(예: 20)를 고려한 제한된 풀

여러 개발자가 같은 DB를 사용하면 각 서버 프로세스가 별도 풀을 갖습니다.
"""

import os

import psycopg
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import (
    DB_HOST,
    DB_PORT,
    DB_USER,
    DB_PASSWORD,
    DB_NAME,
    DB_SSLMODE,
)


# 기존 직접 연결을 사용하는 다른 API를 위한 호환 함수.
# 컨텍스트 매니저(`with`)로 사용하여 연결을 확실히 닫아야 합니다.
def get_db_connection():
    return psycopg.connect(
        host=DB_HOST,
        port=int(DB_PORT),
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME,
        sslmode=DB_SSLMODE,
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


# 기본 SQLAlchemy 연결 풀(5+10)이 공유 DB의 연결 한도를 소진하지 않게 제한.
# 프로세스당 ORM 연결 최대 1개, 초과 요청은 최대 15초 대기합니다.
engine = create_engine(
    DATABASE_URL,
    connect_args={
        "sslmode": DB_SSLMODE,
        "connect_timeout": 10,
        "application_name": os.getenv("DB_APPLICATION_NAME", "playmate") + "_orm",
    },
    pool_size=1,
    max_overflow=0,
    pool_timeout=15,
    pool_pre_ping=True,
    pool_recycle=900,
)


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
