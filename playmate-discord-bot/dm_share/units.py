"""DM 작업 단위와 Discord 오류 코드 (순수 상수·함수, Issue #182에서 repositories.dm_delivery_repository로부터 분리).

DM Worker Lambda(VPC 밖, DB 없음)가 DB 저장소 모듈 없이 쓸 수 있게 따로 둔다. DB·discord.py·config를 import하지 않는다.
값과 동작은 분리 전과 같다. repositories.dm_delivery_repository가 같은 이름으로 다시 내보내므로 기존 import 경로도 그대로 동작한다.
"""

DM_BLOCKED_CODE = 50007                 # Cannot send messages to this user
USER_GONE_CODES = (10013, 50033)        # Unknown user / Invalid recipient (공식 문서 코드. HTTP 상태는 실환경 미확인)


def dm_unit_id(notification_id: int) -> str:
    return f"dm-{int(notification_id)}"


def notification_id_of(unit_id) -> int | None:
    if isinstance(unit_id, str) and unit_id.startswith("dm-") and unit_id[3:].isdigit():
        return int(unit_id[3:])
    return None
