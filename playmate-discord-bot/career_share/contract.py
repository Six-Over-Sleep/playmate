"""Lambda/SQS 이벤트 계약 (JSON). 모든 메시지는 "최소 1회 전달"이므로 중복 도착해도 안전해야 한다 (exactly-once 아님).

DB Lambda -> [발송 큐] -> Discord Worker -> [결과 큐] -> DB Lambda

작업(job): {"v":1, "type":"send"|"verify", "job_id", "unit_id", "kind", "claim_token", "claimed_at", "not_after",
            "marker", "payload"(send만)}
  unit_id      post-<id> (즉시) / digest-<YYYY-MM-DD> (묶음). 메시지 하나의 식별자다.
  claim_token  DB가 선점할 때 만든 소유권 값. 결과는 이 값이 맞을 때만 반영된다.
  not_after    이 시각 이후에는 Worker가 **보내지 않는다** (큐에 오래 남은 작업이 뒤늦게 발송되는 것을 막아
               "이미 보내졌는지 확인한 뒤 재선점"이 안전하도록 한다).
결과(result): {"v":1, "type":"result", "job_id", "unit_id", "kind", "claim_token", "outcome", "message_id",
              "channel_id", "error", "completed_at"}
outcome:
  SENT              전송됨(또는 마커로 이미 전송된 것을 확인함). message_id 있음
  FAILED_RETRY      전송되지 않았음이 확실하고 나중에 재시도 가능 (429 소진, 연결 자체가 안 됨)
  FAILED_PERMANENT  전송되지 않았고 재시도해도 같다 (401/403/404/400). 사람이 설정을 고쳐야 한다
  EXPIRED           not_after가 지나 보내지 않았다 (전송되지 않았음이 확실)
  UNKNOWN           전송되었을 수도 있다 (5xx/타임아웃) 마커로 확인하지 못함. 자동 재발송 금지
  ABSENT_PROVEN     verify 전용: 조회 범위가 claimed_at 이전까지 닿았는데 마커가 없다 (전송되지 않았음이 증명됨)
  INCONCLUSIVE      verify 전용: 마커를 못 찾았지만 없다고 단정할 수 없다 (범위/권한)
"""
import json
import re
import secrets
from datetime import datetime, timezone

VERSION = 1
TYPE_SEND, TYPE_VERIFY, TYPE_RESULT = "send", "verify", "result"
OUTCOMES = ("SENT", "FAILED_RETRY", "FAILED_PERMANENT", "EXPIRED", "UNKNOWN", "ABSENT_PROVEN", "INCONCLUSIVE")
# hot-<id>: HOT 게시글 공유(hot_share, Issue #165). 같은 Worker 코드를 쓰되 별도 큐·채널·이력 테이블을 쓴다.
#   취업 공유 DB Lambda가 hot- 결과를 받아도 career_discord_announcements에 해당 batch_id가 없어 'ignored'로 끝난다.
# dm-<notification_id>: 댓글·대댓글 DM(dm_share, Issue #171). Worker마다 UNIT_PREFIXES로 자기 단위만 처리한다.
_UNIT = re.compile(r"^(post-\d{1,18}|digest-\d{4}-\d{2}-\d{2}|hot-\d{1,18}|dm-\d{1,18})$")


class ContractError(ValueError):
    """형식이 잘못된 이벤트. 다시 받아도 같으므로 재시도하지 않고 DLQ/로그로 보낸다."""


def new_token() -> str:
    return secrets.token_hex(12)


def iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("naive datetime 금지")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_time(text) -> datetime:
    try:
        value = datetime.fromisoformat(str(text))
    except ValueError as error:
        raise ContractError("시각 형식 오류") from error
    if value.tzinfo is None:
        raise ContractError("시각에 시간대가 없습니다.")
    return value.astimezone(timezone.utc)


def dumps(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def loads(body) -> dict:
    try:
        data = json.loads(body) if isinstance(body, (str, bytes)) else body
    except ValueError as error:
        raise ContractError("JSON이 아닙니다.") from error
    if not isinstance(data, dict) or data.get("v") != VERSION:
        raise ContractError("지원하지 않는 이벤트 버전입니다.")
    return data


def _common(data: dict) -> None:
    for key in ("job_id", "unit_id", "claim_token"):
        if not isinstance(data.get(key), str) or not data[key] or len(data[key]) > 120:
            raise ContractError(f"{key} 누락/오류")
    if not _UNIT.match(data["unit_id"]):
        raise ContractError("unit_id 형식 오류")


def validate_job(data: dict) -> dict:
    from career_share.messages import MARKER_PATTERN
    _common(data)
    if data.get("type") not in (TYPE_SEND, TYPE_VERIFY):
        raise ContractError("type 오류")
    for key in ("claimed_at", "not_after"):
        parse_time(data.get(key))
    if not MARKER_PATTERN.match(str(data.get("marker"))) or data["marker"] != f"ref:{data['unit_id']}":
        raise ContractError("marker가 unit_id와 맞지 않습니다.")
    if data["type"] == TYPE_SEND:
        payload = data.get("payload")
        if not isinstance(payload, dict) or not payload.get("embeds") or set(payload) - {"embeds", "allowed_mentions"}:
            raise ContractError("payload 오류")
        footers = [(e.get("footer") or {}).get("text") for e in payload["embeds"] if isinstance(e, dict)]
        if data["marker"] not in footers:
            raise ContractError("payload에 마커가 없습니다.")
    return data


def validate_result(data: dict) -> dict:
    _common(data)
    if data.get("type") != TYPE_RESULT or data.get("outcome") not in OUTCOMES:
        raise ContractError("result 형식 오류")
    if data["outcome"] == "SENT" and not re.fullmatch(r"\d{15,25}", str(data.get("message_id") or "")):
        raise ContractError("SENT에는 message_id가 필요합니다.")
    return data
