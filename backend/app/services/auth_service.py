
# Discord OAuth2 인증 및 사용자 정보 조회를 담당하는 Service
# Router에서 전달받은 인증 코드를 처리하고 Discord API와 통신함.
import httpx

# Discord 인증에 필요한 설정값을 config.py에서 가져옴.
from app.core.config import (
    DISCORD_CLIENT_ID,       # Discord 애플리케이션 식별 번호
    DISCORD_CLIENT_SECRET,   # Discord 애플리케이션 비밀키
    DISCORD_REDIRECT_URI,    # 인증 완료 후 돌아올 콜백 주소
    DISCORD_API_URL,         # Discord API 기본 주소
)


# 1. Discord 인증 코드를 Access Token으로 교환
async def exchange_code_for_token(code: str) -> str:

    # Discord OAuth2 토큰 발급 API 주소
    url = f"{DISCORD_API_URL}/oauth2/token"

    # 토큰 발급 요청에 전달할 데이터
    # grant_type : 인증 코드로 토큰을 발급받는 방식
    # code : Discord 로그인 후 발급받은 인증 코드
    # redirect_uri : 인증 완료 후 돌아올 주소
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": DISCORD_REDIRECT_URI,
    }

    # Discord 애플리케이션 인증에 사용할 Client ID와 Secret
    auth = (
        DISCORD_CLIENT_ID,
        DISCORD_CLIENT_SECRET,
    )

    # AsyncClient : 비동기 HTTP 요청을 처리하는 객체
    # timeout=10.0 : HTTP 요청 시간 제한 설정
    # async with : 요청 종료 후 연결 자원을 자동 정리함.
    async with httpx.AsyncClient(timeout=10.0) as client:

        # POST 요청으로 인증 코드를 전달하고 토큰 발급을 요청함.
        response = await client.post(
            url,
            data=data,
            auth=auth,
        )

        # HTTP 오류 응답(4xx, 5xx)이면 예외 발생
        response.raise_for_status()

        # JSON 응답을 Python 딕셔너리로 변환
        token_data = response.json()

    # 발급받은 Access Token 반환
    return token_data["access_token"]


# 2. Access Token으로 Discord 사용자 정보 조회
async def get_discord_user(access_token: str) -> dict:

    # 현재 인증된 Discord 사용자 정보 조회 API 주소
    url = f"{DISCORD_API_URL}/users/@me"

    # Authorization : API 요청에 사용할 인증 정보
    # Bearer : Access Token을 전달하는 인증 방식
    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    # Discord API에 비동기 GET 요청 전송
    async with httpx.AsyncClient(timeout=10.0) as client:

        # Access Token을 이용하여 Discord 사용자 정보 요청
        response = await client.get(
            url,
            headers=headers,
        )

        # HTTP 오류 응답이면 예외 발생
        response.raise_for_status()

        # JSON 응답을 Python 딕셔너리로 변환
        user_data = response.json()

    # Discord 사용자 정보(id, username, avatar 등) 반환
    return user_data
