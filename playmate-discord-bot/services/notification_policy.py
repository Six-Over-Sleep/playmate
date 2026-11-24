"""댓글·대댓글 DM의 순수 규칙 (Issue #171에서 notification_service로부터 분리).

discord.py와 config를 import하지 않는다: Gateway Bot(services.notification_service)과 DM Lambda(dm_share)가 함께 쓴다.
기존 동작은 그대로다 (notification_service가 같은 이름으로 다시 내보낸다).
"""
from typing import Any, Mapping


def dm_allowed(opt_in: bool | None) -> bool:
    """기본 ON: 사용자가 직접 끈 false만 미허용이다. true와 NULL(아직 선택하지 않음)은 허용한다."""
    return opt_in is not False


DM_MESSAGES = {
    "COMMENT": "💬 내 게시글에 새 댓글이 달렸어요.",   # 받는 사람: 게시글 작성자
    "REPLY": "↪️ 내 댓글에 새 답글이 달렸어요.",       # 받는 사람: 부모 댓글 작성자
}


LINK_LABEL = "🔗 PlayMate에서 보기"


def build_dm_message(notification: Mapping[str, Any], url: str | None = None) -> str | None:
    """알림 종류에 맞는 DM 문구. 아직 지원하지 않는 종류(REACTION 등)면 None (SKIPPED 처리).

    url이 있으면 마지막 줄에 원본 게시글 링크를 붙인다. 제목과 문구, 보낼 대상은 링크와 무관하게 같다.
    """
    message = DM_MESSAGES.get(notification["notification_type"])
    if message is None:
        return None
    title = (notification.get("post_title") or "").strip()
    text = f"{message}\n게시글: {title}" if title else message
    return f"{text}\n{LINK_LABEL}: {url}" if url else text


def to_discord_id(value) -> int | None:
    """members.discord_id(varchar)를 Discord 사용자 ID로. 숫자가 아니면(탈퇴 시 'w<member_id>') None."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def skip_reason(notification: Mapping[str, Any]) -> str | None:
    """DM을 보내지 않아야 하는 이유. 보내야 하면 None."""
    if notification["actor_member_id"] == notification["receiver_member_id"]:
        return "본인 알림"
    if notification.get("target_missing"):
        return "대상 없음"
    if not dm_allowed(notification.get("receiver_dm_opt_in")):
        return "DM 알림 꺼짐"
    if to_discord_id(notification.get("receiver_discord_id")) is None:
        return "Discord 계정 없음"
    if build_dm_message(notification) is None:
        return f"지원하지 않는 알림 종류: {notification['notification_type']}"
    return None
