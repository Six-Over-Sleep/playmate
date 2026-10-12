from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.routers.recruit import router as recruit_router


app = FastAPI(title="Playmate API")


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(recruit_router)


@app.get("/")
def home():
    return {"message": "Playmate API 실행 성공"}