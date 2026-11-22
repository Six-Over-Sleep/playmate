"""DB Lambda의 업무 로직: relay(즉시 공유) / digest(20시 묶음) / result(결과 반영) / recover(복구).

DB와 SQS는 주입받는다 (테스트는 메모리 저장소와 FakeQueue). Discord에는 접근하지 않는다 (그건 Worker의 일이다).

발행 실패 처리: SQS 발행이 실패하면 큐에 들어갔는지 알 수 없으므로 FAILED로 바꾸지 않고 PENDING으로 둔다.
선점 만료(claim_stale_minutes) 뒤 복구 단계가 UNKNOWN -> 마커 확인 -> (미전송 증명 시) 재선점으로 안전하게 이어 간다.
이때 큐에 남은 옛 작업이 뒤늦게 발송되지 않도록 작업에 not_after(job_ttl_minutes)가 들어 있고 Worker가 지킨다.
"""
import logging
from datetime import date, datetime, timedelta, timezone

from career_share import contract, messages
from career_share.policy import KIND_DIGEST, KIND_IMMEDIATE, classify
from career_share.queues import PublishError
from career_share.settings import DbSettings
from services.web_links import career_post_url

log = logging.getLogger("career_share")
KST = timezone(timedelta(hours=9))


def digest_date(now: datetime) -> date:
    """20:00 KST 배치의 날짜. 항상 KST 달력 날짜 (UTC 날짜가 아니다)."""
    return now.astimezone(KST).date()


class CareerShareService:
    def __init__(self, repo, publisher, settings: DbSettings, clock=lambda: datetime.now(timezone.utc)):
        self.repo, self.publisher, self.s, self.clock = repo, publisher, settings, clock

    # -- 작업 만들기 ---------------------------------------------------------------
    def _entries(self, claim: dict):
        entries = []
        for post in claim["posts"]:
            target = classify(post["category_code"], post["subcategory_code"], post.get("process_result"))
            url = career_post_url(self.s.base_url, post["category_code"], post["post_id"])
            if target is None or url is None:
                raise ValueError("공유 대상이 아니거나 링크를 만들 수 없습니다.")
            entries.append((post, url, target.label))
        return entries

    def _job(self, claim: dict, now: datetime, job_type: str) -> dict:
        unit = claim["unit_id"]
        job = {"v": contract.VERSION, "type": job_type, "job_id": f"{unit}:{claim['claim_token']}",
               "unit_id": unit, "kind": claim["kind"], "claim_token": claim["claim_token"],
               "claimed_at": contract.iso(claim["claimed_at"]),
               "not_after": contract.iso(claim["claimed_at"] + timedelta(minutes=self.s.job_ttl_minutes)),
               "marker": messages.marker_for(unit)}
        if job_type == contract.TYPE_SEND:
            entries = self._entries(claim)
            if claim["kind"] == KIND_IMMEDIATE:
                job["payload"] = messages.immediate_payload(entries[0][0], entries[0][1], entries[0][2])
            else:
                job["payload"] = messages.digest_payload(entries, claim["batch_date"])
        return contract.validate_job(job)

    def _publish_claims(self, claims: list[dict], now: datetime) -> dict:
        sent = failed_publish = invalid = 0
        for claim in claims:
            try:
                job = self._job(claim, now, contract.TYPE_SEND)
            except ValueError as error:
                # 만들 수 없는 메시지는 재시도해도 같다: 영구 실패로 기록한다 (전송된 적 없음이 확실하다).
                self.repo.apply_result({"unit_id": claim["unit_id"], "claim_token": claim["claim_token"],
                                        "outcome": "FAILED_PERMANENT", "error": f"메시지 생성 불가: {error}"}, now,
                                       retry_base_minutes=self.s.retry_base_minutes, absent_required=self.s.absent_required)
                invalid += 1
                continue
            try:
                self.publisher.send(self.s.send_queue_url, contract.dumps(job))
                sent += 1
            except PublishError as error:
                failed_publish += 1  # PENDING 유지: 큐에 들어갔을 수도 있으므로 만료 후 확인 절차로 복구한다
                log.warning("발송 큐 발행 실패 unit=%s: %s", claim["unit_id"], error)
        return {"claimed": len(claims), "published": sent, "publish_failed": failed_publish, "invalid": invalid}

    # -- 이벤트 처리 ---------------------------------------------------------------
    def relay(self, now: datetime | None = None) -> dict:
        """1분 주기: 신규 후기(즉시 공유) 선점 -> 발송 큐. 이어서 복구 단계도 실행한다."""
        now = now or self.clock()
        if not self.s.base_url:
            log.error("PLAYMATE_WEB_BASE_URL이 없거나 사용할 수 없어 공유하지 않습니다 (링크 없는 공유 금지).")
            return {"skipped": "no_base_url"}
        claims = self.repo.claim_immediate(now, cutover=self.s.cutover_at, limit=self.s.relay_limit,
                                           max_attempts=self.s.max_attempts, stale_minutes=self.s.claim_stale_minutes)
        result = self._publish_claims(claims, now)
        result["recover"] = self.recover(now)
        return result

    def digest(self, now: datetime | None = None, scheduled_at: datetime | None = None) -> dict:
        """매일 20:00 KST: 미공유 연구소 글 최대 5건 -> 메시지 1건. 같은 날짜의 두 번째 실행은 아무것도 하지 않는다.

        날짜는 예약 시각(scheduled_at, 없으면 now)의 KST 날짜다. 선점/만료 계산은 실제 현재 시각(now)을 쓴다 (늦게 실행돼도
        작업이 곧바로 만료되지 않게).
        """
        now = now or self.clock()
        if not self.s.base_url:
            log.error("PLAYMATE_WEB_BASE_URL이 없거나 사용할 수 없어 공유하지 않습니다 (링크 없는 공유 금지).")
            return {"skipped": "no_base_url"}
        claim = self.repo.claim_digest(now, digest_date(scheduled_at or now), cutover=self.s.cutover_at, limit=self.s.digest_limit,
                                       max_attempts=self.s.max_attempts, stale_minutes=self.s.claim_stale_minutes)
        if claim is None:
            return {"claimed": 0}
        return self._publish_claims([claim], now)

    def recover(self, now: datetime | None = None) -> dict:
        """만료된 PENDING / 확인 대기 UNKNOWN을 마커 확인 작업(verify)으로 보낸다. 재발송이 아니다."""
        now = now or self.clock()
        tasks = self.repo.claim_verifications(now, max_verifies=self.s.max_verifies,
                                              interval_minutes=self.s.verify_interval_minutes,
                                              settle_minutes=self.s.verify_settle_minutes)
        published = 0
        for task in tasks:
            job = {"v": contract.VERSION, "type": contract.TYPE_VERIFY,
                   "job_id": f"{task['unit_id']}:{task['claim_token']}:v{int(now.timestamp())}",
                   "unit_id": task["unit_id"], "kind": task["kind"], "claim_token": task["claim_token"],
                   "claimed_at": contract.iso(task["claimed_at"]),
                   "not_after": contract.iso(now + timedelta(minutes=self.s.job_ttl_minutes)),
                   "marker": messages.marker_for(task["unit_id"])}
            try:
                self.publisher.send(self.s.send_queue_url, contract.dumps(contract.validate_job(job)))
                published += 1
            except PublishError as error:
                log.warning("확인 작업 발행 실패 unit=%s: %s", task["unit_id"], error)  # 다음 주기에 다시 시도(verify_count 한도 내)
        return {"verify_jobs": published, "verify_due": len(tasks)}

    def apply_result(self, body, now: datetime | None = None) -> str:
        """결과 큐 메시지 한 건 반영. 'applied' / 'duplicate' / 'ignored'. 형식 오류는 ContractError."""
        now = now or self.clock()
        result = contract.validate_result(contract.loads(body))
        return self.repo.apply_result(result, now, retry_base_minutes=self.s.retry_base_minutes,
                                      absent_required=self.s.absent_required)

    def baseline(self) -> dict:
        return {"baseline_rows": self.repo.baseline(self.s.cutover_at)}

    def summary(self, now: datetime | None = None) -> dict:
        return self.repo.summary(now or self.clock(), max_attempts=self.s.max_attempts)
