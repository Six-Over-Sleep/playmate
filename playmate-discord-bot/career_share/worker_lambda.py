"""Discord Worker Lambda 핸들러 (VPC 밖, DB 접근 없음). 발송 큐 이벤트 소스 매핑으로 호출된다.

필수 배포 설정 (DEPLOY.md): 예약 동시성 1, 배치 크기 1, ReportBatchItemFailures, 가시성 타임아웃 >= 함수 타임아웃 x 6.
환경변수: DISCORD_BOT_TOKEN(Secrets Manager 등에서 주입), CAREER_SHARE_CHANNEL_ID, CAREER_SHARE_RESULT_QUEUE_URL.
이 모듈은 discord.py, 기존 config, DB 드라이버를 import하지 않는다 (표준 라이브러리 + discord_rest).
"""
import logging
import os

from career_share import contract
from career_share.queues import PublishError, SqsPublisher
from career_share.worker import CareerShareWorker, TransientWorkerError

log = logging.getLogger("career_share")
_runtime = None


def _build(context=None):
    from discord_rest import DiscordRestClient
    token = os.environ["DISCORD_BOT_TOKEN"]
    channel = int(os.environ["CAREER_SHARE_CHANNEL_ID"])
    remaining = context.get_remaining_time_in_millis() / 1000 - 5 if context is not None else None
    client = DiscordRestClient(token, time_budget=remaining if remaining and remaining > 5 else None)
    return CareerShareWorker(client, channel), os.environ["CAREER_SHARE_RESULT_QUEUE_URL"], SqsPublisher()


def handle_records(event: dict, worker: CareerShareWorker, publisher, result_queue_url: str) -> dict:
    failures = []
    for record in event.get("Records") or []:
        message_id = record.get("messageId")
        try:
            job = contract.loads(record.get("body"))
            count = int((record.get("attributes") or {}).get("ApproximateReceiveCount") or 1)
            result = worker.process(job, receive_count=count)
            publisher.send(result_queue_url, contract.dumps(result))  # 실패하면 재전달된다 (재전달 시 마커로 중복 방지)
            log.info("job %s -> %s", job.get("job_id"), result["outcome"])
        except contract.ContractError as error:
            log.error("작업 형식 오류 id=%s: %s", message_id, error)  # 재시도해도 같다: DLQ로 간다
            failures.append({"itemIdentifier": message_id})
        except (TransientWorkerError, PublishError) as error:
            log.warning("처리 보류 id=%s: %s", message_id, error)
            failures.append({"itemIdentifier": message_id})
        except Exception as error:
            log.error("예상하지 못한 오류 id=%s: %s", message_id, type(error).__name__)
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}


def handler(event, context=None):
    global _runtime
    if _runtime is None:
        _runtime = _build(context)
    worker, queue_url, publisher = _runtime
    return handle_records(event, worker, publisher, queue_url)
