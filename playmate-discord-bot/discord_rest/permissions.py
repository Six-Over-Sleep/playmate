"""모임 채널 권한을 Discord REST 형식(allow/deny 비트)으로 표현한다. discord.py에 의존하지 않는다.

기존 `services/meeting_space.py`(PARTICIPANT_PERMISSIONS, create_meeting_channel)와
`services/permissions.py`(remove_participant_permissions)가 discord.py 객체로 하던 일과 같은 결과다.
같은 값인지는 tests/test_discord_rest.py가 기존 상수와 직접 비교해 확인한다.
"""

VIEW_CHANNEL = 1 << 10
SEND_MESSAGES = 1 << 11
READ_MESSAGE_HISTORY = 1 << 16

OVERWRITE_ROLE = 0
OVERWRITE_MEMBER = 1

PARTICIPANT_ALLOW = VIEW_CHANNEL | READ_MESSAGE_HISTORY | SEND_MESSAGES
_READ_ONLY = VIEW_CHANNEL | READ_MESSAGE_HISTORY


def _visibility(value: str) -> str:
    value = value.upper()
    if value not in ("PUBLIC", "PRIVATE"):
        raise ValueError("visibility은 PUBLIC 또는 PRIVATE여야 합니다.")
    return value


def overwrite(target_id: int, target_type: int, allow: int, deny: int) -> dict:
    """REST permission_overwrites 항목. Discord는 allow/deny를 문자열 비트필드로 주고받는다."""
    return {"id": str(target_id), "type": target_type, "allow": str(allow), "deny": str(deny)}


def participant_overwrite(user_id: int) -> dict:
    """참여자: 보기/읽기/쓰기 허용 (HOST도 같다. 채널 구조를 바꾸는 권한은 주지 않는다)."""
    return overwrite(user_id, OVERWRITE_MEMBER, PARTICIPANT_ALLOW, 0)


def everyone_overwrite(guild_id: int, visibility: str = "PUBLIC") -> dict:
    """@everyone 역할(ID는 길드 ID와 같다). PUBLIC은 읽기만, PRIVATE는 보이지 않음."""
    if _visibility(visibility) == "PUBLIC":
        return overwrite(guild_id, OVERWRITE_ROLE, _READ_ONLY, SEND_MESSAGES)
    return overwrite(guild_id, OVERWRITE_ROLE, 0, _READ_ONLY | SEND_MESSAGES)


def meeting_channel_overwrites(guild_id: int, participant_ids, visibility: str = "PUBLIC") -> list[dict]:
    """채널을 만들 때 함께 보내는 권한 목록. 같은 참여자가 중복되어도 한 번만 넣는다."""
    entries = [everyone_overwrite(guild_id, visibility)]
    seen: set[int] = set()
    for user_id in participant_ids or []:
        if user_id in seen:
            continue
        seen.add(user_id)
        entries.append(participant_overwrite(user_id))
    return entries


def revoked_permissions(visibility: str = "PUBLIC") -> tuple[int, int] | None:
    """참여 취소자의 목표 권한. PUBLIC은 (allow, deny)로 읽기만 허용, PRIVATE는 None(개인 overwrite 삭제)."""
    if _visibility(visibility) == "PUBLIC":
        return _READ_ONLY, SEND_MESSAGES
    return None
