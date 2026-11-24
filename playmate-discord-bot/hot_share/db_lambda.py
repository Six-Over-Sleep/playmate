"""HOT DB Lambda 핸들러 (VPC 안, PostgreSQL 접근). career_share.db_lambda와 같은 형태이며 결과 처리 함수는 그대로 재사용한다.

  EventBridge Scheduler (5분, rate(5 minutes))  {"action": "hot_relay"}     baseline 확인 + 신규 HOT 선점·발행 + 복구
  결과 큐 (SQS 이벤트 소스 매핑)                 {"Records": [...]}          결과 반영 (batchItemFailures 응답)
  수동                                           {"action": "hot_baseline"} / {"action": "hot_summary"}
"""
import json
import logging
import os
from datetime import datetime, timezone

from career_share.db_lambda import handle_results
from career_share.queues import SqsPublisher
from hot_share.service import HotShareService
from hot_share.settings import load_hot_settings

log = logging.getLogger("hot_share")
_service: HotShareService | None = None


def build_service() -> HotShareService:
    from hot_share.repository import PostgresHotShareRepository, connect_for_lambda
    from repositories.db import Database
    settings = load_hot_settings()
    return HotShareService(PostgresHotShareRepository(Database(connect_for_lambda), settings.db_timezone), SqsPublisher(),
                           settings)


def _get_service() -> HotShareService:
    global _service
    if _service is None:
        _service = build_service()
    return _service


def handler(event, context=None, *, service: HotShareService | None = None):
    service = service or _get_service()
    if isinstance(event, dict) and event.get("Records"):
        return handle_results(service, event)
    action = event.get("action") if isinstance(event, dict) else None
    now = datetime.now(timezone.utc)
    if action == "hot_relay":
        return service.relay(now)
    if action == "hot_baseline":
        return service.baseline(now)
    if action == "hot_summary":
        return service.summary(now)
    raise ValueError(f"알 수 없는 이벤트: {json.dumps(action)[:40]}")


if os.environ.get("HOT_SHARE_LOG_LEVEL"):
    logging.basicConfig(level=os.environ["HOT_SHARE_LOG_LEVEL"])
