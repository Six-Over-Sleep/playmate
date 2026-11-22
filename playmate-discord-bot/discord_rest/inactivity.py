"""비활성 모임 채널 판정 (순수 함수, discord.py / Gateway / 캐시에 의존하지 않는다).

`services/lifecycle._check_meeting`의 판정 순서를 그대로 옮겼다 (그 함수는 Discord 객체와 DB 쓰기가 섞여 있어
그대로 부를 수 없다). 같은 결과인지는 tests/test_discord_rest.py가 기존 `_check_meeting`과 직접 비교한다
(경고 여부, 삭제 예약 시각, 예약 시각 도래 후의 삭제/취소 분기 포함).
정책 값(7일, 24시간)은 인자로 받는다: config를 import하지 않아야 DB/토큰 없이 쓸 수 있다.

== 인터페이스 계약 (삭제 안전) ==
채널 삭제는 되돌릴 수 없으므로 **활동이 없다고 "확인된" 경우에만** 허용한다. 확인할 수 없는 모든 경우는 삭제 금지다.
  * decide_action()의 결과가 DELETE_DUE여도 곧바로 삭제하면 안 된다. 삭제 직전에 최근 메시지를 REST로 다시 조회하고
    check_activity_for_deletion()의 결과가 NO_ACTIVITY일 때만 삭제한다.
  * ACTIVE(활동 발견)와 UNKNOWN(확인 불가)은 둘 다 "삭제하지 않음"이다. UNKNOWN은 다음 주기에 다시 확인한다.
  * 메시지 조회 자체가 실패했거나(예외, 권한, 시간 초과) 응답이 비정상이면 호출자는 messages=None으로 넘긴다.
  * Discord는 봇에 READ_MESSAGE_HISTORY가 없으면 오류 없이 빈 목록을 돌려준다(공식 문서). 그래서 빈 목록은
    "활동 없음"이 아니다. 채널의 last_message_id를 함께 넘겨 교차 확인한다.
모든 datetime은 시간대(tz)가 있어야 한다 (naive는 ValueError). 기존 코드의 시각(KST 등)도 모두 aware다.
"""
from datetime import datetime, timedelta, timezone

# decide_action 결과
SKIP_DELETED = "skip_deleted"        # 이미 삭제 기록됨
WAIT_DELETE = "wait_delete"          # 삭제 예약 시각 전
DELETE_DUE = "delete_due"            # 예약 시각이 지났고 경고 이후 기록된 활동 없음: 삭제 직전 재확인 단계로
CANCEL_SCHEDULE = "cancel_schedule"  # 예약 시각이 지났지만 경고 이후 활동이 기록됨: 삭제하지 않고 예약 취소
HOLD = "hold"                        # 예약은 있는데 경고 시각이 없는 비정상 상태: 삭제하지 않고 사람이 확인
NONE = "none"                        # 할 일 없음 (활동 기록 없음, 아직 기간 안 됨, 이미 경고함)
WARN = "warn"                        # 경고 메시지를 보내고 삭제를 예약

# check_activity_for_deletion 결과. NO_ACTIVITY만 삭제를 허용한다.
ACTIVE = "active"
NO_ACTIVITY = "no_activity"
UNKNOWN = "unknown"
# 삭제 대상이 "방금 만든 채널의 정리"처럼 비활성 정책과 무관한 경우를 호출자가 명시하는 값
ACTIVITY_NOT_APPLICABLE = "not_applicable"

_DISCORD_EPOCH_MS = 1420070400000
_UNSET = object()


class ActivityUnverifiable(ValueError):
    """메시지 목록이 비정상이라 활동 여부를 확인할 수 없다 (timestamp 누락/형식 오류 등). 삭제하지 말 것."""


def _require_aware(name: str, value) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name}은 시간대(tz)가 있는 datetime이어야 합니다.")
    return value


def decide_action(meeting: dict, now: datetime, *, inactivity_days: int, grace_hours: int) -> tuple[str, datetime | None]:
    """(행동, 삭제 예정 시각). 삭제 예정 시각은 WARN일 때만 값이 있다.

    meeting 키: last_activity_at, inactivity_warned_at, scheduled_delete_at, discord_deleted_at.
    값이 있는 시각은 모두 timezone 포함이어야 한다 (naive면 ValueError).
    """
    _require_aware("now", now)
    fields = {key: meeting.get(key) for key in
              ("last_activity_at", "inactivity_warned_at", "scheduled_delete_at", "discord_deleted_at")}
    for key, value in fields.items():
        if value is not None:
            _require_aware(key, value)
    if fields["discord_deleted_at"] is not None:
        return SKIP_DELETED, None
    scheduled = fields["scheduled_delete_at"]
    if scheduled is not None:
        if now < scheduled:
            return WAIT_DELETE, None
        warned, last_activity = fields["inactivity_warned_at"], fields["last_activity_at"]
        if warned is None:
            # 기존 _delete_checked: "경고/예약 상태가 사라져 삭제 취소" (record_warning은 둘을 함께 저장하므로 정상 상태가
            # 아니다). 경고 이후 활동을 비교할 기준이 없으니 삭제하지 않고 사람이 확인한다.
            return HOLD, None
        # 기존 _check_meeting: 예약 시각이 지나면 최신 상태를 다시 읽고, 경고 이후 활동이 있으면 예약을 취소한다.
        if last_activity is not None and last_activity > warned:
            return CANCEL_SCHEDULE, None
        return DELETE_DUE, None
    last_activity = fields["last_activity_at"]
    if last_activity is None:
        return NONE, None
    if now - last_activity < timedelta(days=inactivity_days):
        return NONE, None
    if fields["inactivity_warned_at"] is not None:
        return NONE, None
    return WARN, now + timedelta(hours=grace_hours)


def parse_discord_time(value: str) -> datetime:
    """Discord ISO8601 시각(예: 2026-11-21T03:04:05.123000+00:00)을 timezone 포함 datetime으로."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def snowflake_time(snowflake) -> datetime:
    """Discord ID(snowflake)에 들어 있는 생성 시각 (UTC)."""
    return datetime.fromtimestamp(((int(snowflake) >> 22) + _DISCORD_EPOCH_MS) / 1000, tz=timezone.utc)


def _message_time(message) -> datetime:
    if not isinstance(message, dict):
        raise ActivityUnverifiable("메시지가 객체가 아닙니다.")
    stamp = message.get("timestamp")
    if not isinstance(stamp, str) or not stamp:
        raise ActivityUnverifiable("메시지에 timestamp가 없습니다.")
    try:
        return parse_discord_time(stamp)
    except ValueError:
        raise ActivityUnverifiable("메시지 timestamp 형식이 올바르지 않습니다.") from None


def latest_user_message_at(messages: list[dict], since: datetime, tz: timezone | None = None) -> datetime | None:
    """REST 최근 메시지(최신순) 중 `since` 이후 봇이 아닌 사용자의 최신 메시지 시각. 없으면 None.

    `lifecycle._latest_user_message_at`과 같은 규칙이다: since 이하가 나오면 중단, 봇(및 다른 봇) 메시지는 건너뜀.
    본문(content)은 읽지 않는다 (message content 권한이 없어도 author와 timestamp만으로 판정한다).
    목록이 list가 아니거나 판정에 필요한 메시지의 timestamp가 없으면 ActivityUnverifiable (삭제 금지 신호).
    **None 반환은 "목록 안에 사용자 활동이 없다"일 뿐 "채널에 활동이 없다"가 아니다.** 삭제 판단에는
    check_activity_for_deletion을 쓴다.
    """
    _require_aware("since", since)
    if not isinstance(messages, list):
        raise ActivityUnverifiable("메시지 목록이 list가 아닙니다.")
    for message in messages:
        created = _message_time(message)
        if created <= since:
            return None
        if not (message.get("author") or {}).get("bot", False):
            return created.astimezone(tz) if tz else created
    return None


def check_activity_for_deletion(messages: list[dict] | None, since: datetime, *, limit: int,
                                last_message_id=_UNSET) -> str:
    """삭제 직전 확인: ACTIVE / NO_ACTIVITY / UNKNOWN. **NO_ACTIVITY일 때만 삭제를 허용한다.**

    messages: get_recent_messages(channel_id, limit)의 결과. 조회에 실패했으면 None.
    since:    경고 시각 (이후의 사용자 메시지가 있으면 삭제를 취소해야 한다).
    limit:    조회에 사용한 limit.
    last_message_id: GET /channels/{id}의 last_message_id (메시지가 한 번도 없으면 None). 빈 목록이 "정말 메시지가 없음"인지
              "권한 때문에 안 보임"인지 가르는 데 쓴다. 넘기지 않으면 빈 목록은 UNKNOWN이다.

    UNKNOWN인 경우 (모두 삭제 금지):
      - messages가 None이거나 list가 아니다 (조회 실패)
      - 메시지에 timestamp가 없거나 형식이 틀렸고, 최신순 정렬이 아니다
      - 빈 목록인데 last_message_id를 모르거나, last_message_id가 since 이후 메시지를 가리킨다 (권한 문제로 숨겨진 것)
      - 조회한 메시지가 limit개로 가득 찼고 전부 since 이후의 봇 메시지라 그보다 오래된 사용자 메시지를 못 봤다
    (기존 lifecycle._latest_user_message_at은 마지막 경우를 '활동 없음'으로 보지만, 이 함수는 더 보수적이다.)
    """
    _require_aware("since", since)
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("limit은 1 이상의 정수여야 합니다.")
    if not isinstance(messages, list):
        return UNKNOWN
    try:
        times = [_message_time(message) for message in messages]
        latest = latest_user_message_at(messages, since)
    except ActivityUnverifiable:
        return UNKNOWN
    if any(newer > older for older, newer in zip(times, times[1:])):
        return UNKNOWN  # 최신순이 아니면 "since 이하가 나오면 중단"하는 판정을 믿을 수 없다
    if latest is not None:
        return ACTIVE
    if not messages:
        if last_message_id is _UNSET:
            return UNKNOWN
        if last_message_id is None:
            return NO_ACTIVITY  # 채널에 메시지가 한 번도 없음
        try:
            return NO_ACTIVITY if snowflake_time(last_message_id) <= since else UNKNOWN
        except (TypeError, ValueError, OverflowError, OSError):
            return UNKNOWN
    if any(created <= since for created in times):
        return NO_ACTIVITY  # since까지 거슬러 올라가 확인했다
    return UNKNOWN if len(messages) >= limit else NO_ACTIVITY
