
"""
PlayMate FastAPI 메인 서버

주요 기능
1. Python 모듈 경로 설정
2. FastAPI 애플리케이션 생성
3. 로그인 세션 관리
4. CORS 설정
5. 기능별 API Router 등록
6. 이미지 업로드 경로 설정
7. 공통 예외 처리
8. 서버 및 DB 상태 확인
"""

import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware


# =========================================================
# 1. 프로젝트 경로 설정
# =========================================================

# backend/app/main.py 기준 경로
BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT_PATH = BACKEND_DIR.parent

# 프로젝트 루트와 backend 폴더를 Python 검색 경로에 추가
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

if str(PROJECT_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_PATH))


# =========================================================
# 2. 공통 모듈 Import
# =========================================================

# 서버 설정
from backend.app.core.config import SESSION_SECRET_KEY  # noqa: E402

# DB 연결
from backend.app.core.db_connect import db_cursor  # noqa: E402

# 이미지 업로드 경로
from backend.app.core.uploads import PROJECT_ROOT  # noqa: E402

# SQLAlchemy 모델 등록
from backend.app.models.member import Member  # noqa: E402, F401


# =========================================================
# 3. Router Import
# =========================================================

# 회원 인증
from backend.app.routers.auth import router as auth_router  # noqa: E402

# 일반 게시판
from backend.app.routers.board import router as board_router  # noqa: E402

# 모임
from backend.app.routers.recruit import router as recruit_router  # noqa: E402

# 마이페이지
from backend.app.routers.mypage import router as mypage_router  # noqa: E402

# 취업 카테고리
from backend.app.routers.career import router as career_router  # noqa: E402


# =========================================================
# 4. FastAPI 애플리케이션 생성
# =========================================================

app = FastAPI(
    title="PlayMate API",
    version="0.1.0",
)


# =========================================================
# 5. 로그인 세션 설정
# =========================================================

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY,
    session_cookie="playmate_session",
    same_site="lax",
    https_only=False,  # 로컬 개발 환경
)


# =========================================================
# 6. CORS 설정
# =========================================================

# .env의 FRONTEND_ORIGINS 환경변수 활용
# 예: http://localhost:5173,http://127.0.0.1:5173

origins = [
    value.strip()
    for value in os.getenv("FRONTEND_ORIGINS", "").split(",")
    if value.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# 7. Router 등록
# =========================================================

# 회원 인증 API
app.include_router(auth_router)

# 일반 게시판 API
app.include_router(board_router)

# 모임 API
app.include_router(recruit_router)

# 취업 카테고리 API
# 최종 주소: /api/career/...
app.include_router(career_router)

# 마이페이지 API
# 최종 주소: /api/mypage/...
app.include_router(
    mypage_router,
    prefix="/api",
)


# =========================================================
# 8. 이미지 업로드 경로 설정
# =========================================================

# 업로드 폴더 생성
UPLOAD_DIR = PROJECT_ROOT / "uploads"

UPLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

# 이미지 정적 파일 제공
# 예: /uploads/profiles/example.png
app.mount(
    "/uploads",
    StaticFiles(directory=UPLOAD_DIR),
    name="uploads",
)


# =========================================================
# 9. 공통 예외 처리
# =========================================================

# DB 연결 등 RuntimeError 발생 시 HTTP 503 반환
@app.exception_handler(RuntimeError)
def database_runtime_error(_, exc: RuntimeError):
    return JSONResponse(
        status_code=503,
        content={
            "detail": str(exc),
        },
    )


# =========================================================
# 10. 기본 서버 확인
# =========================================================

@app.get("/", tags=["health"])
def home():
    return {
        "message": "PlayMate API 실행 성공",
    }


# =========================================================
# 11. 서버 상태 확인
# =========================================================

@app.get("/health", tags=["health"])
def health():
    return {
        "status": "ok",
    }


# =========================================================
# 12. PostgreSQL 연결 확인
# =========================================================

@app.get("/health/db", tags=["health"])
def database_health():

    with db_cursor() as cursor:
        cursor.execute(
            """
            SELECT
                current_database() AS database_name,
                1 AS connected
            """
        )

        row = cursor.fetchone()

    return {
        "status": "ok",
        "database": row["database_name"],
    }
