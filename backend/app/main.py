import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# Support both `uvicorn app.main:app` from backend/ and
# `uvicorn backend.app.main:app` from the repository root.
BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT_PATH = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(PROJECT_ROOT_PATH) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_PATH))

from app.core.uploads import PROJECT_ROOT  # noqa: E402
from app.core.db_connect import db_cursor  # noqa: E402
from app.routers.board import router as board_router  # noqa: E402
from backend.app.routers.recruit import router as recruit_router  # noqa: E402


app = FastAPI(title="PlayMate API", version="0.1.0")
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

app.include_router(board_router)
app.include_router(recruit_router)
PROJECT_ROOT.joinpath("uploads").mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=PROJECT_ROOT / "uploads"), name="uploads")


@app.exception_handler(RuntimeError)
def database_runtime_error(_, exc: RuntimeError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/", tags=["health"])
def home():
    return {"message": "PlayMate API 실행 성공"}


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


@app.get("/health/db", tags=["health"])
def database_health():
    with db_cursor() as cursor:
        cursor.execute("SELECT current_database() AS database_name, 1 AS connected")
        row = cursor.fetchone()
    return {"status": "ok", "database": row["database_name"]}
