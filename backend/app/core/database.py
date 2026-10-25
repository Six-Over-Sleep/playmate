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


# =========================================================
# psycopg 직접 연결
# 로그인 / 회원가입 기능에서 사용
# =========================================================
def get_db_connection():
    return psycopg.connect(
        host=DB_HOST,
        port=int(DB_PORT),
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME,
        sslmode=DB_SSLMODE,
        connect_timeout=10,
    )


# =========================================================
# SQLAlchemy 연결
# 모임 등 ORM 기반 API에서 사용
# =========================================================
DATABASE_URL = URL.create(
    drivername="postgresql+psycopg",
    username=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=int(DB_PORT),
    database=DB_NAME,
)


engine = create_engine(
    DATABASE_URL,
    connect_args={"sslmode": DB_SSLMODE},
    pool_pre_ping=True,
)


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


# FastAPI 요청마다 DB 세션 제공 및 종료
def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()