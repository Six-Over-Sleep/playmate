"""Lambda DM 본문: embed 카드 1개 (순수 함수). 기존 Gateway DM은 텍스트 형식을 그대로 쓴다.

  title       💬 내 게시글에 새 댓글이 달렸어요. / ↪️ 내 댓글에 새 답글이 달렸어요.   (services.notification_policy.DM_MESSAGES)
  description 게시글: {제목}  +  [🔗 PlayMate에서 보기](링크)                          (제목·링크가 없으면 그 줄은 없다)
  footer      ref:dm-{notification_id}   ← 중복 확인 마커. 사용자에게 작은 회색 글씨로 보인다.
작성자(닉네임), 댓글 본문은 넣지 않는다 (기존 텍스트 DM과 같은 정보). 멘션은 보내지 않는다.
"""
from career_share import messages as base
from repositories.dm_delivery_repository import dm_unit_id
from services.notification_policy import DM_MESSAGES, LINK_LABEL

DM_COLOR = 0x5865F2
TITLE_LIMIT = 200


def dm_payload(notification: dict, url: str | None) -> dict:
    """url이 비었거나 안전하지 않으면 링크 없이 만든다 (기존 Gateway처럼 링크 문제로 DM을 막지 않는다)."""
    heading = DM_MESSAGES.get(notification.get("notification_type"))
    if heading is None:
        raise ValueError("지원하지 않는 알림 종류")
    try:
        link = base.safe_url(url) if url else None
    except ValueError:
        link = None
    lines = []
    if (notification.get("post_title") or "").strip():
        lines.append(f"게시글: {base.markdown_title(notification['post_title'], TITLE_LIMIT)}")
    if link:
        lines.append(f"[{LINK_LABEL}]({link})")
    embed = {"title": heading, "color": DM_COLOR,
             "footer": {"text": base.marker_for(dm_unit_id(notification["notification_id"]))}}
    if lines:
        embed["description"] = "\n".join(lines)
    if link:
        embed["url"] = link
    base._check(embed)
    return {"embeds": [embed], "allowed_mentions": dict(base.NO_MENTIONS)}
