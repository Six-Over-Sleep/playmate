"""SQS 발행 어댑터. boto3는 실제 Lambda에서만 import한다 (로컬 테스트는 FakeQueue를 쓴다).

표준 큐(최소 1회 전달, 순서 보장 없음)를 가정한다. 같은 메시지가 두 번 오거나 순서가 바뀔 수 있으므로
수신 측(Worker, 결과 처리)은 멱등이어야 한다.
"""


class PublishError(RuntimeError):
    """발행 실패. 큐에 들어갔는지 알 수 없는 경우(타임아웃)도 포함한다."""


class SqsPublisher:
    def __init__(self, client=None):
        self._client = client

    def send(self, queue_url: str, body: str) -> None:
        try:
            if self._client is None:
                import boto3  # Lambda 런타임에 포함되어 있다
                self._client = boto3.client("sqs")
            self._client.send_message(QueueUrl=queue_url, MessageBody=body)
        except Exception as error:  # botocore 예외 포함: 내용(URL/본문)은 넣지 않는다
            raise PublishError(f"SQS 발행 실패: {type(error).__name__}") from None


class FakeQueue:
    """테스트용. fail_next>0이면 그 횟수만큼 발행이 실패한다."""

    def __init__(self):
        self.messages: list[tuple[str, str]] = []
        self.fail_next = 0

    def send(self, queue_url: str, body: str) -> None:
        if self.fail_next > 0:
            self.fail_next -= 1
            raise PublishError("fake publish failure")
        self.messages.append((queue_url, body))

    def bodies(self, queue_url: str | None = None) -> list[str]:
        return [body for url, body in self.messages if queue_url is None or url == queue_url]
