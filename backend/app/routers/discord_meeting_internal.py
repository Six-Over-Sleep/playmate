"""Opt-in, HTTPS ingress only. Authenticated, one-shot Discord write approval."""
import hashlib
import hmac
import json
import logging
import os
import time
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.core.db_connect import db_cursor

router = APIRouter()
log = logging.getLogger(__name__)
APPROVAL_PATH = "/internal/discord-meeting/approve"
CREATE_ELIGIBLE = """
    SELECT p.title FROM public.recruits r JOIN public.posts p ON p.post_id=r.post_id
    JOIN public.recruit_discord_channels rc ON rc.recruit_id=r.recruit_id
    WHERE r.recruit_id=%s AND r.recruit_mode IN ('regular','short')
      AND p.post_status IS DISTINCT FROM 'DELETED' AND rc.sync_status='PENDING'
      AND rc.discord_text_channel_id IS NULL
      AND COALESCE(r.deadline_at, CASE r.recruit_mode WHEN 'regular' THEN r.regular_start_date::timestamp
            WHEN 'short' THEN date_trunc('day', r.meeting_start) END) <= clock_timestamp() AT TIME ZONE 'Asia/Seoul'
"""


def authenticate(body, stamp, signature, secret, now):
    if not stamp or not stamp.isascii() or not stamp.isdecimal() or len(stamp) != 10:
        return False
    if abs(now - int(stamp)) > 15:
        return False
    signed = b"POST /internal/discord-meeting/approve\n" + stamp.encode() + b"\n" + body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return bool(signature and signature.isascii() and hmac.compare_digest(expected, signature))


def issue_approval(job_id, nonce, grant_from):
    with db_cursor(commit=True) as cur:
        cur.execute("""
            SELECT create_owner, permission_owner,
                   result_seen_at > clock_timestamp() - interval '90 seconds' AS consumer_ready
              FROM public.discord_meeting_control WHERE singleton FOR SHARE
        """)
        control = cur.fetchone()
        if not control or not control["consumer_ready"]:
            return None
        cur.execute("""
            SELECT 1 FROM public.discord_meeting_jobs
            WHERE finished_at IS NULL AND approved_at < clock_timestamp()-interval '4 minutes'
            LIMIT 1
        """)
        if cur.fetchone():
            return None
        cur.execute("""
            SELECT *, created_at > clock_timestamp() - interval '5 minutes' AS fresh
              FROM public.discord_meeting_jobs WHERE job_id=%s FOR UPDATE
        """, (job_id,))
        job = cur.fetchone()
        if not job or not job["fresh"] or job["approved_at"] or job["finished_at"]:
            return None
        if control["create_owner" if job["kind"] == "create" else "permission_owner"] != "lambda":
            return None
        target = job["target"]
        if job["kind"] == "create":
            cur.execute(CREATE_ELIGIBLE, (job["recruit_id"],))
            current = cur.fetchone()
            if current is None:
                return None
            action = "create"
            payload = {"name": ((current["title"] or "").strip() or f"모임-{job['recruit_id']}")[:100]}
        else:
            cur.execute("""
                SELECT s.*, rc.discord_text_channel_id FROM public.discord_meeting_permission_snapshot(%s,%s) s
                JOIN public.recruit_discord_channels rc ON rc.recruit_id=%s
            """, (job["recruit_id"], job["member_id"], job["recruit_id"]))
            current = cur.fetchone()
            if (not current or current["fingerprint"] != job["fingerprint"]
                    or current["discord_id"] != target["user_id"]
                    or current["discord_text_channel_id"] != target["channel_id"]):
                return None
            action = current["desired"]
            if action == "grant":
                if os.getenv("DISCORD_MEETING_ALLOW_GRANT") != "true":
                    return None
                if not (grant_from == "absent" or (grant_from == "readonly" and current["managed"])):
                    return None
            if action == "revoke" and not current["managed"]:
                return None
            payload = {}
        cur.execute("""
            UPDATE public.discord_meeting_jobs SET approved_at=clock_timestamp(), approval_id=%s, approved_action=%s
            WHERE job_id=%s AND created_at > clock_timestamp() - interval '5 minutes'
              AND NOT EXISTS (SELECT 1 FROM public.discord_meeting_jobs WHERE approval_id=%s)
            RETURNING extract(epoch FROM approved_at)::float8 + 5 AS expires_at
        """, (nonce, action, job_id, nonce))
        issued = cur.fetchone()
        if not issued:
            return None
        return {**target, **payload, "action": action, "approval_id": nonce,
                "expires_at": issued["expires_at"]}


@router.post(APPROVAL_PATH, include_in_schema=False)
async def approve_discord_meeting(request: Request):
    secret = os.getenv("DISCORD_MEETING_APPROVAL_SECRET", "")
    if os.getenv("DISCORD_MEETING_APPROVAL_ENABLED") != "true" or len(secret) < 32:
        raise HTTPException(status_code=404)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 512:
            raise HTTPException(status_code=413)
        body.extend(chunk)
    if not authenticate(bytes(body), request.headers.get("x-meeting-time"),
                        request.headers.get("x-meeting-signature"), secret, time.time()):
        log.warning("meeting approval authentication denied")
        raise HTTPException(status_code=403)
    try:
        data = json.loads(body)
        job, nonce = data["job_id"], data["nonce"]
        if (set(data) != {"job_id", "nonce", "grant_from"}
                or data["grant_from"] not in ("disabled", "absent", "readonly")
                or str(UUID(job)) != job or str(UUID(nonce)) != nonce):
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(status_code=400) from None
    try:
        approved = await run_in_threadpool(issue_approval, job, nonce, data["grant_from"])
    except Exception as error:
        log.error("meeting approval unavailable type=%s", type(error).__name__)
        raise HTTPException(status_code=503) from None
    if approved is None:
        log.info("meeting execution not approved")
        raise HTTPException(status_code=409)
    return approved
