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
from discord_rest.errors import DiscordAuthError, DiscordError, DiscordNotFound
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


def _positive_int(value, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name}은 양의 정수여야 합니다.")
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{name}은 양의 정수여야 합니다.") from None
    if number <= 0:
        raise ValueError(f"{name}은 양의 정수여야 합니다.")
    return number


def _protected_set(protected_ids) -> frozenset[int]:
    """보호 채널 ID 목록을 정수 집합으로 바꾼다. 문자열 ID(환경변수 등)도 받고, 잘못된 값은 거부한다."""
    if protected_ids is None or isinstance(protected_ids, (str, bytes)):
        raise ValueError("protected_ids는 채널 ID의 컬렉션이어야 합니다 (None, 문자열 불가).")
    try:
        return frozenset(_positive_int(item, "protected_ids 항목") for item in protected_ids)
    except TypeError:
        raise ValueError("protected_ids는 채널 ID의 컬렉션이어야 합니다.") from None


def safe_delete_meeting_channel(client, channel_id: int, recruit_id: int, *, guild_id: int, protected_ids,
                                activity: str, should_abort=None) -> bool:
    """기존 `meeting_space.delete_meeting_channel`의 보호 조건을 모두 유지하고 더 얹어 채널 하나만 삭제한다 (REST, 캐시 없음).

    기존과 같은 조건 (하나라도 어긋나면 삭제하지 않음): ① 보호 목록에 없음 ② 텍스트 채널(type 0) ③ 채널 주제가 이 모임
    표지로 시작 ④ should_abort()가 삭제 직전에 True가 아님.
    추가한 조건: ⑤ 조회한 채널 JSON의 id가 요청한 ID와 같음 ⑥ 채널의 guild_id가 지정한 guild_id와 같음 (다른 서버나
    guild_id가 없는 DM 채널은 거부) ⑦ activity가 삭제를 허용하는 값일 때만.

    인자 (모두 필수, 기본값 없음 → 빠뜨리면 TypeError. 보호 장치를 깜빡해 지우는 일을 막는다):
      guild_id      삭제를 허용할 서버 ID.
      protected_ids 지우면 안 되는 채널 ID 컬렉션 (상시 오픈채팅, HOT/취업 소식 채널 등. 문자열 ID도 가능). 빈 컬렉션도
                    허용하지만 **호출자가 의도적으로 넘겨야 한다.** Lambda에는 Gateway Bot의 PROTECTED_CHANNEL_IDS 같은
                    메모리 목록이 없으므로 설정에서 직접 구성해야 한다. 값이 잘못되면 ValueError.
      activity      inactivity.check_activity_for_deletion의 결과. **inactivity.NO_ACTIVITY일 때만** 삭제한다
                    (ACTIVE, UNKNOWN, 그 밖의 값은 REST 호출 없이 False). 비활성 정책과 무관한 정리(예: 방금 만든 채널의
                    롤백)는 inactivity.ACTIVITY_NOT_APPLICABLE를 명시한다.
    반환: 채널이 지금 없으면 True(삭제했거나 이미 없었음, 재시도 뒤 404 포함), 지우지 않았거나 삭제 여부가 불명확하면 False.
    삭제 요청이 5xx/타임아웃으로 끝난 경우는 False이며 "실패 확정"이 아니다: 호출자는 get_channel로 다시 확인해야 한다.
    인증 오류(401)는 설정 문제라 삼키지 않고 올린다. 락(meeting_lock)과 삭제 직전 활동 재확인은 호출자의 책임이다.
    """
    channel_id = _positive_int(channel_id, "channel_id")
    guild_id = _positive_int(guild_id, "guild_id")
    protected = _protected_set(protected_ids)
    if activity not in (inactivity.NO_ACTIVITY, inactivity.ACTIVITY_NOT_APPLICABLE):
        return False
    if channel_id in protected:
        return False
    try:
        channel = client.get_channel(channel_id)
    except DiscordNotFound:
        return True
    except DiscordAuthError:
        raise
    except DiscordError:
        return False
    if not isinstance(channel, dict) or str(channel.get("id")) != str(channel_id):
        return False
    if str(channel.get("guild_id")) != str(guild_id):
        return False
    if channel.get("type") != 0:
        return False
    if not (channel.get("topic") or "").startswith(topic_marker(recruit_id)):
        return False
    if should_abort is not None and should_abort():
        return False
    try:
        client.delete_channel(channel_id, reason="PlayMate 모임 채널 비활성 삭제", missing_ok=True)
    except DiscordAuthError:
        raise
    except DiscordError:
        return False  # 삭제 여부 불명확 (5xx/타임아웃/403 등): True로 확정하지 않는다
    return True
