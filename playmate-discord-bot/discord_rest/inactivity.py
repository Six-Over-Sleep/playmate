"""비활성 모임 채널 판정 (순수 함수, discord.py / Gateway / 캐시에 의존하지 않는다).

`services/lifecycle._check_meeting`의 판정 순서를 그대로 옮겼다 (그 함수는 Discord 객체와 DB 쓰기가 섞여 있어
그대로 부를 수 없다). 같은 결과인지는 tests/test_discord_rest.py가 기존 `_check_meeting`과 직접 비교한다.
정책 값(7일, 24시간)은 인자로 받는다: config를 import하지 않아야 DB/토큰 없이 쓸 수 있다.
"""
from datetime import datetime, timedelta, timezone

SKIP_DELETED = "skip_deleted"        # 이미 삭제 기록됨
WAIT_DELETE = "wait_delete"          # 삭제 예약 시각 전
DELETE_DUE = "delete_due"            # 예약 시각이 지남: 삭제 직전 확인 단계로
NONE = "none"                        # 할 일 없음 (활동 기록 없음, 아직 기간 안 됨, 이미 경고함)
WARN = "warn"                        # 경고 메시지를 보내고 삭제를 예약


def decide_action(meeting: dict, now: datetime, *, inactivity_days: int, grace_hours: int) -> tuple[str, datetime | None]:
    """(행동, 삭제 예정 시각). 삭제 예정 시각은 WARN일 때만 값이 있다.

    meeting 키: last_activity_at, inactivity_warned_at, scheduled_delete_at, discord_deleted_at (timezone 포함 시각).
    """
    if meeting.get("discord_deleted_at") is not None:
        return SKIP_DELETED, None
    scheduled = meeting.get("scheduled_delete_at")
    if scheduled is not None:
        return (WAIT_DELETE if now < scheduled else DELETE_DUE), None
    last_activity = meeting.get("last_activity_at")
    if last_activity is None:
        return NONE, None
    if now - last_activity < timedelta(days=inactivity_days):
        return NONE, None
    if meeting.get("inactivity_warned_at") is not None:
        return NONE, None
    return WARN, now + timedelta(hours=grace_hours)


def parse_discord_time(value: str) -> datetime:
    """Discord ISO8601 시각(예: 2026-11-21T03:04:05.123000+00:00)을 timezone 포함 datetime으로."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def latest_user_message_at(messages: list[dict], since: datetime, tz: timezone | None = None) -> datetime | None:
    """REST 최근 메시지(최신순) 중 `since` 이후 봇이 아닌 사용자의 최신 메시지 시각. 없으면 None.

    `lifecycle._latest_user_message_at`과 같은 규칙이다: since 이하가 나오면 중단, 봇(및 다른 봇) 메시지는 건너뜀.
    본문(content)은 읽지 않는다 (message content 권한이 없어도 author와 timestamp만으로 판정한다).
    """
    for message in messages:
        created = parse_discord_time(message["timestamp"])
        if created <= since:
            return None
        if not (message.get("author") or {}).get("bot", False):
            return created.astimezone(tz) if tz else created
    return None
