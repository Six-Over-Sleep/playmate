"""Create and delete Discord resources; names are never used as identifiers."""
import discord


class MeetingSpaceCleanupError(RuntimeError):
    """Creation failed AND the partially created Discord resources could not
    all be removed. `remaining_ids` lists what may still exist on the server."""

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
    """
    PlayMate에서 생성 승인된 regular 모임의 Discord 공간을 생성한다.

    short 모임은 Discord 공간을 만들지 않고 None을 반환한다.

    구조:

    📁 모임명
    ├─ # 채팅
    └─ 🔊 음성


    원칙:

    - 모임명 중복 검사는 PlayMate 백엔드/DB 담당
    - Bot은 모임명을 정규화하여
      동일 모임 여부를 판단하지 않는다.
    - 실제 서비스 중복 생성 방지는
      recruit_id ↔ Discord resource ID 기준으로 처리한다.
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
        overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=False, connect=False, speak=False)}
    else:
        overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False, read_message_history=False, send_messages=False, connect=False, speak=False)}
    for participant_id in participant_ids:
        try:
            member = await guild.fetch_member(participant_id)
        except discord.NotFound:
            print(f'참여자를 찾을 수 없음: {participant_id}')
            continue
        except discord.Forbidden:
            print(f'참여자 조회 권한 없음: {participant_id}')
            continue
        overwrites[member] = discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=True, connect=True, speak=True)
    category = await guild.create_category(name=meeting_name, overwrites=overwrites)
    print(f'모임 카테고리 생성 완료: {category.name} (ID: {category.id})')
    created = [category]
    try:
        text_channel = await guild.create_text_channel(name='채팅', category=category, topic=f'[{visibility}] {meeting_name}')
        created.append(text_channel)
        print(f'텍스트 채널 생성 완료: {text_channel.name} (ID: {text_channel.id})')
        voice_channel = None
        if create_voice_channel:
            voice_channel = await guild.create_voice_channel(name='음성', category=category)
            created.append(voice_channel)
            print(f'음성 채널 생성 완료: {voice_channel.name} (ID: {voice_channel.id})')
        else:
            print('음성 채널 생성 안 함')
    except Exception as creation_error:
        # Do not leave a half-built space that nothing tracks. If removal fails
        # too, tell the caller which IDs remain so it is never retried blindly.
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
    """Look a channel up in the cache, then ask the Discord API.

    Returns ("present", channel), ("gone", None) or ("unknown", None).
    Only an explicit NotFound from the API means "gone"; a cache miss alone,
    Forbidden, HTTP errors, timeouts or anything else is "unknown" and must
    never be treated as deleted.
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
    """Resolve the managed channels from their STORED ids (DB is authoritative).

    Returns (category_state, targets, unresolved):
      targets    - the category first, then every channel found under the category
                   (cache) plus every stored id, de-duplicated. A stored channel is
                   used wherever it currently lives (cache miss, moved to another
                   category, ...): it is looked up in the cache, then via the API.
      unresolved - True when any lookup was unclear (Forbidden / HTTP error /
                   timeout / ...). NotFound alone means "that resource does not exist".
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
    """
    모임 Discord 공간 삭제.

    Discord는 카테고리를 지워도 하위 채널을 자동 삭제하지 않는다.
    그래서 카테고리 하위 채널과, DB에 저장된 text/voice 채널 ID(extra_channel_ids)를
    각각 삭제한 뒤 카테고리를 삭제한다. 캐시에 없으면 API로 조회하고,
    API가 NotFound를 돌려준 리소스만 이미 삭제된 것으로 본다.

    순서:

    1. 하위 채널 삭제 (실패해도 나머지 채널은 계속 시도)
    2. 모든 하위 채널이 확실히 사라진 경우에만 카테고리 삭제

    반환값 True는 카테고리까지 삭제된 경우에만이다. False이면 호출자가
    세 리소스가 실제로 모두 사라졌는지 API로 따로 확인해야 한다.
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
            channel_name = channel.name
            channel_id = channel.id
            await channel.delete(reason='PlayMate 모임 종료')
            print(f'채널 삭제 완료: {channel_name} (ID: {channel_id})')
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
        category_name = category.name
        category_id_value = category.id
        await category.delete(reason='PlayMate 모임 종료')
        print(f'카테고리 삭제 완료: {category_name} (ID: {category_id_value})')
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
