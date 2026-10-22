# Discord OAuth2 로그인, 로그인 상태 확인, 로그아웃 및 회원가입 API를 관리하는 Router
import logging  # 서버에서 발생한 오류와 경고를 기록하는 표준 라이브러리
import secrets  # 예측하기 어려운 OAuth2 state 값 생성 및 안전한 문자열 비교에 사용
from urllib.parse import urlencode  # Discord 인증 URL에 필요한 쿼리 파라미터를 구성

import httpx  # Discord API와의 HTTP 통신에서 발생하는 오류 처리에 사용
import psycopg  # PostgreSQL 조회 및 저장 중 발생하는 DB 오류 처리에 사용

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool  # 동기 DB 함수를 별도 스레드에서 실행
from fastapi.responses import RedirectResponse  # 브라우저를 다른 URL로 이동시킬 때 사용

# 환경 설정에서 Discord OAuth2 정보와 프론트엔드 주소를 가져옴
from app.core.config import (
    DISCORD_CLIENT_ID,
    DISCORD_REDIRECT_URI,
    FRONTEND_URL,
)

# Discord 인증 코드를 Access Token으로 교환하고 Discord 사용자 정보를 조회하는 Service
from app.services.auth_service import (
    exchange_code_for_token,
    get_discord_user,
)

# 추가 회원가입 시 요청 데이터의 형식을 검증하는 스키마
from app.schemas.member import MemberSignup

# DB에서 기존 회원을 조회하거나 신규 회원을 등록하는 Service
from app.services.member_service import (
    get_member,
    register_member,
)


# 현재 파일의 실행 정보 및 예외를 기록할 로거 생성
logger = logging.getLogger(__name__)

# 이 Router에 등록된 API는 모두 /auth 경로로 시작함
router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


# =========================================================
# 1. Discord 로그인 시작 (GET /auth/discord/login)
# =========================================================
@router.get("/discord/login")
async def discord_login(request: Request):

    # 이전 세션 정보 초기화 (기존 로그인 정보 및 임시 인증 정보 제거)
    request.session.clear()

    # OAuth2 CSRF 방지용 state 생성
    # Discord에서 돌아온 state와 세션에 저장한 값을 비교할 예정임
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state

    # Discord에 전달할 OAuth2 인증 요청 정보
    # scope="identify" : Discord 사용자 기본 정보 조회 권한
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify",
        "state": state,
    }

    # 딕셔너리의 인증 파라미터를 URL 쿼리 문자열로 변환
    discord_url = (
        "https://discord.com/oauth2/authorize?"
        + urlencode(params)
    )

    # HTTP 302 : 브라우저를 Discord 로그인/동의 화면으로 이동시킴
    return RedirectResponse(
        url=discord_url,
        status_code=302,
    )


# =========================================================
# 2. Discord 인증 완료 후 처리 (GET /auth/discord/callback)
# =========================================================
@router.get("/discord/callback")
async def discord_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):

    # Discord에서 error를 전달하면 인증 취소 또는 실패로 처리함
    if error:
        raise HTTPException(
            status_code=400,
            detail="Discord 인증이 취소되거나 실패했습니다.",
        )

    # OAuth2 state 검증
    # pop() : 세션에 저장된 값을 가져오면서 제거해 재사용하지 않도록 함
    saved_state = request.session.pop(
        "oauth_state",
        None,
    )

    # compare_digest() : state 문자열을 안전하게 비교하는 함수
    # 유효하지 않은 요청이면 HTTP 400 오류 반환
    if (
        not saved_state
        or not state
        or not secrets.compare_digest(saved_state, state)
    ):
        raise HTTPException(
            status_code=400,
            detail="유효하지 않은 OAuth 인증 요청입니다.",
        )

    # Discord가 발급한 일회성 인증 코드가 전달됐는지 확인
    if not code:
        raise HTTPException(
            status_code=400,
            detail="Discord 인증 코드가 없습니다.",
        )

    # Discord Access Token 및 사용자 정보 조회
    try:
        # 인증 코드를 Access Token으로 교환함
        access_token = await exchange_code_for_token(code)
        # Access Token으로 Discord 사용자 프로필을 조회함
        discord_user = await get_discord_user(access_token)

        # Discord 사용자 ID를 문자열로 통일하여 사용함
        discord_id = str(discord_user["id"])

    # 외부 HTTP 요청 실패 또는 응답 데이터 문제를 처리함
    except (httpx.HTTPError, KeyError, ValueError):
        logger.exception("Discord OAuth 처리 중 오류 발생")

        # HTTP 502 : 외부 인증 서비스 처리 실패
        raise HTTPException(
            status_code=502,
            detail="Discord 인증 처리에 실패했습니다.",
        )

    # PostgreSQL에서 기존 회원 조회
    try:
        # get_member()는 동기 함수이므로 스레드풀에서 실행해 이벤트 루프 차단을 줄임
        member = await run_in_threadpool(
            get_member,
            discord_id,
        )

    # PostgreSQL 연결 또는 조회 오류 처리
    except psycopg.Error:
        logger.exception("회원 DB 조회 중 오류 발생")

        # HTTP 503 : DB 서비스 이용 불가
        raise HTTPException(
            status_code=503,
            detail="회원 DB 조회에 실패했습니다.",
        )

    # 인증된 Discord 사용자 정보 저장
    # 기존 세션을 비우고 이번 인증에 필요한 정보만 새로 기록함
    request.session.clear()

    request.session["user"] = {
        "discord_id": discord_id,
        "username": discord_user["username"],
        "avatar": discord_user.get("avatar"),
    }

    # 기존 회원인 경우
    if member:
        # PLAYMATE 내부 회원 번호를 로그인 세션에 저장함
        request.session["member_id"] = member["member_id"]

        # 로그인 성공을 알리는 쿼리 파라미터와 함께 홈으로 이동
        return RedirectResponse(
            url=f"{FRONTEND_URL}/?auth=success",
            status_code=302,
        )

    # 신규 회원인 경우 : Discord 인증은 완료했지만 추가 회원가입이 필요함
    return RedirectResponse(
        url=f"{FRONTEND_URL}/?signup=required",
        status_code=302,
    )


# =========================================================
# 3. 현재 로그인 및 회원가입 상태 확인 (GET /auth/me)
# =========================================================
@router.get("/me")
async def get_current_user(request: Request):

    # 현재 세션에서 Discord 사용자 정보를 가져옴
    discord_user = request.session.get("user")

    # Discord 인증도 하지 않은 경우
    if not discord_user:
        # HTTP 401 : 로그인이 필요한 요청
        raise HTTPException(
            status_code=401,
            detail="로그인이 필요합니다.",
        )

    # 세션의 member_id만 신뢰하지 않고 Discord ID로 DB의 실제 가입 여부를 다시 확인함
    try:
        member = await run_in_threadpool(
            get_member,
            discord_user["discord_id"],
        )
    except psycopg.Error as exc:
        logger.exception("회원 정보 조회 실패")
        # from exc : 원래 발생한 DB 예외를 연결하여 오류 원인 추적을 도움
        raise HTTPException(
            status_code=503,
            detail="회원 정보를 조회하지 못했습니다.",
        ) from exc

    # Discord 인증은 되었지만 PLAYMATE 회원가입을 아직 하지 않은 경우
    if member is None:
        # 남아 있을 수 있는 이전 회원 번호를 세션에서 제거함
        request.session.pop("member_id", None)
        return {
            "authenticated": True,
            "signup_required": True,
            "discord_user": discord_user,
            "member": None,
        }

    # 가입된 회원이면 DB에서 확인한 member_id를 세션에 갱신함
    request.session["member_id"] = member["member_id"]

    # Discord 아바타 정보가 있을 때 프로필 이미지 URL을 구성함
    avatar_hash = discord_user.get("avatar")
    avatar_url = None
    if avatar_hash:
        # 애니메이션 아바타(a_로 시작)는 GIF, 일반 아바타는 PNG로 표시함
        extension = "gif" if avatar_hash.startswith("a_") else "png"
        avatar_url = (
            f"https://cdn.discordapp.com/avatars/"
            f"{discord_user['discord_id']}/{avatar_hash}.{extension}"
        )

    # 프론트엔드에 인증 여부, Discord 프로필, 회원 정보를 JSON으로 반환함
    return {
        "authenticated": True,
        "signup_required": False,
        "discord_user": {**discord_user, "avatar_url": avatar_url},
        "member_id": member["member_id"],  # 기존 API 응답과 호환
        "member": member,
    }


# =========================================================
# 4. 로그아웃 (POST /auth/logout)
# =========================================================
@router.post("/logout")
async def logout(request: Request):

    # 현재 세션에서 로그인 및 인증 관련 정보를 모두 제거함
    request.session.clear()

    return {
        "message": "로그아웃 완료",
    }


# =========================================================
# 5. Discord 인증 후 추가 회원가입 (POST /auth/signup)
# =========================================================
@router.post("/signup", status_code=201)
def signup(
    request: Request,
    signup_data: MemberSignup,
):

    # Discord 인증 여부 확인
    discord_user = request.session.get("user")

    if not discord_user:
        raise HTTPException(
            status_code=401,
            detail="Discord 로그인이 필요합니다.",
        )

    # Discord ID를 기존 회원 조회 및 신규 가입에 사용함
    discord_id = discord_user["discord_id"]

    # 기존 회원 조회
    try:
        existing_member = get_member(discord_id)

    except psycopg.Error:
        logger.exception("회원 DB 조회 중 오류 발생")

        raise HTTPException(
            status_code=503,
            detail="회원 DB 조회에 실패했습니다.",
        )

    # 이미 가입된 회원이라면 중복 가입 방지
    if existing_member:
        request.session["member_id"] = existing_member["member_id"]

        # HTTP 409 : 기존 데이터와 충돌하는 요청
        raise HTTPException(
            status_code=409,
            detail="이미 가입된 회원입니다.",
        )

    # 신규 회원 DB 등록
    try:
        member = register_member(
            discord_id,
            signup_data,
        )

    # 유니크 제약조건 등 DB 무결성 제약 위반을 처리함
    except psycopg.IntegrityError:
        logger.warning("중복 또는 제약조건 위반으로 회원가입 실패")

        raise HTTPException(
            status_code=409,
            detail="중복 또는 DB 제약조건 위반으로 회원가입에 실패했습니다.",
        )

    # 그 밖의 PostgreSQL 오류 처리
    except psycopg.Error:
        logger.exception("회원 DB 저장 중 오류 발생")

        raise HTTPException(
            status_code=503,
            detail="회원정보 저장에 실패했습니다.",
        )

    # PLAYMATE 회원 ID를 로그인 세션에 추가
    request.session["member_id"] = member["member_id"]

    # HTTP 201 : 회원가입 성공 후 생성된 회원 정보를 반환함
    return {
        "message": "회원가입 완료!",
        "signup_required": False,
        "member": member,
    }
