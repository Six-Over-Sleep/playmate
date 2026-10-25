"""모임 Discord 채널을 만들고 삭제한다. 모임 하나에 채널 하나이며, 모임별 Category는 만들지 않는다.

모임 채널은 공용 카테고리(config.MEETING_CATEGORY_NAME) 아래에 만든다. 모임 이름은 식별자가 아니므로
채널은 항상 recruit_id와 저장된 Discord 채널 ID로 구분한다.
"""
import discord

from config import MEETING_CATEGORY_CHANNEL_LIMIT, MEETING_CATEGORY_NAME

# 참여자 권한 (텍스트 채널). db_sync가 목표 상태를 확인할 때도 같은 세트를 쓴다.
# HOST도 일반 참여자와 같다. 채널 구조를 바꾸는 권한(manage_channels 등)은 누구에게도 주지 않는다.
PARTICIPANT_PERMISSIONS = dict(
    view_channel=True, read_message_history=True, send_messages=True,
)


def participant_overwrite() -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(**PARTICIPANT_PERMISSIONS)


def channel_topic(recruit_id: int, visibility: str = "PUBLIC") -> str:
    """채널 주제. 삭제 직전에 "이 채널이 정말 이 모임의 채널인지" 확인하는 표지로도 쓴다."""
    return f"PlayMate 모임 #{recruit_id} ({visibility})"


async def ensure_meeting_category(guild: discord.Guild) -> discord.CategoryChannel:
    """모임 채널을 넣을 공용 카테고리를 찾고, 없으면 만든다.

    Discord 카테고리는 채널 50개가 한도라서, 가득 차면 "모임별 채널 2", "모임별 채널 3"처럼
    공용 카테고리를 늘린다. 이것은 모임별 Category가 아니라 모든 모임이 함께 쓰는 묶음이다.
    """
    index = 1
    while True:
        name = MEETING_CATEGORY_NAME if index == 1 else f"{MEETING_CATEGORY_NAME} {index}"
        category = discord.utils.get(guild.categories, name=name)
        if category is None:
            category = await guild.create_category(name=name)
            print(f'모임 공용 카테고리 생성: {name} (ID: {category.id})')
            return category
        if len(category.channels) < MEETING_CATEGORY_CHANNEL_LIMIT:
            return category
        index += 1


async def create_meeting_channel(
    guild: discord.Guild,
    meeting_name: str,
    recruit_id: int,
    participant_ids: list[int] | None = None,
    visibility: str = "PUBLIC",
) -> discord.TextChannel:
    """모임 텍스트 채널 하나를 만들고 최종 참여자에게 권한을 준다. 음성 채널은 만들지 않는다.

    입력:
        participant_ids: 최종 참여자의 Discord 사용자 ID (HOST 포함). 서버에서 찾지 못한
            사용자는 로그만 남기고 건너뛴다.
        visibility: PUBLIC은 비참여자도 보기/읽기 가능(쓰기 불가), PRIVATE은 비참여자에게 안 보임.
    실패 처리: 채널 생성이 실패하면 예외를 그대로 올린다 (만든 것이 없으므로 정리할 것도 없다).
        공용 카테고리는 다른 모임도 쓰므로 실패해도 지우지 않는다.
    """
    visibility = visibility.upper()
    if visibility not in ('PUBLIC', 'PRIVATE'):
        raise ValueError('visibility은 PUBLIC 또는 PRIVATE여야 합니다.')
    if visibility == 'PUBLIC':
        # 비참여자: 보기/읽기만 가능, 쓰기 불가
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True, read_message_history=True, send_messages=False,
            )
        }
    else:
        # 비참여자: 채널이 보이지 않음
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False, read_message_history=False, send_messages=False,
            )
        }
    for participant_id in participant_ids or []:
        try:
            member = await guild.fetch_member(participant_id)
        except discord.NotFound:
            print(f'참여자를 찾을 수 없음: {participant_id}')
            continue
        except discord.Forbidden:
            print(f'참여자 조회 권한 없음: {participant_id}')
            continue
        overwrites[member] = participant_overwrite()
    category = await ensure_meeting_category(guild)
    channel = await guild.create_text_channel(
        name=meeting_name,
        category=category,
        topic=channel_topic(recruit_id, visibility),
        overwrites=overwrites,
    )
    print(f'모임 채널 생성 완료: {channel.name} (ID: {channel.id}, recruit_id={recruit_id})')
    return channel


async def resolve_channel(guild: discord.Guild, channel_id: int):
    """캐시, 없으면 API로 채널을 찾는다: ("present", 채널) / ("gone", None) / ("unknown", None).

    API가 NotFound를 돌려준 경우만 "gone"이다. 캐시 미스나 불명확한 응답은 "unknown"(재시도 대상).
    """
    try:
        cached = guild.get_channel(channel_id)
        if cached is not None:
            return "present", cached
        return "present", await guild.fetch_channel(channel_id)
    except discord.NotFound:
        return "gone", None
    except Exception:
        return "unknown", None


async def delete_meeting_channel(
    guild: discord.Guild,
    channel_id: int,
    recruit_id: int,
    protected_ids=frozenset(),
    should_abort=None,
) -> bool:
    """저장된 채널 ID 하나만 삭제한다. 카테고리나 다른 채널은 절대 지우지 않는다.

    공식 서버에는 모임과 무관한 채널이 많으므로 삭제 전에 안전 확인을 한다:
        1. 보호 목록(상시 오픈채팅 등)에 있는 채널이면 삭제하지 않는다.
        2. 텍스트 채널이 아니면(카테고리, 음성 등) 삭제하지 않는다.
        3. 채널 주제가 이 모임(recruit_id)의 표지로 시작하지 않으면 삭제하지 않는다
           (DB의 ID가 잘못되어 엉뚱한 채널을 지우는 일을 막는다).
    should_abort: 안전 확인을 모두 마친 뒤 `channel.delete()`를 부르기 직전에 한 번 더 호출되는 동기 함수.
    True를 돌려주면 삭제하지 않는다 (그 사이 사용자 활동이 감지된 경우 등).
    반환: 채널이 삭제되었거나 이미 없으면 True, 삭제하지 않았거나 실패했으면 False.
    호출자는 반환값을 믿지 말고 API로 사라졌는지 따로 확인해야 한다.
    """
    if channel_id in protected_ids:
        print(f'보호된 채널이라 삭제하지 않음: {channel_id}')
        return False
    state, channel = await resolve_channel(guild, channel_id)
    if state == "gone":
        print(f'채널이 이미 삭제됨: {channel_id}')
        return True
    if state == "unknown":
        print(f'채널 조회가 불명확해 삭제하지 않음: {channel_id}')
        return False
    if getattr(channel, "type", None) is not discord.ChannelType.text:
        print(f'텍스트 채널이 아니라 삭제하지 않음: {channel_id}')
        return False
    marker = f"PlayMate 모임 #{recruit_id} "
    if not (getattr(channel, "topic", None) or "").startswith(marker):
        print(f'모임 채널 표지가 달라 삭제하지 않음: {channel_id} (recruit_id={recruit_id})')
        return False
    if should_abort is not None and should_abort():
        print(f'삭제 직전 활동이 감지되어 삭제하지 않음: {channel_id}')
        return False
    try:
        await channel.delete(reason='PlayMate 모임 채널 비활성 삭제')
        print(f'모임 채널 삭제 완료: {channel.name} (ID: {channel_id})')
        return True
    except discord.NotFound:
        print(f'채널이 이미 삭제됨: {channel_id}')
        return True
    except discord.Forbidden:
        print(f'채널 삭제 권한 없음: {channel_id}')
        return False
    except discord.HTTPException as error:
        print(f'채널 삭제 실패: {channel_id} / {error}')
        return False
