"""DM 발송 큐 FIFO 발행 정책 (Issue #182). DM DB 계층의 발행만 감싼다 (취업·HOT 발행과 Worker 결과 발행은 그대로).

MessageGroupId = unit_id (dm-<알림 ID>)
  같은 알림의 작업(이전 선점의 작업, 재선점한 새 작업, 확인 작업)은 SQS가 한 번에 하나씩, 넣은 순서대로 Worker에 준다.
  앞 작업이 처리되어 삭제되거나 가시성 타임아웃이 지나야 다음 작업이 나온다. 서로 다른 알림은 병렬로 처리된다.
  -> R4(429 대기 중인 이전 작업과 60초 뒤 재선점한 새 작업이 동시에 처리되어 둘 다 마커를 못 찾는 경우)를
     예약 동시성 1 대신 그룹 직렬화로 막는다. 새 작업은 이전 작업이 끝난 뒤 마커를 찾는다.
MessageDeduplicationId = job_id
  발송 작업: dm-<id>:<claim_token>. 재선점할 때마다 claim_token이 바뀌므로 정당한 재시도는 지워지지 않고,
  같은 선점의 작업을 두 번 넣은 경우(발행 재시도 등)는 SQS가 5분 동안 하나로 본다.
  확인 작업: dm-<id>:<claim_token>:v<초>. 복구 주기마다 다르다.
  고정 값(예: unit_id)을 쓰면 5분 안의 정당한 재선점 작업까지 버려지므로 쓰지 않는다.
SQS FIFO 중복 제거는 **5분 창**에서만 동작한다. Discord 전송의 exactly-once를 보장하지 않는다 (DEPLOY.md 15.4).

큐 URL이 .fifo로 끝날 때만 FIFO 인자를 넘긴다 (표준 큐는 MessageDeduplicationId를 거부한다). 운영 설정은 load_dm_settings가 .fifo를 강제한다.
"""
import json
import re

from career_share import contract
from dm_share.units import notification_id_of

# SQS: MessageGroupId·MessageDeduplicationId는 1~128자, 영숫자와 구두점(!"#$%&'()*+,-./:;<=>?@[\]^_`{|}~)
_SQS_ID = re.compile(r"^[!-~]{1,128}$")


def fifo_attributes(job: dict) -> tuple[str, str]:
    """(MessageGroupId, MessageDeduplicationId). DM 작업이 아니거나 값이 SQS 규칙에 맞지 않으면 ContractError."""
    if not isinstance(job, dict) or job.get("kind") != "DM" or notification_id_of(job.get("unit_id")) is None:
        raise contract.ContractError("DM 작업이 아닙니다 (DM 발송 큐에는 DM 작업만 넣는다).")
    group, dedup = job["unit_id"], job.get("job_id")
    if not isinstance(dedup, str) or not _SQS_ID.match(group) or not _SQS_ID.match(dedup):
        raise contract.ContractError("FIFO 그룹·중복 제거 ID 형식 오류")
    if not dedup.startswith(group + ":"):
        raise contract.ContractError("job_id가 unit_id와 맞지 않습니다.")
    return group, dedup


class DmFifoPublisher:
    """DmShareService가 쓰는 발행기. 본문(작업 JSON)에서 그룹·중복 제거 ID를 계산해 내부 발행기에 넘긴다."""

    def __init__(self, inner):
        self.inner = inner

    def send(self, queue_url: str, body: str) -> None:
        job = json.loads(body)
        group, dedup = fifo_attributes(job)      # 표준 큐여도 DM 작업인지는 항상 확인한다
        if queue_url.endswith(".fifo"):
            self.inner.send(queue_url, body, group_id=group, dedup_id=dedup)
        else:
            self.inner.send(queue_url, body)
