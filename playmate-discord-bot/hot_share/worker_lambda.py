"""HOT Discord Worker Lambda (VPC 밖, DB 접근 없음). career_share의 Worker 로직과 SQS 처리 함수를 그대로 쓴다.

다른 점은 두 가지뿐이다.
  * 채널: HOT_SHARE_CHANNEL_ID(기존 🔥│핫플레이메이트). Worker는 작업이 아니라 자기 환경변수의 채널로만 보낸다.
  * HOT 작업(kind=HOT, unit_id=hot-<id>)만 처리한다. 다른 작업이 잘못 들어오면 형식 오류로 DLQ에 보낸다 (취업 글이 HOT 채널에 게시되지 않게).
필수 배포 설정은 #163과 같다: 예약 동시성 1, 배치 크기 1, ReportBatchItemFailures, 가시성 타임아웃 >= 함수 타임아웃 x 6.
"""
import logging
import os

from career_share import contract
from career_share.queues import SqsPublisher
from career_share.worker import CareerShareWorker
from career_share.worker_lambda import handle_records
from hot_share.messages import post_id_of
from hot_share.policy import KIND_HOT

log = logging.getLogger("hot_share")
_runtime = None


class HotShareWorker(CareerShareWorker):
    UNIT_PREFIXES = ("hot-",)   # 취업 단위(post-/digest-)는 부모 process에서도 거부된다

    def process(self, job: dict, *, receive_count: int = 1) -> dict:
        if not isinstance(job, dict) or job.get("kind") != KIND_HOT or post_id_of(job.get("unit_id")) is None:
            raise contract.ContractError("HOT 작업이 아닙니다.")
        return super().process(job, receive_count=receive_count)


def _build(context=None):
    from discord_rest import DiscordRestClient
    token = os.environ["DISCORD_BOT_TOKEN"]
    channel = int(os.environ["HOT_SHARE_CHANNEL_ID"])
    remaining = context.get_remaining_time_in_millis() / 1000 - 5 if context is not None else None
    client = DiscordRestClient(token, time_budget=remaining if remaining and remaining > 5 else None)
    return HotShareWorker(client, channel), os.environ["HOT_SHARE_RESULT_QUEUE_URL"], SqsPublisher()


def handler(event, context=None):
    global _runtime
    if _runtime is None:
        _runtime = _build(context)
    worker, queue_url, publisher = _runtime
    return handle_records(event, worker, publisher, queue_url)
