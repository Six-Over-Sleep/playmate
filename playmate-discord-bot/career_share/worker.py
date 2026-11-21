"""Discord Worker의 발송/확인 로직 (VPC 밖, PostgreSQL에 접근하지 않는다). 기존 #161 DiscordRestClient를 그대로 쓴다.

핵심 규칙
  * 보내기 전에 채널의 최근 메시지에서 이 작업의 마커(embed footer)를 찾는다. 있으면 이미 전송된 것이므로 보내지 않고 SENT로 보고한다
    (SQS 중복 전달/결과 발행 실패 뒤 재전달 시 중복 메시지 방지).
  * 마커를 못 찾았다는 사실만으로 "전송 안 됨"을 확정하지 않는다. 조회 범위가 작업의 claimed_at 이전까지 닿았을 때만 증명으로 본다
    (권한이 없으면 Discord가 오류 없이 빈 목록을 주고, 페이지 범위 밖에 있을 수도 있다).
  * 5xx/타임아웃(outcome_unknown)은 다시 보내지 않는다: 마커로 확인하고, 못 찾으면 UNKNOWN으로 보고한다.
  * not_after가 지난 작업은 보내지 않는다 (EXPIRED). 이것이 있어야 DB 쪽의 "확인 후 재선점"이 안전하다.
"""
import logging
from datetime import datetime, timezone

from career_share import contract
from career_share.messages import NO_MENTIONS, message_has_marker
from discord_rest import errors, inactivity

log = logging.getLogger("career_share")
PAGE_SIZE, MAX_PAGES = 100, 3


class TransientWorkerError(RuntimeError):
    """지금은 판단할 수 없다 (조회 실패 등). 결과를 보내지 않고 큐가 작업을 다시 전달하게 한다."""


class Lookup:
    """마커 조회 결과. found: 메시지 id 또는 None / proven_absent: 마커가 없음이 증명됨."""

    def __init__(self, found: str | None, proven_absent: bool):
        self.found, self.proven_absent = found, proven_absent


class CareerShareWorker:
    def __init__(self, client, channel_id: int, clock=lambda: datetime.now(timezone.utc)):
        self.client, self.channel_id, self.clock = client, channel_id, clock

    # -- 마커 조회 -----------------------------------------------------------------
    def lookup(self, marker: str, since: datetime) -> Lookup:
        """최근 메시지를 최신순으로 훑어 마커를 찾는다. 조회 자체가 실패하면 TransientWorkerError."""
        before = None
        try:
            for page in range(MAX_PAGES):
                messages = self.client.get_recent_messages(self.channel_id, PAGE_SIZE, before=before)
                if not isinstance(messages, list):
                    raise TransientWorkerError("메시지 목록 형식 오류")
                for message in messages:
                    if message_has_marker(message, marker):
                        return Lookup(str(message["id"]), False)
                if not messages:
                    if page > 0:
                        return Lookup(None, True)  # 거슬러 올라가다 채널의 처음까지 닿았다
                    channel = self.client.get_channel(self.channel_id)
                    last = channel.get("last_message_id") if isinstance(channel, dict) else False
                    if last is None:
                        return Lookup(None, True)  # 메시지가 한 번도 없는 채널
                    try:
                        return Lookup(None, inactivity.snowflake_time(last) <= since)  # 최근 메시지가 숨겨졌을 수 있다
                    except (TypeError, ValueError, OverflowError, OSError):
                        return Lookup(None, False)
                try:
                    oldest = min(inactivity.parse_discord_time(m["timestamp"]) for m in messages)
                except (KeyError, TypeError, ValueError, AttributeError):
                    return Lookup(None, False)
                if oldest <= since:
                    return Lookup(None, True)  # claimed_at 이전까지 확인했는데 마커가 없다
                before = int(messages[-1]["id"])
        except errors.DiscordError as error:
            raise TransientWorkerError(f"메시지 조회 실패 status={error.status}") from None
        return Lookup(None, False)

    # -- 작업 처리 -----------------------------------------------------------------
    def _result(self, job: dict, outcome: str, **extra) -> dict:
        result = {"v": contract.VERSION, "type": contract.TYPE_RESULT, "job_id": job["job_id"], "unit_id": job["unit_id"],
                  "kind": job.get("kind"), "claim_token": job["claim_token"], "outcome": outcome,
                  "channel_id": str(self.channel_id), "completed_at": contract.iso(self.clock())}
        result.update({k: v for k, v in extra.items() if v is not None})
        return contract.validate_result(result)

    def process(self, job: dict, *, receive_count: int = 1) -> dict:
        """작업 하나를 처리하고 결과(dict)를 돌려준다. 판단할 수 없으면 TransientWorkerError (큐가 다시 전달)."""
        job = contract.validate_job(job)
        since = contract.parse_time(job["claimed_at"])
        if job["type"] == contract.TYPE_VERIFY:
            found = self.lookup(job["marker"], since)
            if found.found:
                return self._result(job, "SENT", message_id=found.found)
            return self._result(job, "ABSENT_PROVEN" if found.proven_absent else "INCONCLUSIVE")

        if self.clock() > contract.parse_time(job["not_after"]):
            if receive_count > 1:
                # 재전달된 작업: 앞선 전달이 이미 보냈을 수 있다 (결과만 유실). '보내지 않았다'고 단정하지 않는다.
                return self._result(job, "UNKNOWN", error="not_after 경과한 재전달 작업: 앞선 전송 여부를 확인하지 못함")
            return self._result(job, "EXPIRED", error="not_after 경과: 보내지 않음")
        # 보내기 전 확인: 이미 있으면 보내지 않는다. 조회가 불가능하면 판단 보류(큐가 재전달).
        existing = self.lookup(job["marker"], since)
        if existing.found:
            return self._result(job, "SENT", message_id=existing.found)
        if receive_count > 1 and not existing.proven_absent:
            # 재전달된 작업인데 이전 시도가 보냈는지 증명할 수 없다: 보내지 않는다.
            return self._result(job, "UNKNOWN", error="재전달 작업이며 기존 전송 여부를 확인하지 못함")
        return self._send(job, since)

    def _send(self, job: dict, since: datetime) -> dict:
        payload = job["payload"]
        try:
            message = self.client.send_message(self.channel_id, embeds=payload["embeds"], allowed_mentions=dict(NO_MENTIONS),
                                               nonce=job["marker"])
            message_id = str(message["id"])
        except errors.DiscordRateLimited as error:
            return self._result(job, "FAILED_RETRY", error=f"429 rate limit (실행되지 않음) retry_after={error.retry_after}")
        except (errors.DiscordAuthError, errors.DiscordForbidden, errors.DiscordNotFound, errors.DiscordRequestError) as error:
            log.error("영구 오류 status=%s code=%s (설정/권한 확인 필요)", error.status, error.code)
            return self._result(job, "FAILED_PERMANENT", error=f"{type(error).__name__} status={error.status} code={error.code}")
        except errors.DiscordError as error:
            if not error.outcome_unknown:
                return self._result(job, "FAILED_RETRY", error=f"{type(error).__name__} (전송 전 실패)")
            return self._resolve_unknown(job, since, f"{type(error).__name__} status={error.status}")
        except (KeyError, TypeError):
            return self._resolve_unknown(job, since, "응답에 메시지 id가 없음")
        return self._result(job, "SENT", message_id=message_id)

    def _resolve_unknown(self, job: dict, since: datetime, reason: str) -> dict:
        """전송 결과 불명: 마커로 확인한다. 찾으면 SENT, 못 찾아도 FAILED가 아니라 UNKNOWN (자동 재발송 금지)."""
        try:
            found = self.lookup(job["marker"], since)
        except TransientWorkerError:
            return self._result(job, "UNKNOWN", error=reason + " / 확인 조회도 실패")
        if found.found:
            return self._result(job, "SENT", message_id=found.found)
        return self._result(job, "UNKNOWN", error=reason + " / 마커 미발견(미전송 단정 불가)")
