"""HOT 공유 환경변수 (HOT_SHARE_*). 취업 공유(CAREER_SHARE_*)와 큐·채널·한도를 공유하지 않는다.

DB Lambda(VPC 안):  DB_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME DB_SSLMODE,
                    HOT_SHARE_SEND_QUEUE_URL, PLAYMATE_WEB_BASE_URL, HOT_SHARE_DB_TIMEZONE (필수)
Worker Lambda(VPC 밖): DISCORD_BOT_TOKEN, HOT_SHARE_CHANNEL_ID(기존 🔥│핫플레이메이트), HOT_SHARE_RESULT_QUEUE_URL

HOT_SHARE_DB_TIMEZONE: 웹(backend)이 운영 DB에 접속할 때의 세션 TimeZone. post_reactions.created_at(naive)이 이 시간대로
저장·비교되므로 웹과 같은 7일 경계를 쓰려면 반드시 같아야 한다. backend는 TimeZone을 지정하지 않으므로 서버/계정 기본값이다.
운영 DB에서 backend 계정으로 `SHOW TimeZone;`을 실행해 확인한 값을 넣는다 (기본값을 두지 않는다).
"""
import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from career_share.settings import SettingsError, _int, web_base_url

# job_ttl은 #163(10분)보다 짧게 둔다: 선점 후 삭제된 글이 뒤늦게 게시될 수 있는 최대 시간을 줄인다 (없애지는 못한다).
DEFAULTS = dict(relay_limit=10, max_attempts=3, retry_base_minutes=5, job_ttl_minutes=3, claim_stale_minutes=15,
                verify_interval_minutes=10, max_verifies=6, verify_settle_minutes=30, absent_required=2)


@dataclass(frozen=True)
class HotSettings:
    """CareerShareService가 읽는 이름(send_queue_url, base_url, job_ttl_minutes, ...)을 그대로 쓴다."""
    send_queue_url: str
    base_url: str
    db_timezone: str
    relay_limit: int
    max_attempts: int
    retry_base_minutes: int
    job_ttl_minutes: int
    claim_stale_minutes: int
    verify_interval_minutes: int
    max_verifies: int
    verify_settle_minutes: int
    absent_required: int


def check_timezone(name: str) -> str:
    """IANA 이름만 허용한다. 일광절약 시간이 있는 시간대는 7일 경계 변환이 1시간 어긋날 수 있어 거부한다."""
    name = (name or "").strip()
    if not name:
        raise SettingsError("HOT_SHARE_DB_TIMEZONE(웹 DB 세션 시간대, 예: UTC)이 없으면 실행하지 않습니다 (7일 경계 불일치 방지).")
    try:
        zone = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise SettingsError("HOT_SHARE_DB_TIMEZONE 형식 오류") from error
    from datetime import datetime
    offsets = {zone.utcoffset(datetime(2026, month, 1)) for month in range(1, 13)}
    if len(offsets) != 1:
        raise SettingsError("일광절약 시간이 있는 시간대는 지원하지 않습니다 (7일 경계 변환이 어긋날 수 있음).")
    return name


def load_hot_settings(env=None) -> HotSettings:
    env = os.environ if env is None else env
    queue = (env.get("HOT_SHARE_SEND_QUEUE_URL") or "").strip()
    if not queue:
        raise SettingsError("HOT_SHARE_SEND_QUEUE_URL이 없습니다.")
    if queue == (env.get("CAREER_SHARE_SEND_QUEUE_URL") or "").strip():
        raise SettingsError("HOT 발송 큐가 취업 공유 발송 큐와 같습니다 (취업 채널로 게시되는 것을 막기 위해 분리해야 함).")
    tz = check_timezone(env.get("HOT_SHARE_DB_TIMEZONE"))
    base = web_base_url(env.get("PLAYMATE_WEB_BASE_URL"), allow_local=env.get("HOT_SHARE_ALLOW_LOCAL") == "1")
    values = {key: _int(env, "HOT_SHARE_" + key.upper(), default) for key, default in DEFAULTS.items()}
    if values["max_verifies"] < values["absent_required"] + 1:
        raise SettingsError("max_verifies는 absent_required보다 커야 합니다.")
    if values["claim_stale_minutes"] <= values["job_ttl_minutes"]:
        raise SettingsError("claim_stale_minutes는 job_ttl_minutes보다 커야 합니다 (뒤늦은 발송 방지).")
    return HotSettings(send_queue_url=queue, base_url=base or "", db_timezone=tz, **values)
