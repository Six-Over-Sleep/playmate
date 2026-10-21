"""모임의 Discord 공간(카테고리, 채팅, 음성)을 만들고 삭제한다.

모임 이름은 식별자가 아니다. 공간은 항상 recruit_id와 저장된 Discord 리소스 ID로 구분한다.
"""
import discord

# 참여자 권한. 카테고리와 모든 채널에 같은 세트를 적용한다 (db_sync가 목표 상태 확인에도 쓴다).
PARTICIPANT_PERMISSIONS = dict(
    view_channel=True, read_message_history=True,
    send_messages=True, connect=True, speak=True,
)


def participant_overwrite() -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(**PARTICIPANT_PERMISSIONS)


class MeetingSpaceCleanupError(RuntimeError):
    """생성 실패 후 부분 생성물을 다 지우지 못했다 (`remaining_ids`).

    자동 재시도하면 남은 공간 위에 새 공간이 중복으로 만들어지므로 재시도하면 안 된다.
    """

    def __init__(self, cause: BaseException, remaining_ids: list[int]):
        super().__init__(f"{type(cause).__name__}: {cause}")
        self.cause = cause
        self.remaining_ids = remaining_ids


async def create_meeting_space(
    guild: discord.Guild,
    meeting_name: str,
    recruit_mode: str,
    visibility: str = "PUBLIC",
    participant_ids: list[int] | None = None,
    create_voice_channel: bool = True,
):
    """regular 모임의 공간(📁 모임명 / # ╔・채팅 / 🔊 ╚・음성)을 만든다. short는 만들지 않고 None.

    반환: (카테고리, 텍스트, 음성 또는 None). 중간에 실패하면 만든 리소스를 역순으로 지우고
    원래 예외를 올린다. 지우지도 못하면 MeetingSpaceCleanupError.
    """
    if recruit_mode == "short":
        print("short 모임은 Discord 공간을 생성하지 않습니다.")
        return None
    if recruit_mode != "regular":
        raise ValueError("recruit_mode는 'regular' 또는 'short'여야 합니다.")

    participant_ids = participant_ids or []
    visibility = visibility.upper()
    if visibility not in ('PUBLIC', 'PRIVATE'):
        raise ValueError('visibility은 PUBLIC 또는 PRIVATE여야 합니다.')
    if visibility == 'PUBLIC':
        # 비참여자: 보기/읽기만 가능, 쓰기와 음성 연결 불가
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True, read_message_history=True,
                send_messages=False, connect=False, speak=False,
            )
        }
    else:
        # 비참여자: 카테고리와 채널이 아예 보이지 않음
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False, read_message_history=False,
                send_messages=False, connect=False, speak=False,
            )
        }
    for participant_id in participant_ids:
        try:
            member = await guild.fetch_member(participant_id)
        except discord.NotFound:
            print(f'참여자를 찾을 수 없음: {participant_id}')
            continue
        except discord.Forbidden:
            print(f'참여자 조회 권한 없음: {participant_id}')
            continue
        overwrites[member] = participant_overwrite()
    category = await guild.create_category(name=meeting_name, overwrites=overwrites)
    print(f'모임 카테고리 생성 완료: {category.name} (ID: {category.id})')
    created = [category]
    try:
        text_channel = await guild.create_text_channel(
            name='╔・채팅', category=category, topic=f'[{visibility}] {meeting_name}'
        )
        created.append(text_channel)
        print(f'텍스트 채널 생성 완료: {text_channel.name} (ID: {text_channel.id})')
        voice_channel = None
        if create_voice_channel:
            voice_channel = await guild.create_voice_channel(name='╚・음성', category=category)
            created.append(voice_channel)
            print(f'음성 채널 생성 완료: {voice_channel.name} (ID: {voice_channel.id})')
        else:
            print('음성 채널 생성 안 함')
    except Exception as creation_error:
        # DB가 추적하지 못하는 반쪽짜리 공간을 남기지 않도록 만든 것을 역순으로 지운다.
        # 지우는 것까지 실패하면 남은 ID를 호출자에게 알려 맹목적인 재시도를 막는다.
        remaining = []
        for resource in reversed(created):
            try:
                await resource.delete(reason='PlayMate 모임 생성 실패 정리')
            except Exception as cleanup_error:
                print(f'생성 실패 정리 중 삭제 실패: {resource.id} / {cleanup_error}')
                remaining.append(resource.id)
        if remaining:
            raise MeetingSpaceCleanupError(creation_error, remaining) from creation_error
        raise
    return (category, text_channel, voice_channel)


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


async def resolve_space(guild: discord.Guild, category_id: int, channel_ids=()):
    """저장된 ID 기준으로 공간을 찾는다: (카테고리 상태, 대상 목록, 불명확 여부).

    대상은 카테고리, 그 하위 채널, 저장된 채널 ID 순서(중복 없음)다. 다른 카테고리로 옮겨진
    채널도 ID로 찾아 권한 변경이 놓치지 않게 한다. NotFound는 불명확으로 보지 않는다.
    """
    category_state, category = await resolve_channel(guild, category_id)
    unresolved = category_state == "unknown"
    targets = []
    seen = set()
    if category is not None:
        targets.append(category)
        seen.add(category.id)
        for channel in category.channels:
            if channel.id not in seen:
                targets.append(channel)
                seen.add(channel.id)
    for channel_id in channel_ids:
        if channel_id is None or channel_id in seen:
            continue
        seen.add(channel_id)
        state, channel = await resolve_channel(guild, channel_id)
        if state == "present":
            targets.append(channel)
        elif state == "unknown":
            unresolved = True
    return category_state, targets, unresolved


async def delete_meeting_space(
    guild: discord.Guild,
    category_id: int,
    extra_channel_ids=(),
) -> bool:
    """모임 공간을 삭제한다. Discord는 카테고리를 지워도 하위 채널을 지우지 않는다.

    하위 채널과 저장된 채널(extra_channel_ids)을 지운 뒤, 모두 확실히 사라졌을 때만 카테고리를 지운다.
    True는 카테고리까지 삭제된 경우뿐이며, False면 호출자가 API로 따로 확인해야 한다.
    """
    complete = True
    category_state, category = await resolve_channel(guild, category_id)
    if category_state == "unknown":
        complete = False

    targets = []
    seen = set()
    if category is not None:
        for channel in category.channels:
            targets.append(channel)
            seen.add(channel.id)
    for channel_id in extra_channel_ids:
        if channel_id is None or channel_id in seen:
            continue
        seen.add(channel_id)
        state, channel = await resolve_channel(guild, channel_id)
        if state == "present":
            targets.append(channel)
        elif state == "unknown":
            complete = False

    if category_state == "gone" and not targets and complete:
        print(f'카테고리/채널을 찾을 수 없음 또는 이미 삭제됨: {category_id}')
        return False
    print(f'\n모임 Discord 공간 삭제 시작: category_id={category_id}')
    for channel in targets:
        try:
            await channel.delete(reason='PlayMate 모임 종료')
            print(f'채널 삭제 완료: {channel.name} (ID: {channel.id})')
        except discord.NotFound:
            print(f'채널이 이미 삭제됨: {channel.id}')
        except discord.Forbidden:
            print(f'채널 삭제 권한 없음: {channel.name}')
            complete = False
        except discord.HTTPException as e:
            print(f'채널 삭제 실패: {channel.name} / {e}')
            complete = False
    if category is None or not complete:
        return False
    try:
        await category.delete(reason='PlayMate 모임 종료')
        print(f'카테고리 삭제 완료: {category.name} (ID: {category.id})')
        return True
    except discord.NotFound:
        print(f'카테고리가 이미 삭제됨: {category.id}')
        return True
    except discord.Forbidden:
        print(f'카테고리 삭제 권한 없음: {category.name}')
        return False
    except discord.HTTPException as e:
        print(f'카테고리 삭제 실패: {category.name} / {e}')
        return False
