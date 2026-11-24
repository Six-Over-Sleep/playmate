"""DM DB Lambda 핸들러 (VPC 안, PostgreSQL 접근). 결과 처리 함수는 career_share.db_lambda.handle_results를 그대로 쓴다.

  EventBridge Scheduler (1분, rate(1 minute))  {"action": "dm_relay"}    Gateway 만료 마감 + 공동 선점·발행 + 복구
  EventBridge Scheduler (롤백 중, 10분)        {"action": "dm_recover"}  신규 선점 없이 진행 중 건의 마커 확인·마감만
  결과 큐 (SQS 이벤트 소스 매핑)                {"Records": [...]}       결과 반영 (batchItemFailures 응답)
  수동                                          {"action": "dm_summary"}
"""
import json
import logging
import os
from datetime import datetime, timezone

from career_share.db_lambda import handle_results
from career_share.queues import SqsPublisher
from dm_share.service import DmShareService
from dm_share.settings import load_dm_settings

log = logging.getLogger("dm_share")
_service: DmShareService | None = None


def build_service() -> DmShareService:
    from career_share.repository import connect_for_lambda
    from repositories.db import Database
    from repositories.dm_delivery_repository import DmDeliveryRepository
    settings = load_dm_settings()
    # connect_for_lambda는 Gateway(connect_from_env)와 같은 TimeZone=Asia/Seoul이다: notifications의 CURRENT_TIMESTAMP 의미가 같다.
    repo = DmDeliveryRepository(Database(lambda: connect_for_lambda("playmate_dm_share")),
                                retry_seconds=settings.retry_seconds, max_attempts=settings.max_attempts)
    return DmShareService(repo, SqsPublisher(), settings)


def _get_service() -> DmShareService:
    global _service
    if _service is None:
        _service = build_service()
    return _service


def handler(event, context=None, *, service: DmShareService | None = None):
    service = service or _get_service()
    if isinstance(event, dict) and event.get("Records"):
        return handle_results(service, event)
    action = event.get("action") if isinstance(event, dict) else None
    now = datetime.now(timezone.utc)
    if action == "dm_relay":
        return service.relay(now)
    if action == "dm_recover":
        # 롤백용: 신규 선점 없이 진행 중 건의 확인·마감만 한다 (Gateway가 다시 보내는 동안 Lambda 쪽 마무리)
        return service.recover(now)
    if action == "dm_summary":
        return service.summary(now)
    raise ValueError(f"알 수 없는 이벤트: {json.dumps(action)[:40]}")


if os.environ.get("DM_SHARE_LOG_LEVEL"):
    logging.basicConfig(level=os.environ["DM_SHARE_LOG_LEVEL"])
