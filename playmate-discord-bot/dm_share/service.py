"""DM DB Lambda 업무 로직. CareerShareService를 상속해 발행(_publish_claims)과 결과 반영(apply_result) 흐름을 그대로 쓴다.

바꾼 것: 작업 본문(DM embed + recipient_id, TTL 초 단위), relay(Gateway 만료 마감 + 공동 선점), recover(받는 사람 포함 확인 작업 +
확인 한도 초과 마감), summary. digest/baseline은 없다 (DM은 최초 실행 때 쌓인 PENDING도 정상 대상이다).
"""
import logging
from datetime import datetime, timedelta, timezone

from career_share import contract
from career_share.messages import marker_for
from career_share.queues import PublishError
from career_share.service import CareerShareService
from dm_share.messages import dm_payload
from repositories.dm_delivery_repository import SENDER_LAMBDA, dm_unit_id, notification_id_of
from services.web_links import notification_post_url

log = logging.getLogger("dm_share")
KIND_DM = "DM"


class DmShareService(CareerShareService):
    def __init__(self, repo, publisher, settings, clock=lambda: datetime.now(timezone.utc)):
        super().__init__(repo, publisher, settings, clock)

    def _link(self, notification: dict) -> str | None:
        if not self.s.base_url:
            return None
        try:
            return notification_post_url(self.s.base_url, notification)
        except Exception:   # 링크 문제로 DM을 막지 않는다 (기존 Gateway와 같음)
            return None

    def _base_job(self, unit: str, token: str, claimed_at: datetime, not_after: datetime, recipient, job_type: str,
                  job_id: str) -> dict:
        return {"v": contract.VERSION, "type": job_type, "job_id": job_id, "unit_id": unit, "kind": KIND_DM,
                "claim_token": token, "claimed_at": contract.iso(claimed_at), "not_after": contract.iso(not_after),
                "marker": marker_for(unit), "recipient_id": str(recipient or "")}

    def _job(self, claim: dict, now: datetime, job_type: str) -> dict:
        if claim.get("kind") != KIND_DM or notification_id_of(claim.get("unit_id")) is None:
            raise ValueError("DM 작업이 아닙니다.")
        unit, token = claim["unit_id"], claim["claim_token"]
        job = self._base_job(unit, token, claim["claimed_at"], claim["claimed_at"] + timedelta(seconds=self.s.job_ttl_seconds),
                             claim["recipient_id"], job_type, f"{unit}:{token}")
        if job_type == contract.TYPE_SEND:
            notification = claim["notification"]
            job["payload"] = dm_payload(notification, self._link(notification))
        return contract.validate_job(job)

    def relay(self, now: datetime | None = None) -> dict:
        """1분 주기: 만료된 Gateway 선점 마감 -> 공동 선점 -> 발송 큐. 이어서 복구 단계도 실행한다."""
        now = now or self.clock()
        expired = self.repo.expire_gateway_claims(now)
        raw = self.repo.claim(SENDER_LAMBDA, now, limit=self.s.relay_limit, stale_seconds=self.s.claim_stale_minutes * 60)
        claims = [{"unit_id": dm_unit_id(c["notification"]["notification_id"]), "kind": KIND_DM,
                   "claim_token": c["claim_token"], "claimed_at": c["claimed_at"], "recipient_id": c["recipient_id"],
                   "notification": c["notification"]} for c in raw]
        result = self._publish_claims(claims, now)
        result["gateway_expired"] = len(expired)
        result["auth_breaker"] = (self.repo.last_breaker or {}).get("state", "CLOSED")
        result["recover"] = self.recover(now)
        return result

    def recover(self, now: datetime | None = None) -> dict:
        """만료된 PENDING / 정착 대기가 지난 UNKNOWN의 마커 확인 작업 발행 (재발송 아님) + 확인 한도 초과 마감."""
        now = now or self.clock()
        if self.repo.auth_open():
            # R5: 인증 장애(401) 동안에는 마커 확인·확인 한도 마감을 멈춘다 (UNKNOWN을 FAILED로 바꾸지 않는다). 만료 처리만 한다.
            self.repo.expire_lambda_claims(now)
            return {"verify_jobs": 0, "verify_due": 0, "finalized_unknown": 0, "paused_auth": True}
        tasks = self.repo.claim_verifications(now, max_verifies=self.s.max_verifies,
                                              interval_minutes=self.s.verify_interval_minutes,
                                              settle_minutes=self.s.verify_settle_minutes)
        published = 0
        for task in tasks:
            unit = task["unit_id"]
            job = self._base_job(unit, task["claim_token"], task["claimed_at"], now + timedelta(seconds=self.s.job_ttl_seconds),
                                 task["recipient_id"], contract.TYPE_VERIFY,
                                 f"{unit}:{task['claim_token']}:v{int(now.timestamp())}")
            try:
                self.publisher.send(self.s.send_queue_url, contract.dumps(contract.validate_job(job)))
                published += 1
            except PublishError as error:
                log.warning("확인 작업 발행 실패 unit=%s: %s", unit, error)
        finalized = self.repo.finalize_unverifiable(now, max_verifies=self.s.max_verifies,
                                                    interval_minutes=self.s.verify_interval_minutes)
        return {"verify_jobs": published, "verify_due": len(tasks), "finalized_unknown": len(finalized)}

    def digest(self, *args, **kwargs):
        raise NotImplementedError("DM에는 묶음 공유가 없습니다.")

    def baseline(self, *args, **kwargs):
        raise NotImplementedError("DM에는 baseline이 없습니다 (PENDING 알림은 모두 정상 대상).")

    def summary(self, now: datetime | None = None) -> dict:
        return self.repo.summary()
