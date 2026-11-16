"""Discord OAuth2 로그인, 회원 상태, 로그아웃, 추가 회원가입 API."""

import logging
import secrets
from urllib.parse import urlencode

import httpx
import psycopg2
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse

from app.core.config import DISCORD_CLIENT_ID, DISCORD_REDIRECT_URI, FRONTEND_URL
from app.schemas.member import MemberSignup
from app.services.auth_service import exchange_code_for_token, get_discord_user
from app.services.member_service import (
    get_education_options,
    get_member,
    register_member,
    sync_member_avatar,
    withdraw_member,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])
DB_ERRORS = (psycopg2.Error, RuntimeError)


@router.get("/discord/login")
async def discord_login(request: Request):
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
    discord_user = request.session.get("user")
    if not discord_user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    try:
        member = await run_in_threadpool(get_member, discord_user["discord_id"])
    except DB_ERRORS as exc:
        logger.exception("회원 정보 조회 실패")
        raise HTTPException(status_code=503, detail="회원 정보를 조회하지 못했습니다.") from exc

    if member is None:
        if request.session.get("member_id") is not None:
            request.session.clear()
            raise HTTPException(status_code=401, detail="로그인 세션이 만료되었습니다.")
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

    if "profile_image_url" in member and member["profile_image_url"] != avatar_url:
        try:
            await run_in_threadpool(sync_member_avatar, member["member_id"], avatar_url)
        except DB_ERRORS:
            logger.warning("Discord 프로필 사진 동기화 실패", exc_info=True)

    return {
        "authenticated": True,
        "signup_required": False,
        "discord_user": {**discord_user, "avatar_url": avatar_url},
        "member_id": member["member_id"],
        "member": member,
    }


@router.get("/education-options")
async def education_options(request: Request):
    """Discord OAuth 인증 이후 등록된 교육기관/과정/기수만 조회합니다."""
    user = request.session.get("user")
    if not isinstance(user, dict) or not user.get("discord_id"):
        raise HTTPException(status_code=401, detail="Discord 로그인이 필요합니다.")
    try:
        cohorts = await run_in_threadpool(get_education_options)
    except DB_ERRORS as exc:
        logger.exception("교육과정 목록 조회 실패")
        raise HTTPException(status_code=503, detail="교육과정 목록을 조회하지 못했습니다.") from exc
    return {"cohorts": cohorts}


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"message": "로그아웃 완료"}


@router.post("/signup", status_code=201)
def signup(request: Request, signup_data: MemberSignup):
    discord_user = request.session.get("user")
    if not isinstance(discord_user, dict) or not discord_user.get("discord_id"):
        raise HTTPException(status_code=401, detail="Discord 로그인이 필요합니다.")

    discord_id = str(discord_user["discord_id"])
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
        logger.warning("중복 또는 DB 제약조건 위반으로 회원가입 실패")
        raise HTTPException(
            status_code=409,
            detail="중복 또는 DB 제약조건 위반으로 회원가입에 실패했습니다.",
        ) from exc
    except DB_ERRORS as exc:
        logger.exception("회원 DB 저장 중 오류 발생")
        raise HTTPException(status_code=503, detail="회원정보 저장에 실패했습니다.") from exc

    request.session["member_id"] = member["member_id"]
    return {"message": "회원가입 완료!", "signup_required": False, "member": member}


@router.delete("/withdraw")
async def withdraw_account(request: Request):
    member_id = request.session.get("member_id")
    discord_user = request.session.get("user")
    if (
        type(member_id) is not int
        or not isinstance(discord_user, dict)
        or not discord_user.get("discord_id")
    ):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    try:
        success = await run_in_threadpool(
            withdraw_member, member_id, str(discord_user["discord_id"])
        )
    except DB_ERRORS as exc:
        logger.exception("회원 탈퇴 처리 실패")
        raise HTTPException(status_code=503, detail="회원 탈퇴에 실패했습니다.") from exc

    if not success:
        raise HTTPException(status_code=404, detail="탈퇴 가능한 회원을 찾을 수 없습니다.")
    request.session.clear()
    return {"message": "회원 탈퇴가 완료되었습니다."}
