"""프로젝트 루트에서 python -m backend.app.jobs.run_recruit_scheduler로 실행한다."""

import argparse
import logging
import signal
from threading import Event

from backend.app.core.recruit_config import RecruitSchedulerSettings


def run_cycle(session_factory):
    """매 주기 세션을 반환한다. Outbox 전송기는 구성하거나 호출하지 않는다."""
    from backend.app.repositories.recruit_program_repository import ProgramRepository
    from backend.app.services.recruit_program_service import ProgramService

    failures = []
    with session_factory() as session:
        service = ProgramService(ProgramRepository(session))
        processed = service.tick(on_error=failures.append)
    return processed, len(failures)


def run_scheduler(session_factory, settings, stop, once=False):
    """실패 주기에는 재시도 간격을 사용하고, 대기 중 종료 요청에는 즉시 반응한다."""
    logger = logging.getLogger(__name__)
    while not stop.is_set():
        try:
            processed, failed = run_cycle(session_factory)
            logger.info("모임 예약 처리 processed=%s failed=%s", processed, failed)
        except Exception as error:
            # 연결 장애도 다음 주기에 새 세션으로 재시도하며 비밀값은 출력하지 않는다.
            failed = 1
            logger.error("모임 예약 주기 실패 error_type=%s", type(error).__name__)
        if once:
            return 1 if failed else 0
        delay = settings.retry_seconds if failed else settings.interval_seconds
        stop.wait(delay)
    return 0


def main(argv=None):
    """기존 DB 설정을 읽되 DDL·상시 실행 등록·외부 전송은 수행하지 않는다."""
    parser = argparse.ArgumentParser(description="모임 상태 변경 전용 예약 실행")
    parser.add_argument("--once", action="store_true", help="한 주기 실행 후 종료")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    # 기존 설정 모듈이 루트 .env를 읽는다. 설정 파일과 공통 연결 코드는 수정하지 않는다.
    from backend.app.core.database import SessionLocal, engine

    try:
        settings = RecruitSchedulerSettings.from_environment()
    except ValueError as error:
        parser.error(str(error))
    stop = Event()
    previous = {}

    def request_stop(signum, frame):
        stop.set()

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, request_stop)
        return run_scheduler(SessionLocal, settings, stop, args.once)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
