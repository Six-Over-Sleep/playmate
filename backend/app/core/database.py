
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.engine import URL

BASE_DIR = Path(__file__).resolve().parents[3] # 프로젝트 루트 경로 검색
load_dotenv(BASE_DIR / ".env") # .env에서 접속 정보 불러오기

# PostgreSQL 연결 주소 생성
DATABASE_URL = URL.create( 
    drivername = "postgresql+psycopg2",
    username = os.getenv("DB_USER"),
    password = os.getenv("DB_PASSWORD"),
    host = os.getenv("DB_HOST"),
    port = int(os.getenv("DB_PORT", "5432")),
    database = os.getenv("DB_NAME"),
)

# SQLAlchemy DB 엔진 생성
engine = create_engine( 
    DATABASE_URL,
    connect_args = {"sslmode": "require"},
    pool_pre_ping = True, # 연결 재사용 전 유효성 확인
)

# DB 작업에 사용할 세션 생성
SessionLocal = sessionmaker(
    bind = engine,
    autoflush = False,
    autocommit = False,
)

# SQLAlchemy 모델의 공통 부모 클래스
class Base(DeclarativeBase):
    pass

# FastAPI 요청마다 DB 세션 제공 및 종료
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
