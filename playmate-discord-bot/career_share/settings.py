"""환경변수 설정. 기존 Gateway Bot의 config 모듈은 import하지 않는다 (DISCORD_BOT_TOKEN/GUILD_ID가 import 시점에 필요하다).

DB Lambda(VPC 안):  DB_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME DB_SSLMODE,
                    CAREER_SHARE_SEND_QUEUE_URL, PLAYMATE_WEB_BASE_URL, CAREER_SHARE_CUTOVER_AT (필수)
Worker Lambda(VPC 밖): DISCORD_BOT_TOKEN, CAREER_SHARE_CHANNEL_ID, CAREER_SHARE_RESULT_QUEUE_URL
"""
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

DEFAULTS = dict(relay_limit=20, digest_limit=5, max_attempts=3, retry_base_minutes=5, job_ttl_minutes=10,
                claim_stale_minutes=30, verify_interval_minutes=10, max_verifies=6, verify_settle_minutes=30, absent_required=2)


class SettingsError(RuntimeError):
    pass


def _int(env, name, default, minimum=1):
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    if not raw.isdigit() or int(raw) < minimum:
        raise SettingsError(f"{name}은 {minimum} 이상의 정수여야 합니다.")
    return int(raw)


def web_base_url(value, allow_local: bool = False) -> str | None:
    """http(s) 주소만. 비었거나 형식이 이상하면 None (잘못된 링크를 보내지 않는다). localhost는 운영에서 금지."""
    value = (value or "").strip().rstrip("/")
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.query or parts.fragment or parts.username:
        return None
    if parts.hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1") and not allow_local:
        return None
    return value


@dataclass(frozen=True)
class DbSettings:
    send_queue_url: str
    base_url: str
    cutover_at: datetime
    relay_limit: int
    digest_limit: int
    max_attempts: int
    retry_base_minutes: int
    job_ttl_minutes: int
    claim_stale_minutes: int
    verify_interval_minutes: int
    max_verifies: int
    verify_settle_minutes: int   # UNKNOWN이 된 뒤 첫 확인까지 기다리는 시간 (뒤늦게 처리되는 요청을 기다린다)
    absent_required: int         # 서로 다른 확인 작업에서 '마커 없음'을 이만큼 받아야 미전송으로 본다


def load_db_settings(env=None) -> DbSettings:
    env = os.environ if env is None else env
    cutover = (env.get("CAREER_SHARE_CUTOVER_AT") or "").strip()
    if not cutover:
        raise SettingsError("CAREER_SHARE_CUTOVER_AT(컷오버 시각, 예: 2026-12-01T00:00:00+09:00)이 없으면 실행하지 않습니다 (과거 글 대량 공유 방지).")
    try:
        cutover_at = datetime.fromisoformat(cutover)
    except ValueError as error:
        raise SettingsError("CAREER_SHARE_CUTOVER_AT 형식 오류") from error
    if cutover_at.tzinfo is None:
        raise SettingsError("CAREER_SHARE_CUTOVER_AT에는 시간대(+09:00 등)가 필요합니다.")
    queue = (env.get("CAREER_SHARE_SEND_QUEUE_URL") or "").strip()
    if not queue:
        raise SettingsError("CAREER_SHARE_SEND_QUEUE_URL이 없습니다.")
    base = web_base_url(env.get("PLAYMATE_WEB_BASE_URL"), allow_local=env.get("CAREER_SHARE_ALLOW_LOCAL") == "1")
    values = {key: _int(env, "CAREER_SHARE_" + key.upper(), default) for key, default in DEFAULTS.items()}
    if values["digest_limit"] > 5:
        raise SettingsError("묶음 공유는 최대 5건입니다.")
    if values["max_verifies"] < values["absent_required"] + 1:
        raise SettingsError("max_verifies는 absent_required보다 커야 합니다.")
    if values["claim_stale_minutes"] <= values["job_ttl_minutes"]:
        raise SettingsError("claim_stale_minutes는 job_ttl_minutes보다 커야 합니다 (뒤늦은 발송 방지).")
    return DbSettings(send_queue_url=queue, base_url=base or "", cutover_at=cutover_at.astimezone(timezone.utc), **values)
