"""DB Lambda 핸들러 (VPC 안, PostgreSQL 접근). 이벤트 종류에 따라 분기한다.

  EventBridge Scheduler (1분)        {"action": "relay"}                          즉시 공유 선점+발행, 복구 단계 포함
  EventBridge Scheduler (매일 20:00 Asia/Seoul) {"action": "digest", "scheduled_at": "<aws.scheduler.scheduled-time>"}
  결과 큐 (SQS 이벤트 소스 매핑)      {"Records": [...]}                           결과 반영 (batchItemFailures 응답)
  수동                               {"action": "baseline"} / {"action": "summary"}

SQS 결과 처리는 부분 실패 응답(ReportBatchItemFailures)을 쓴다. 형식 오류는 재시도해도 같으므로 로그를 남기고 실패로 보고해
DLQ로 보낸다. DB 일시 오류도 실패로 보고해 큐가 다시 전달한다 (결과 반영은 멱등이다).
"""
import json
import logging
import os
from datetime import datetime, timezone

from career_share import contract
from career_share.queues import SqsPublisher
from career_share.service import CareerShareService
from career_share.settings import load_db_settings

log = logging.getLogger("career_share")
_service: CareerShareService | None = None


def build_service() -> CareerShareService:
    """실제 환경 서비스 (DB 연결은 첫 쿼리 때 연다). psycopg/boto3는 여기서만 import한다."""
    from career_share.repository import PostgresCareerShareRepository, connect_for_lambda
    from repositories.db import Database
    return CareerShareService(PostgresCareerShareRepository(Database(connect_for_lambda)), SqsPublisher(),
                              load_db_settings())


def _get_service() -> CareerShareService:
    global _service
    if _service is None:
        _service = build_service()
    return _service


def _parse_scheduled(event: dict) -> datetime | None:
    """Scheduler가 넘기는 예약 시각 (배치 날짜 결정용). 없거나 형식이 틀리면 None (현재 시각의 날짜를 쓴다)."""
    scheduled = event.get("scheduled_at")
    if not scheduled:
        return None
    try:
        return contract.parse_time(scheduled)
    except contract.ContractError:
        log.warning("scheduled_at 형식 오류: 현재 시각의 날짜를 사용합니다.")
        return None


def handle_results(service: CareerShareService, event: dict) -> dict:
    failures = []
    for record in event.get("Records") or []:
        try:
            outcome = service.apply_result(record.get("body"))
            log.info("result %s -> %s", record.get("messageId"), outcome)
        except contract.ContractError as error:
            log.error("결과 메시지 형식 오류 id=%s: %s", record.get("messageId"), error)
            failures.append({"itemIdentifier": record.get("messageId")})
        except Exception as error:  # DB 일시 오류 등: 큐가 다시 전달한다
            log.error("결과 반영 실패 id=%s: %s", record.get("messageId"), type(error).__name__)
            failures.append({"itemIdentifier": record.get("messageId")})
    return {"batchItemFailures": failures}


def handler(event, context=None, *, service: CareerShareService | None = None):
    service = service or _get_service()
    if isinstance(event, dict) and event.get("Records"):
        return handle_results(service, event)
    action = event.get("action") if isinstance(event, dict) else None
    now = datetime.now(timezone.utc)
    if action == "relay":
        return service.relay(now)
    if action == "digest":
        return service.digest(now, _parse_scheduled(event))
    if action == "baseline":
        return service.baseline()
    if action == "summary":
        return service.summary()
    raise ValueError(f"알 수 없는 이벤트: {json.dumps(action)[:40]}")


if os.environ.get("CAREER_SHARE_LOG_LEVEL"):
    logging.basicConfig(level=os.environ["CAREER_SHARE_LOG_LEVEL"])
