import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from app.routers import career

# Support both `uvicorn app.main:app` from backend/ and
# `uvicorn backend.app.main:app` from the repository root.
BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT_PATH = BACKEND_DIR.parent

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

if str(PROJECT_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_PATH))

from app.core.config import SESSION_SECRET_KEY  # noqa: E402
from app.core.uploads import PROJECT_ROOT  # noqa: E402
from app.core.db_connect import db_cursor  # noqa: E402

from app.routers.auth import router as auth_router  # noqa: E402
from app.routers.board import router as board_router  # noqa: E402
from backend.app.routers.recruit import router as recruit_router  # noqa: E402

# 외래키가 참조하는 회원 테이블을 ORM에 등록함.
from backend.app.models.member import Member  # noqa: E402, F401


# FastAPI 애플리케이션 생성
app = FastAPI(
    title="PlayMate API",
    version="0.1.0",
)


# 로그인 세션 관리
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY,
    session_cookie="playmate_session",
    same_site="lax",
    https_only=False,  # 로컬 개발용, 배포 시 True 검토
)


# React 프론트엔드 CORS 설정
origins = [
    value.strip()
    for value in os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if value.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 라우터 등록
app.include_router(auth_router)
app.include_router(board_router)
app.include_router(recruit_router)
app.include_router(career.router)

# 업로드 폴더 설정
PROJECT_ROOT.joinpath("uploads").mkdir(exist_ok=True)

app.mount(
    "/uploads",
    StaticFiles(directory=PROJECT_ROOT / "uploads"),
    name="uploads",
)


# DB 관련 RuntimeError 처리
@app.exception_handler(RuntimeError)
def database_runtime_error(_, exc: RuntimeError):
    return JSONResponse(
        status_code=503,
        content={"detail": str(exc)},
    )


# 서버 상태 확인
@app.get("/", tags=["health"])
def home():
    return {"message": "PlayMate API 실행 성공"}


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


@app.get("/health/db", tags=["health"])
def database_health():
    with db_cursor() as cursor:
        cursor.execute(
            "SELECT current_database() AS database_name, 1 AS connected"
        )
        row = cursor.fetchone()

    return {
        "status": "ok",
        "database": row["database_name"],
    }