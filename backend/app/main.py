# PlayMate FastAPI 서버의 실행 환경과 공통 설정을 관리하는 파일
# 로그인 세션, CORS, 라우터, 업로드 경로 및 서버 상태 확인 API를 등록함.
import os
import sys
from pathlib import Path

# FastAPI : API 서버를 생성하는 프레임워크
from fastapi import FastAPI
# CORSMiddleware : React 프론트엔드의 교차 출처 요청을 허용하는 설정
from fastapi.middleware.cors import CORSMiddleware
# JSONResponse : HTTP 상태 코드와 JSON 응답을 직접 지정할 때 사용함.
from fastapi.responses import JSONResponse
# StaticFiles : 업로드된 이미지 등 정적 파일을 제공할 때 사용함.
from fastapi.staticfiles import StaticFiles
# SessionMiddleware : 쿠키를 이용해 로그인 세션 정보를 관리함.
from starlette.middleware.sessions import SessionMiddleware


# 1. 서버 실행 위치에 따른 Python 모듈 경로 설정
# backend/ 폴더에서 `uvicorn app.main:app`으로 실행하는 경우와
# 프로젝트 루트에서 `uvicorn backend.app.main:app`으로 실행하는 경우를 모두 지원함.
# __file__ : 현재 파일(main.py)의 경로
# parents[1] : backend 폴더 / parent : 프로젝트 최상위 폴더
BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT_PATH = BACKEND_DIR.parent

# sys.path : Python이 import할 모듈을 검색하는 경로 목록
# 중복 경로를 추가하지 않도록 먼저 포함 여부를 확인함.
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

if str(PROJECT_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_PATH))

# 서버 설정과 DB 연결 및 이미지 업로드에 필요한 기능 가져오기
# noqa: E402 : 모듈 경로 설정 이후 import하도록 의도한 코드의 린트 경고를 제외함.
from app.core.config import SESSION_SECRET_KEY  # noqa: E402
from app.core.uploads import PROJECT_ROOT  # noqa: E402
from app.core.db_connect import db_cursor  # noqa: E402

# 기능별 API Router 가져오기 (로그인 / 게시판 / 모임)
from app.routers.auth import router as auth_router  # noqa: E402
from app.routers.board import router as board_router  # noqa: E402
from backend.app.routers.recruit import router as recruit_router  # noqa: E402

# 회원 테이블 모델을 SQLAlchemy 메타데이터에 등록하기 위한 import
# F401 : 이 파일에서 이름을 직접 사용하지 않으므로 미사용 import 경고를 제외함.
from backend.app.models.member import Member  # noqa: E402, F401


# 2. FastAPI 애플리케이션 생성
# title : Swagger 문서에 표시되는 API 이름
# version : 현재 API 버전
app = FastAPI(
    title="PlayMate API",
    version="0.1.0",
)


# 3. 로그인 세션 관리 미들웨어 등록
# SessionMiddleware : 사용자별 세션을 서명된 쿠키로 관리함.
# secret_key : 쿠키 변조 방지에 사용할 비밀키
# session_cookie : 브라우저에 저장될 쿠키 이름
# same_site="lax" : 다른 사이트에서 보내는 일부 쿠키 요청을 제한함.
# https_only=False : 로컬 HTTP 개발용 설정 (HTTPS 배포 환경에서는 True 검토)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY,
    session_cookie="playmate_session",
    same_site="lax",
    https_only=False,  # 로컬 개발용, 배포 시 True 검토
)


# 4. React 프론트엔드의 CORS 설정
# FRONTEND_ORIGINS 환경변수에 허용할 프론트엔드 주소를 쉼표로 구분해 저장함.
# 설정값이 없으면 로컬 Vite 개발 서버 주소를 기본값으로 사용함.
# split(",") : 쉼표 기준으로 주소 분리 / strip() : 앞뒤 공백 제거
# React 프론트엔드 CORS 설정
origins = [
    value.strip()
    for value in os.getenv("FRONTEND_ORIGINS", "").split(",")
    if value.strip()
]

# allow_origins : 요청을 허용할 프론트엔드 주소 목록
# allow_credentials=True : 쿠키 등 인증 정보가 포함된 요청 허용
# allow_methods / allow_headers : HTTP 메서드 및 요청 헤더 허용 범위
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 5. 기능별 Router 등록
# 각 Router에 작성된 API를 하나의 FastAPI 애플리케이션에 연결함.
app.include_router(auth_router)
app.include_router(board_router)
app.include_router(recruit_router)


# 6. 이미지 업로드 경로 및 정적 파일 제공 설정
# uploads 폴더가 없으면 생성함. exist_ok=True는 폴더가 이미 있어도 오류를 내지 않음.
PROJECT_ROOT.joinpath("uploads").mkdir(exist_ok=True)

# /uploads/... URL로 업로드된 파일에 접근할 수 있도록 연결함.
app.mount(
    "/uploads",
    StaticFiles(directory=PROJECT_ROOT / "uploads"),
    name="uploads",
)


# 7. RuntimeError 발생 시 공통 JSON 오류 응답 반환
# @app.exception_handler() : 지정한 예외 유형의 처리 함수를 등록함.
# RuntimeError가 발생하면 HTTP 503 상태와 오류 메시지를 반환함.
@app.exception_handler(RuntimeError)
def database_runtime_error(_, exc: RuntimeError):
    return JSONResponse(
        status_code=503,
        content={"detail": str(exc)},
    )


# 8. 기본 서버 상태 확인 API
# GET / : FastAPI 서버가 실행 중인지 간단히 확인함.
@app.get("/", tags=["health"])
def home():
    return {"message": "PlayMate API 실행 성공"}


# GET /health : 서버가 HTTP 요청에 응답하는지 확인함.
@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


# GET /health/db : PostgreSQL 연결 여부와 현재 DB 이름을 확인함.
@app.get("/health/db", tags=["health"])
def database_health():
    # db_cursor() : 데이터베이스 커서를 열고 종료 시 자원을 정리하는 기능
    with db_cursor() as cursor:
        # current_database() : 현재 연결한 PostgreSQL 데이터베이스 이름 반환
        # 1 AS connected : 연결 및 SQL 실행이 성공하는지 확인하기 위한 고정 값
        cursor.execute(
            "SELECT current_database() AS database_name, 1 AS connected"
        )
        # fetchone() : 쿼리 결과에서 한 행을 가져옴.
        row = cursor.fetchone()

    # 연결 확인에 성공하면 DB 이름을 포함한 응답을 반환함.
    return {
        "status": "ok",
        "database": row["database_name"],
    }

from backend.app.routers import mypage

app.include_router(mypage.router, prefix="/api")
