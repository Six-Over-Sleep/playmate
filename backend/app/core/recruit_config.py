"""모임 확장 API의 명시적 활성화 설정. 기존 .env를 수정하거나 DDL을 실행하지 않는다."""

import os
from dataclasses import dataclass


def programs_enabled():
    """마이그레이션 적용 후 운영자가 켠 경우에만 신규 쓰기 경로를 활성화한다."""
    return os.getenv("ENABLE_RECRUIT_PROGRAMS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass(frozen=True)
class RecruitSchedulerSettings:
    """반복 주기와 장애 재시도 간격. 잘못된 설정은 DB 연결 전에 거절한다."""

    interval_seconds: int = 60
    retry_seconds: int = 30

    @classmethod
    def from_environment(cls):
        """양의 정수만 허용해 무한 고속 반복과 조용한 설정 무시를 막는다."""
        values = []
        for name, default in (
            ("RECRUIT_SCHEDULER_INTERVAL_SECONDS", 60),
            ("RECRUIT_SCHEDULER_RETRY_SECONDS", 30),
        ):
            try:
                value = int(os.getenv(name, str(default)))
            except ValueError:
                raise ValueError(f"{name}는 양의 정수여야 합니다.") from None
            if value <= 0:
                raise ValueError(f"{name}는 양의 정수여야 합니다.")
            values.append(value)
        if not programs_enabled():
            raise ValueError("ENABLE_RECRUIT_PROGRAMS=true 설정이 필요합니다.")
        return cls(*values)
