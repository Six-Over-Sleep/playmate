"""SQS 발행 어댑터. boto3는 실제 Lambda에서만 import한다 (로컬 테스트는 FakeQueue를 쓴다).

표준 큐(최소 1회 전달, 순서 보장 없음)를 가정한다. 같은 메시지가 두 번 오거나 순서가 바뀔 수 있으므로
수신 측(Worker, 결과 처리)은 멱등이어야 한다.
FIFO 큐(DM 발송 큐, Issue #182)는 group_id(MessageGroupId)와 dedup_id(MessageDeduplicationId)를 함께 넘긴다.
두 인자는 키워드 전용이고 기본값이 None이라, 기존 표준 큐 호출 send(url, body)는 바뀌지 않는다.
"""


class PublishError(RuntimeError):
    """발행 실패. 큐에 들어갔는지 알 수 없는 경우(타임아웃)도 포함한다."""


class SqsPublisher:
    def __init__(self, client=None):
        self._client = client

    def send(self, queue_url: str, body: str, *, group_id: str | None = None, dedup_id: str | None = None) -> None:
        params = {"QueueUrl": queue_url, "MessageBody": body}
        if group_id is not None:
            params["MessageGroupId"] = group_id
        if dedup_id is not None:
            params["MessageDeduplicationId"] = dedup_id
        try:
            if self._client is None:
                import boto3  # Lambda 런타임에 포함되어 있다
                self._client = boto3.client("sqs")
            self._client.send_message(**params)
        except Exception as error:  # botocore 예외 포함: 내용(URL/본문)은 넣지 않는다
            raise PublishError(f"SQS 발행 실패: {type(error).__name__}") from None


class FakeQueue:
    """테스트용. fail_next>0이면 그 횟수만큼 발행이 실패한다.

    dedup_id가 주어지면 같은 큐에서 같은 dedup_id는 한 번만 넣는다 (SQS FIFO 중복 제거 흉내, 시간 창은 없음).
    """

    def __init__(self):
        self.messages: list[tuple[str, str]] = []
        self.fifo: list[dict] = []          # FIFO 인자를 받은 발행 기록: {"url", "group_id", "dedup_id", "deduplicated"}
        self.fail_next = 0

    def send(self, queue_url: str, body: str, *, group_id: str | None = None, dedup_id: str | None = None) -> None:
        if self.fail_next > 0:
            self.fail_next -= 1
            raise PublishError("fake publish failure")
        if group_id is not None or dedup_id is not None:
            seen = any(r["url"] == queue_url and r["dedup_id"] == dedup_id and not r["deduplicated"] for r in self.fifo)
            self.fifo.append({"url": queue_url, "group_id": group_id, "dedup_id": dedup_id, "deduplicated": bool(dedup_id and seen)})
            if dedup_id and seen:
                return
        self.messages.append((queue_url, body))

    def bodies(self, queue_url: str | None = None) -> list[str]:
        return [body for url, body in self.messages if queue_url is None or url == queue_url]
