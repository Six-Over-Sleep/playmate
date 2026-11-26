"""공유 상태 전이 (순수 함수). PostgreSQL 저장소와 메모리 저장소가 같은 규칙을 쓴다.

상태: PENDING(선점됨, 발송 큐 게시 여부 불명) -> SENT | FAILED | UNKNOWN
      UNKNOWN(전송되었을 수도 있음) -> SENT(마커 확인) | FAILED(미전송 증명됨) | UNKNOWN(그대로)
      FAILED -> (next_retry_at 이후, attempt_count < 한도) 재선점되어 PENDING
SENT는 끝 상태다. 결과가 중복 도착해도 SENT를 다른 상태로 바꾸지 않는다.
"""
from datetime import datetime, timedelta

PENDING, SENT, FAILED, UNKNOWN = "PENDING", "SENT", "FAILED", "UNKNOWN"

# (현재 상태, outcome) -> 새 상태. 표에 없으면 무시한다 (이미 처리됐거나 맞지 않는 늦은 결과).
_TRANSITIONS = {
    (PENDING, "SENT"): SENT, (UNKNOWN, "SENT"): SENT, (FAILED, "SENT"): SENT,
    (PENDING, "FAILED_RETRY"): FAILED, (PENDING, "FAILED_PERMANENT"): FAILED, (PENDING, "EXPIRED"): FAILED,
    (PENDING, "UNKNOWN"): UNKNOWN,
    (UNKNOWN, "ABSENT_PROVEN"): FAILED,   # 저장소가 absent_count가 한도에 이르렀을 때만 이 전이를 적용한다
    (UNKNOWN, "INCONCLUSIVE"): UNKNOWN,
}


def next_state(status: str, outcome: str) -> str | None:
    return _TRANSITIONS.get((status, outcome))


def retry_at(outcome: str, now: datetime, attempt_count: int, base_minutes: int) -> datetime | None:
    """FAILED로 바뀔 때의 다음 재시도 시각. None이면 자동 재시도하지 않는다."""
    if outcome == "FAILED_PERMANENT":
        return None
    if outcome in ("EXPIRED", "ABSENT_PROVEN"):
        return now  # 전송되지 않았음이 확실하다: 바로 다음 조회에서 다시 선점할 수 있다
    return now + timedelta(minutes=base_minutes * max(attempt_count, 1))
