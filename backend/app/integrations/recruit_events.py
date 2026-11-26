"""공통 XP·디스코드 전달 인터페이스. 보상액과 회원 레벨은 이 모듈에서 계산하지 않는다."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RecognitionDecision:
    approved: bool
    policy_version: str
    evidence: str
    scope_key: str


class RecognitionPolicy(Protocol):
    """실제 참여·완료 판정 주체가 확정된 뒤 제공할 서버 내부 정책."""

    def evaluate(
        self, activity, member_id: int, recognition_kind: str
    ) -> RecognitionDecision: ...


class EventGateway(Protocol):
    """같은 event_key를 재전달해도 중복 처리하지 않고 확정된 외부 참조를 반환해야 한다.

    XP 어댑터는 policy_version·scope_key로 주간 한도/중복 보상을 검사해야 한다.
    네트워크 타임아웃을 설정하고 실패 시 예외를 발생시킨다. 빈 참조는 성공이 아니다.
    """

    def deliver(self, event_key: str, kind: str, payload: dict) -> str: ...
