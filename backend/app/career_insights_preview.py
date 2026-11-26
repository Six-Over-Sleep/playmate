"""DB-independent local preview server for the career insights dashboard."""
from fastapi import FastAPI

from backend.app.routers.career_insights import router

app = FastAPI(title='Playmate Career Insights Preview')
app.include_router(router)
