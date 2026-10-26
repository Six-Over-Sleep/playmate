"""모임 확장 API의 명시적 활성화 설정. 기존 .env를 수정하거나 DDL을 실행하지 않는다."""

import os


def programs_enabled():
    """마이그레이션 적용 후 운영자가 켠 경우에만 신규 쓰기 경로를 활성화한다."""
    return os.getenv("ENABLE_RECRUIT_PROGRAMS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
