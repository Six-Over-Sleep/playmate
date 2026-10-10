from fastapi import FastAPI
from backend.app.routers.recruit import router as recruit_router

app = FastAPI(title="Playmate API")

app.include_router(recruit_router)

@app.get("/")
def home():
    return {"message": "Playmate API 실행 성공"}