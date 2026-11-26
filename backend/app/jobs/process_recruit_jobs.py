"""명시적으로 구성한 서비스만 실행한다. 실제 DB/외부 전송은 호출자가 선택한다."""

from backend.app.services.recruit_reward_service import RecruitOutboxService


def process_once(program_service, gateways=None):
    """상태 변경 후 영속 전달 요청을 처리한다. API 서버 시작 이벤트에는 등록하지 않는다."""
    processed = program_service.tick()
    delivered = RecruitOutboxService(program_service, gateways).dispatch()
    return {"processed_programs": processed, "delivered_events": delivered}
