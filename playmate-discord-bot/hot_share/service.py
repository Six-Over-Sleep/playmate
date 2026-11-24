"""HOT DB Lambda 업무 로직. career_share.service.CareerShareService를 상속해 발행/복구/결과 반영 흐름을 그대로 쓴다.

재사용(상속, 수정 없음): _publish_claims(발행 실패 시 PENDING 유지, 메시지 생성 불가 시 영구 실패), recover(만료 PENDING/UNKNOWN의
마커 확인 작업 발행), apply_result(계약 검증 후 저장소 반영).
바꾼 것: 작업 본문(HOT 메시지), relay(HOT 선점 + baseline 확인), baseline, summary. digest는 HOT에 없다.
"""
import logging
from datetime import datetime, timezone

from career_share import contract
from career_share.service import CareerShareService
from hot_share import messages, policy
from hot_share.repository import BASELINE_REQUIRED
from services.web_links import board_post_url

log = logging.getLogger("hot_share")


class HotShareService(CareerShareService):
    def __init__(self, repo, publisher, settings, clock=lambda: datetime.now(timezone.utc)):
        super().__init__(repo, publisher, settings, clock)

    def _job(self, claim: dict, now: datetime, job_type: str) -> dict:
        if claim.get("kind") != policy.KIND_HOT or messages.post_id_of(claim.get("unit_id")) is None:
            raise ValueError("HOT 작업이 아닙니다.")
        job = super()._job(claim, now, contract.TYPE_VERIFY)   # 공통 필드(job_id, not_after, marker)는 #163 규칙 그대로
        job["type"] = job_type
        if job_type == contract.TYPE_SEND:
            post = claim["posts"][0]
            url = board_post_url(self.s.base_url, post.get("board_id"), post.get("post_id"))
            if url is None:
                raise ValueError("링크를 만들 수 없습니다.")
            job["payload"] = messages.hot_payload(post, url)
        return contract.validate_job(job)

    def relay(self, now: datetime | None = None) -> dict:
        """5분 주기: baseline 완료 후 신규 HOT 글 선점 -> 발송 큐. 이어서 복구 단계도 실행한다."""
        now = now or self.clock()
        if not self.s.base_url:
            log.error("PLAYMATE_WEB_BASE_URL이 없거나 사용할 수 없어 공유하지 않습니다 (링크 없는 공유 금지).")
            return {"skipped": "no_base_url"}
        claims = self.repo.claim_hot(now, limit=self.s.relay_limit, max_attempts=self.s.max_attempts,
                                     stale_minutes=self.s.claim_stale_minutes)
        if claims == BASELINE_REQUIRED:
            log.error("HOT baseline이 끝나지 않아 공유하지 않습니다. {\"action\":\"hot_baseline\"}을 먼저 1회 실행하세요.")
            return {"skipped": BASELINE_REQUIRED}
        result = self._publish_claims(claims, now)
        result["recover"] = self.recover(now)
        result["sent_not_shareable"] = self._report_sent_not_shareable()
        return result

    def _report_sent_not_shareable(self) -> int | None:
        """게시 후 삭제·비공개·범위 변경된 글을 매 주기 ERROR로 알린다 (CloudWatch 경보 연결용, PR #170 리뷰 ①).

        Worker는 DB를 보지 않으므로 선점 뒤 또는 게시 뒤의 상태 변경을 막지 못한다. 수동 hot_summary에만 의존하지 않도록
        정리(RETRACTED 기록)될 때까지 반복해서 알린다. 조회 실패는 이번 주기의 선점·발행 결과를 바꾸지 않는다.
        """
        try:
            gone = self.repo.sent_not_shareable()
        except Exception as error:  # 알림 조회는 부가 기능: 다음 주기에 다시 확인한다
            log.error("HOT 게시 후 상태 확인 실패: %s", type(error).__name__)
            return None
        if gone:
            log.error("게시 후 공유 불가가 된 HOT 글 %d건 (Discord 메시지 삭제 필요, 삭제 확인 후 RETRACTED 기록): %s", len(gone),
                      ", ".join(f"post_id={g['post_id']} message_id={g['discord_message_id']}" for g in gone[:50]))
        return len(gone)

    def digest(self, *args, **kwargs):
        raise NotImplementedError("HOT 공유에는 묶음 공유가 없습니다.")

    def baseline(self, now: datetime | None = None) -> dict:
        return self.repo.baseline(now or self.clock())

    def summary(self, now: datetime | None = None) -> dict:
        return self.repo.summary(now or self.clock(), max_attempts=self.s.max_attempts)
