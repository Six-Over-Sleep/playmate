"""기존 Gateway Bot 코드 중 Discord 객체에 의존하지 않는 부분을 REST 데이터에 연결하는 어댑터.

이 모듈만 기존 모듈(`services.*`, `config`)을 import한다. `config`는 import 시점에 DISCORD_BOT_TOKEN과
DISCORD_GUILD_ID 환경변수를 요구하므로 (Lambda에는 있다) 테스트에서는 먼저 가짜 값을 넣어야 한다.
REST 클라이언트 자체(discord_rest.client)는 이 모듈과 무관하게 config 없이 쓴다.

기존 코드를 고치지 않고 그대로 호출하는 것들:
    DM 문구/건너뜀 판정     services.notification_service.build_dm_message, NotificationService.skip_reason
    게시글 링크            services.web_links.notification_post_url
    HOT / 취업 공지 메시지   services.hot_content_service.build_hot_embed, services.career_notice_service.build_notice_embed
    모임 권한 판정          services.db_sync._joined_ok, _revoked_ok  (REST overwrite를 discord.py 값 객체로 바꿔서 입력)
    모임 채널 주제 표지      services.meeting_space.channel_topic
"""
from collections import namedtuple
from datetime import datetime
from typing import Any

import discord

import config
from discord_rest import inactivity
from discord_rest.errors import DiscordAuthError, DiscordError, DiscordForbidden, DiscordNotFound
from services.career_notice_service import build_notice_embed
from services.db_sync import _joined_ok, _revoked_ok
from services.hot_content_service import build_hot_embed
from services.meeting_space import channel_topic
from services.notification_service import NotificationService, build_dm_message
from services.web_links import notification_post_url

DmPlan = namedtuple("DmPlan", "skip_reason discord_id text")


# -- DM ---------------------------------------------------------------------------
def plan_dm(notification: dict, base_url: str | None = config.WEB_BASE_URL) -> DmPlan:
    """알림 한 건을 REST로 보낼 DM으로 바꾼다. skip_reason이 있으면 보내지 않고 SKIPPED로 기록할 대상이다.

    `NotificationService.deliver`의 앞부분(건너뜀 판정, 문구, 링크)과 같은 규칙이며 Discord 호출만 뺐다.
    링크를 만들지 못해도 DM은 막지 않는다 (링크 없는 문구로 보낸다).
    """
    reason = NotificationService.skip_reason(notification)
    if reason is not None:
        return DmPlan(reason, None, None)
    url = None
    if base_url:
        try:
            url = notification_post_url(base_url, notification)
        except Exception:
            url = None
    return DmPlan(None, int(str(notification["receiver_discord_id"]).strip()), build_dm_message(notification, url))


# -- HOT / 취업 공지 -----------------------------------------------------------------
def hot_message_payload(content_type: str, content: dict[str, Any], url: str | None) -> dict:
    """HOT PLAYMATE 게시용 REST 본문(embeds)."""
    return {"embeds": [build_hot_embed(content_type, content, url).to_dict()]}


def career_notice_payload(post: dict[str, Any], url: str) -> dict:
    """취업 신규 글 공지용 REST 본문 (제목과 링크만, 멘션 없음)."""
    return {"embeds": [build_notice_embed(post, url).to_dict()], "allowed_mentions": {"parse": []}}


# -- 모임 권한 판정 --------------------------------------------------------------------
class _ChannelView:
    """기존 판정 함수가 읽는 `.overwrites`만 가진 값 객체 (Guild/Channel 캐시가 아니다)."""

    def __init__(self, overwrites: dict):
        self.overwrites = overwrites


def channel_view(channel_json: dict) -> _ChannelView:
    """REST 채널 JSON(permission_overwrites)을 기존 `_joined_ok` / `_revoked_ok`가 읽는 형태로 바꾼다."""
    overwrites = {}
    for entry in channel_json.get("permission_overwrites") or []:
        kind = discord.Role if entry.get("type") == 0 else discord.Member
        target = discord.Object(id=int(entry["id"]), type=kind)
        overwrites[target] = discord.PermissionOverwrite.from_pair(
            discord.Permissions(int(entry.get("allow") or 0)), discord.Permissions(int(entry.get("deny") or 0)))
    return _ChannelView(overwrites)


def joined_ok(channel_json: dict, discord_id: int) -> bool:
    """JOINED 목표 상태(보기/읽기/쓰기 허용)인가. 기존 `db_sync._joined_ok` 그대로."""
    return _joined_ok(channel_view(channel_json), discord_id)


def revoked_ok(channel_json: dict, discord_id: int, visibility: str = "PUBLIC") -> bool:
    """CANCELED 목표 상태(쓰기 권한 없음)인가. 기존 `db_sync._revoked_ok` 그대로."""
    return _revoked_ok(channel_view(channel_json), discord_id, visibility)


# -- 비활성 판정 -----------------------------------------------------------------------
def decide_inactivity(meeting: dict, now: datetime) -> tuple[str, datetime | None]:
    """config의 정책(INACTIVITY_DAYS, INACTIVITY_GRACE_HOURS)으로 비활성 행동을 정한다."""
    return inactivity.decide_action(meeting, now, inactivity_days=config.INACTIVITY_DAYS,
                                    grace_hours=config.INACTIVITY_GRACE_HOURS)


# -- 모임 채널 식별 / 안전 삭제 ---------------------------------------------------------
def topic_marker(recruit_id: int) -> str:
    """삭제 전에 "이 채널이 정말 이 모임의 채널인지" 확인하는 주제 접두어 (`delete_meeting_channel`과 같은 값)."""
    return f"PlayMate 모임 #{recruit_id} "


def meeting_topic(recruit_id: int, visibility: str = "PUBLIC") -> str:
    return channel_topic(recruit_id, visibility)


def find_meeting_channels(channels: list[dict], recruit_id: int) -> list[dict]:
    """list_guild_channels 결과에서 이 모임의 텍스트 채널을 찾는다.

    채널 생성 응답을 잃었을 때(outcome_unknown) 이미 만들어졌는지 확인하는 용도다. 2개 이상이면 중복 생성 신호다.
    """
    marker = topic_marker(recruit_id)
    return [c for c in channels if c.get("type") == 0 and (c.get("topic") or "").startswith(marker)]


def safe_delete_meeting_channel(client, channel_id: int, recruit_id: int, protected_ids=frozenset()) -> bool:
    """기존 `meeting_space.delete_meeting_channel`과 같은 안전 확인 후 채널 하나만 삭제한다 (REST, 캐시 없음).

    보호 목록, 텍스트 채널 여부, 주제 표지를 확인한다. 반환: 삭제됐거나 이미 없으면 True, 지우지 않았거나 실패면 False.
    인증 오류(401)는 설정 문제라 삼키지 않고 올린다. 호출자는 반환값을 믿지 말고 다시 조회해 확인해야 한다.
    """
    if channel_id in protected_ids:
        return False
    try:
        channel = client.get_channel(channel_id)
    except DiscordNotFound:
        return True
    except DiscordAuthError:
        raise
    except DiscordError:
        return False
    if channel.get("type") != 0:
        return False
    if not (channel.get("topic") or "").startswith(topic_marker(recruit_id)):
        return False
    try:
        client.delete_channel(channel_id, reason="PlayMate 모임 채널 비활성 삭제", missing_ok=True)
    except DiscordAuthError:
        raise
    except (DiscordForbidden, DiscordError):
        return False
    return True
