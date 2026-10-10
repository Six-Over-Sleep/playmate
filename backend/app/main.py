import os

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routers.board import router as board_router
from app.core.uploads import PROJECT_ROOT
from app.core.db_connect import db_cursor


app = FastAPI(title="PlayMate Board API", version="0.1.0")
origins = [value.strip() for value in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",") if value.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(board_router)
(PROJECT_ROOT / "uploads").mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=PROJECT_ROOT / "uploads"), name="uploads")

@app.exception_handler(RuntimeError)
def database_runtime_error(_, exc: RuntimeError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}

@app.get("/health/db", tags=["health"])
def database_health():
    with db_cursor() as cursor:
        cursor.execute("SELECT current_database() AS database_name, 1 AS connected")
        row = cursor.fetchone()
    return {"status": "ok", "database": row["database_name"]}
