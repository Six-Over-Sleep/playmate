"""Discord OAuth2 로그인, 회원 상태, 로그아웃, 추가 회원가입 API."""

import logging
import secrets
from urllib.parse import urlencode

import httpx
import psycopg2
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse

from app.core.config import (
    DISCORD_CLIENT_ID,
    DISCORD_REDIRECT_URI,
    FRONTEND_URL,
)
from app.schemas.member import MemberSignup
from app.services.auth_service import exchange_code_for_token, get_discord_user
from app.services.member_service import get_member, register_member

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])

# db_cursor()는 psycopg2 기반이고 연결 대기 실패는 RuntimeError로 발생한다.
DB_ERRORS = (psycopg2.Error, RuntimeError)


@router.get("/discord/login")
async def discord_login(request: Request):
    """Discord OAuth2 인증 페이지로 이동한다."""
    request.session.clear()
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state
    params = {
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify",
        "state": state,
    }
    return RedirectResponse(
        url="https://discord.com/oauth2/authorize?" + urlencode(params),
        status_code=302,
    )


@router.get("/discord/callback")
async def discord_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """Discord 인증 정보를 확인하고 회원 세션을 발급한다."""
    if error:
        raise HTTPException(status_code=400, detail="Discord 인증이 취소되거나 실패했습니다.")

    saved_state = request.session.pop("oauth_state", None)
    if not saved_state or not state or not secrets.compare_digest(saved_state, state):
        raise HTTPException(status_code=400, detail="유효하지 않은 OAuth 인증 요청입니다.")

    if not code:
        raise HTTPException(status_code=400, detail="Discord 인증 코드가 없습니다.")

    try:
        access_token = await exchange_code_for_token(code)
        discord_user = await get_discord_user(access_token)
        discord_id = str(discord_user["id"])
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.exception("Discord OAuth 처리 중 오류 발생")
        raise HTTPException(status_code=502, detail="Discord 인증 처리에 실패했습니다.") from exc

    try:
        member = await run_in_threadpool(get_member, discord_id)
    except DB_ERRORS as exc:
        logger.exception("로그인 회원 DB 조회 중 오류 발생")
        raise HTTPException(status_code=503, detail="회원 DB 조회에 실패했습니다.") from exc

    request.session.clear()
    request.session["user"] = {
        "discord_id": discord_id,
        "username": discord_user["username"],
        "avatar": discord_user.get("avatar"),
    }
    if member:
        request.session["member_id"] = member["member_id"]
        return RedirectResponse(url=f"{FRONTEND_URL}/?auth=success", status_code=302)

    return RedirectResponse(url=f"{FRONTEND_URL}/?signup=required", status_code=302)


@router.get("/me")
async def get_current_user(request: Request):
    """로그인 상태를 확인하고 Discord 사용자 및 PLAYMATE 회원 정보를 반환한다."""
    discord_user = request.session.get("user")
    if not discord_user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    try:
        member = await run_in_threadpool(get_member, discord_user["discord_id"])
    except DB_ERRORS as exc:
        logger.exception("회원 정보 조회 실패")
        raise HTTPException(status_code=503, detail="회원 정보를 조회하지 못했습니다.") from exc

    if member is None:
        request.session.pop("member_id", None)
        return {
            "authenticated": True,
            "signup_required": True,
            "discord_user": discord_user,
            "member": None,
        }

    request.session["member_id"] = member["member_id"]
    avatar_hash = discord_user.get("avatar")
    avatar_url = None
    if avatar_hash:
        ext = "gif" if avatar_hash.startswith("a_") else "png"
        avatar_url = (
            f"https://cdn.discordapp.com/avatars/"
            f"{discord_user['discord_id']}/{avatar_hash}.{ext}"
        )

    return {
        "authenticated": True,
        "signup_required": False,
        "discord_user": {**discord_user, "avatar_url": avatar_url},
        "member_id": member["member_id"],
        "member": member,
    }


@router.post("/logout")
async def logout(request: Request):
    """로그인 세션을 종료한다."""
    request.session.clear()
    return {"message": "로그아웃 완료"}


@router.post("/signup", status_code=201)
def signup(request: Request, signup_data: MemberSignup):
    """Discord 인증을 받은 사용자에게 PLAYMATE 회원 정보를 등록한다."""
    discord_user = request.session.get("user")
    if not discord_user:
        raise HTTPException(status_code=401, detail="Discord 로그인이 필요합니다.")

    discord_id = discord_user["discord_id"]
    try:
        existing_member = get_member(discord_id)
    except DB_ERRORS as exc:
        logger.exception("회원 DB 조회 중 오류 발생")
        raise HTTPException(status_code=503, detail="회원 DB 조회에 실패했습니다.") from exc

    if existing_member:
        request.session["member_id"] = existing_member["member_id"]
        raise HTTPException(status_code=409, detail="이미 가입된 회원입니다.")

    try:
        member = register_member(discord_id, signup_data)
    except psycopg2.IntegrityError as exc:
        logger.warning("중복 또는 제약조건 위반으로 회원가입 실패")
        raise HTTPException(
            status_code=409,
            detail="중복 또는 DB 제약조건 위반으로 회원가입에 실패했습니다.",
        ) from exc
    except DB_ERRORS as exc:
        logger.exception("회원 DB 저장 중 오류 발생")
        raise HTTPException(status_code=503, detail="회원정보 저장에 실패했습니다.") from exc

    request.session["member_id"] = member["member_id"]
    return {
        "message": "회원가입 완료!",
        "signup_required": False,
        "member": member,
    }
