"""DM Lambda 환경변수 (DM_SHARE_*). 취업·HOT 공유와 큐를 공유하지 않는다.

DB Lambda(VPC 안):  DB_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME DB_SSLMODE, DM_SHARE_SEND_QUEUE_URL (필수),
                    PLAYMATE_WEB_BASE_URL (선택: 없으면 기존 Gateway처럼 링크 없이 보낸다)
Worker Lambda(VPC 밖): DISCORD_BOT_TOKEN, DM_SHARE_RESULT_QUEUE_URL   (채널은 작업의 받는 사람 DM 채널이다)

재시도 간격 60초·최대 3회는 기존 Gateway(config.NOTIFICATION_RETRY_DELAY_SECONDS / NOTIFICATION_MAX_ATTEMPTS)와 같다.
작업 TTL 50초 (R4): 재시도 간격(60초)보다 짧아야 한다. 같은 작업의 SQS 복사본이 재선점 이후 처음 발송을 시작하지 못하게 하는 조건이다.
이미 시작된 HTTP 요청(429 대기 포함)은 TTL로 막지 못하므로 Gateway의 Lambda 행 인수는 16분 제한으로 따로 막는다(dm_delivery_repository).
TTL은 선점 후 알림 OFF·탈퇴된 알림이 큐에서 뒤늦게 발송될 수 있는 시간의 하한이기도 하다 (없애지는 못한다).
"""
import os
from dataclasses import dataclass

from career_share.settings import SettingsError, _int, web_base_url

DEFAULTS = dict(relay_limit=20, job_ttl_seconds=50, claim_stale_minutes=10, retry_seconds=60, max_attempts=3,
                verify_interval_minutes=10, max_verifies=6, verify_settle_minutes=30, absent_required=2)
OTHER_QUEUES = ("CAREER_SHARE_SEND_QUEUE_URL", "HOT_SHARE_SEND_QUEUE_URL")
# 표준 큐 우회(DM_SHARE_ALLOW_STANDARD_QUEUE=1)를 허용하는 비운영 환경 (PLAYMATE_ENVIRONMENT, 대소문자 무시).
# prod·production·값 없음·그 밖의 값은 모두 거부한다 (허용 목록 방식).
STANDARD_QUEUE_ENVIRONMENTS = ("local", "test")


def standard_queue_allowed(env) -> bool:
    """FIFO가 아닌 DM 발송 큐를 쓸 수 있는가: 명시적 허용(=1)과 허용된 비운영 환경이 둘 다 있어야 한다."""
    environment = (env.get("PLAYMATE_ENVIRONMENT") or "").strip().lower()
    return env.get("DM_SHARE_ALLOW_STANDARD_QUEUE") == "1" and environment in STANDARD_QUEUE_ENVIRONMENTS


@dataclass(frozen=True)
class DmSettings:
    send_queue_url: str
    base_url: str
    relay_limit: int
    job_ttl_seconds: int
    claim_stale_minutes: int
    retry_seconds: int
    max_attempts: int
    verify_interval_minutes: int
    max_verifies: int
    verify_settle_minutes: int
    absent_required: int
    retry_base_minutes: int | None = None   # CareerShareService 호환용 (DM은 retry_seconds를 쓴다)


def load_dm_settings(env=None) -> DmSettings:
    env = os.environ if env is None else env
    queue = (env.get("DM_SHARE_SEND_QUEUE_URL") or "").strip()
    if not queue:
        raise SettingsError("DM_SHARE_SEND_QUEUE_URL이 없습니다.")
    if any(queue == (env.get(name) or "").strip() for name in OTHER_QUEUES):
        raise SettingsError("DM 발송 큐가 취업·HOT 공유 발송 큐와 같습니다 (분리해야 함).")
    if not queue.endswith(".fifo") and not standard_queue_allowed(env):
        # DM Worker 동시성 2는 알림 단위 FIFO 그룹 직렬화를 전제로 한다 (Issue #182). 표준 큐면 R4 중복 방지가 깨진다.
        # 운영(prod/production)·환경 미지정·알 수 없는 환경에서는 우회 플래그가 있어도 거부한다.
        raise SettingsError("DM_SHARE_SEND_QUEUE_URL은 FIFO 큐(.fifo)여야 합니다 "
                            "(표준 큐는 PLAYMATE_ENVIRONMENT=local/test + DM_SHARE_ALLOW_STANDARD_QUEUE=1일 때만).")
    base = web_base_url(env.get("PLAYMATE_WEB_BASE_URL"), allow_local=env.get("DM_SHARE_ALLOW_LOCAL") == "1")
    values = {key: _int(env, "DM_SHARE_" + key.upper(), default) for key, default in DEFAULTS.items()}
    if values["max_verifies"] < values["absent_required"] + 1:
        raise SettingsError("max_verifies는 absent_required보다 커야 합니다.")
    if values["job_ttl_seconds"] >= values["retry_seconds"]:
        raise SettingsError("job_ttl_seconds는 retry_seconds보다 짧아야 합니다 (재선점 뒤 이전 작업 발송 방지).")
    if values["claim_stale_minutes"] * 60 <= values["job_ttl_seconds"]:
        raise SettingsError("claim_stale_minutes는 job_ttl_seconds보다 길어야 합니다 (뒤늦은 발송 방지).")
    return DmSettings(send_queue_url=queue, base_url=base or "", **values)
