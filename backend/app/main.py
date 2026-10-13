
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
# **Middleware(미들웨어)**는 사용자의 요청이 실제 API 함수에 전달되기 전이나, 
# #처리 결과가 사용자에게 돌아갈 때 공통 작업을 수행하는 장치

from app.core.config import SESSION_SECRET_KEY
from app.routers.auth import router as auth_router

# 1. FastAPI 애플리케이션 생성
app = FastAPI(title="PlayMate API")
    #title: FastAPI가 자동으로 만들어 주는 Swagger UI 기반 API 문서

# 2. 로그인 세션 관리 설정
app.add_middleware(   # .add_middleware -> FastAPI 앱에 미들웨어를 추가하는 메서드
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY, # 쿠키가 임의로 조작됐는지 검증하는 데 사용할 비밀키
    session_cookie="playmate_session", # 브라우저에 저장될 쿠키 이름 지정
    same_site="lax", # 다른 사이트에서 오는 요청에 쿠키를 보내는 상황을 제한
    https_only=False,  # 로컬 개발용 -> 실제 배포 시 True로 바꿈
)

# 3. Discord 로그인 라우터 등록
app.include_router(auth_router)

# 4. 서버 동작 확인용 API
@app.get("/")
async def home():
    return {"message": "PlayMate API 실행 중"}
