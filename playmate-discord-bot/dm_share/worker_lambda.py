"""DM Worker Lambda (VPC 밖, DB 접근 없음). career_share의 Worker 로직(마커 확인·발송·결과 불명 처리)을 DM 채널에 적용한다.

다른 점
  * 채널: 작업의 recipient_id로 DM 채널을 연다 (POST /users/@me/channels, 멱등). 마커 확인도 그 DM 채널에서 한다.
  * DM 작업(kind=DM, unit_id=dm-<id>)만 처리한다. 다른 작업은 Discord 호출 전에 ContractError -> DLQ.
  * 오류 분류 (결과에 error_code를 담는다):
      50007(DM 차단)            FAILED_PERMANENT -> DB가 즉시 FAILED
      10013/50033(사용자 없음)  FAILED_PERMANENT -> DB가 SKIPPED("Discord 사용자 없음")
      429, 그 밖의 4xx·전송 전 실패  FAILED_RETRY -> DB가 retry_count + 1, 60초 뒤 재시도 (3회째 FAILED)
      5xx·타임아웃(결과 불명)    마커로 확인. 못 찾으면 UNKNOWN (자동 재발송 금지)
      401(인증 오류, R5)         결과에 auth_error=True. 실패 횟수로 세지 않는다 (DB 차단기가 선점을 멈춘다)
        POST 401 / 첫 전달의 사전 조회·DM 채널 401 -> FAILED_RETRY(전송되지 않음)
        재전달 작업의 사전 조회 401                -> UNKNOWN (앞선 전달의 전송 여부를 알 수 없음)
        확인(verify) 작업의 401                   -> INCONCLUSIVE (UNKNOWN 유지, 판단 보류)
  * POST 직전에 not_after를 다시 확인한다 (R4). 조회가 오래 걸려 만료됐으면 보내지 않는다 (EXPIRED).
    이미 시작된 POST의 429 대기·재시도는 막지 못한다: Gateway의 Lambda 행 인수 16분 제한과 예약 동시성 1이 그 경우를 막는다.
필수 배포 설정은 #163과 같다: 예약 동시성 1, 배치 크기 1, ReportBatchItemFailures, 가시성 타임아웃 >= 함수 타임아웃 x 6.
"""
import logging
import os
from datetime import datetime, timezone

from career_share import contract
from career_share.messages import NO_MENTIONS
from career_share.queues import SqsPublisher
from career_share.worker import CareerShareWorker, TransientWorkerError
from career_share.worker_lambda import handle_records
from discord_rest import errors
from dm_share.units import DM_BLOCKED_CODE, USER_GONE_CODES, notification_id_of   # DB 저장소 모듈 대신 순수 모듈 (#182)
from services.notification_policy import to_discord_id

log = logging.getLogger("dm_share")
KIND_DM = "DM"
_runtime = None


def classify(error: errors.DiscordError) -> str | None:
    """전송 시도 오류의 결과 종류. None이면 결과 불명(마커로 확인해야 함)."""
    if isinstance(error, errors.DiscordRateLimited):
        return "FAILED_RETRY"
    if error.code == DM_BLOCKED_CODE or error.code in USER_GONE_CODES:
        return "FAILED_PERMANENT"
    if error.outcome_unknown:
        return None
    return "FAILED_RETRY"


class _AuthWatch:
    """마커 조회(get_recent_messages / get_channel)의 401을 기록하는 얇은 대리 객체. 나머지 호출은 그대로 넘긴다.

    CareerShareWorker.lookup은 조회 오류를 TransientWorkerError로 바꾸므로, 401인지 여기서 따로 알아 둔다 (#163 코드 무수정)."""

    def __init__(self, client):
        self._client = client
        self.auth_failed = False

    def __getattr__(self, name):
        return getattr(self._client, name)

    def _watch(self, method, *args, **kwargs):
        try:
            return method(*args, **kwargs)
        except errors.DiscordAuthError:
            self.auth_failed = True
            raise

    def get_recent_messages(self, *args, **kwargs):
        return self._watch(self._client.get_recent_messages, *args, **kwargs)

    def get_channel(self, *args, **kwargs):
        return self._watch(self._client.get_channel, *args, **kwargs)


class DmShareWorker(CareerShareWorker):
    UNIT_PREFIXES = ("dm-",)

    def __init__(self, client, clock=lambda: datetime.now(timezone.utc)):
        super().__init__(client, None, clock)

    def _result(self, job: dict, outcome: str, **extra) -> dict:
        result = {"v": contract.VERSION, "type": contract.TYPE_RESULT, "job_id": job["job_id"], "unit_id": job["unit_id"],
                  "kind": job.get("kind"), "claim_token": job["claim_token"], "outcome": outcome,
                  "completed_at": contract.iso(self.clock())}
        if self.channel_id is not None:
            result["channel_id"] = str(self.channel_id)
        result.update({k: v for k, v in extra.items() if v is not None})
        return contract.validate_result(result)

    def process(self, job: dict, *, receive_count: int = 1) -> dict:
        if not isinstance(job, dict) or job.get("kind") != KIND_DM or notification_id_of(job.get("unit_id")) is None:
            raise contract.ContractError("DM 작업이 아닙니다.")
        job = contract.validate_job(job)
        if not job["unit_id"].startswith(self.UNIT_PREFIXES):
            raise contract.ContractError("이 Worker가 처리하지 않는 작업 단위입니다.")
        recipient = to_discord_id(job.get("recipient_id"))
        if recipient is None:
            raise contract.ContractError("recipient_id 오류")
        try:
            channel = self.client.create_dm_channel(recipient)
            channel_id = int(channel["id"])
        except errors.DiscordAuthError:
            return self._auth_result(job, receive_count, "DM 채널 열기 401")
        except errors.DiscordError as error:
            outcome = classify(error) if job["type"] == contract.TYPE_SEND else None
            if outcome is None or error.outcome_unknown:
                raise TransientWorkerError(f"DM 채널 열기 실패 status={error.status}") from None
            # 보내기 전 단계의 실패: 전송되지 않았음이 확실하다
            return self._result(job, outcome, error=f"DM 채널 열기 실패 {type(error).__name__} status={error.status} code={error.code}",
                                error_code=error.code)
        except (KeyError, TypeError, ValueError):
            raise TransientWorkerError("DM 채널 응답 형식 오류") from None
        watch = _AuthWatch(self.client)
        bound = DmShareWorker(watch, clock=self.clock)
        bound.channel_id = channel_id
        try:
            return CareerShareWorker.process(bound, job, receive_count=receive_count)
        except TransientWorkerError:
            if watch.auth_failed:   # 사전 조회(발송 작업) 또는 확인 작업 조회가 401: POST는 하지 않았다
                return bound._auth_result(job, receive_count, "메시지 조회 401")
            raise

    def _auth_result(self, job: dict, receive_count: int, reason: str) -> dict:
        """401 결과 (auth_error=True). 실패 횟수로 세지 않고 DB 차단기가 선점을 멈춘다."""
        log.error("Discord 401 (토큰 확인 필요): %s unit=%s", reason, job["unit_id"])
        if job["type"] == contract.TYPE_VERIFY:
            return self._result(job, "INCONCLUSIVE", error=reason, auth_error=True)
        if receive_count > 1:
            return self._result(job, "UNKNOWN", error=reason + " (재전달 작업: 앞선 전송 여부 불명)", auth_error=True)
        return self._result(job, "FAILED_RETRY", error=reason + " (전송되지 않음)", auth_error=True)

    def _send(self, job: dict, since: datetime) -> dict:
        if self.clock() > contract.parse_time(job["not_after"]):
            # R4: 조회가 오래 걸려 POST 직전에 만료됐다. 이 처리에서는 아직 보내지 않았으므로 EXPIRED (재선점은 DB가 판단).
            return self._result(job, "EXPIRED", error="POST 직전 not_after 경과: 보내지 않음")
        payload = job["payload"]
        try:
            message = self.client.send_message(self.channel_id, embeds=payload["embeds"], allowed_mentions=dict(NO_MENTIONS),
                                               nonce=job["marker"])
            message_id = str(message["id"])
        except errors.DiscordAuthError:
            return self._result(job, "FAILED_RETRY", error="POST 401 (전송되지 않음)", auth_error=True)
        except errors.DiscordError as error:
            outcome = classify(error)
            if outcome is None:
                return self._resolve_unknown(job, since, f"{type(error).__name__} status={error.status}")
            if outcome == "FAILED_PERMANENT":
                log.info("DM 영구 실패 code=%s", error.code)
            return self._result(job, outcome, error=f"{type(error).__name__} status={error.status} code={error.code}",
                                error_code=error.code)
        except (KeyError, TypeError):
            return self._resolve_unknown(job, since, "응답에 메시지 id가 없음")
        return self._result(job, "SENT", message_id=message_id)


def _build(context=None):
    from discord_rest import DiscordRestClient
    token = os.environ["DISCORD_BOT_TOKEN"]
    remaining = context.get_remaining_time_in_millis() / 1000 - 5 if context is not None else None
    client = DiscordRestClient(token, time_budget=remaining if remaining and remaining > 5 else None)
    return DmShareWorker(client), os.environ["DM_SHARE_RESULT_QUEUE_URL"], SqsPublisher()


def handler(event, context=None):
    global _runtime
    if _runtime is None:
        _runtime = _build(context)
    worker, queue_url, publisher = _runtime
    return handle_records(event, worker, publisher, queue_url)
