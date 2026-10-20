"""모임의 Discord 공간(카테고리, 채팅, 음성)을 만들고 삭제한다.

모임 이름은 식별자가 아니다. 공간은 항상 recruit_id와 저장된 Discord 리소스 ID로 구분한다.
"""
import discord


class MeetingSpaceCleanupError(RuntimeError):
    """공간 생성이 실패했고, 부분적으로 만들어진 리소스를 모두 지우지도 못했을 때 발생한다.

    `remaining_ids`에는 서버에 남아 있을 수 있는 리소스 ID가 들어 있다. 호출자는 이 경우를
    일반 실패처럼 자동 재시도하면 안 된다 (남은 공간 위에 새 공간이 만들어져 중복된다).
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
    """
    PlayMate에서 생성 승인된 regular 모임의 Discord 공간을 생성한다.

    short 모임은 Discord 공간을 만들지 않고 None을 반환한다.

    구조:

    📁 모임명
    ├─ # ╔・채팅
    └─ 🔊 ╚・음성


    원칙:

    - 모임명 중복 검사는 PlayMate 백엔드/DB 담당
    - Bot은 모임명을 정규화하여
      동일 모임 여부를 판단하지 않는다.
    - 실제 서비스 중복 생성 방지는
      recruit_id ↔ Discord resource ID 기준으로 처리한다.

    반환:
        (카테고리, 텍스트 채널, 음성 채널) 튜플. 음성 채널을 만들지 않으면 세 번째가 None이다.

    실패 처리:
        카테고리를 만든 뒤 하위 채널 생성이 실패하면, 만든 리소스를 역순으로 삭제하고
        원래 예외를 다시 올린다. 추적되지 않는 반쪽짜리 공간을 남기지 않기 위해서다.
        삭제까지 실패하면 남은 ID를 담은 MeetingSpaceCleanupError를 올린다.
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
        overwrites[member] = discord.PermissionOverwrite(
            view_channel=True, read_message_history=True,
            send_messages=True, connect=True, speak=True,
        )
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
    """채널을 캐시에서 찾고, 없으면 Discord API로 조회한다.

    반환: ("present", 채널) / ("gone", None) / ("unknown", None)

    업무 규칙:
        API가 명시적으로 NotFound를 돌려준 경우만 "gone"(없음)이다.
        캐시에 없다는 것만으로, 또는 Forbidden/HTTP 오류/타임아웃 같은 불명확한 응답으로는
        절대 "삭제됨"으로 판단하지 않는다. 그 경우는 "unknown"이며 호출자가 재시도해야 한다.
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
    """DB에 저장된 ID를 기준으로 모임 공간의 카테고리와 채널을 찾는다.

    입력:
        category_id: 저장된 카테고리 ID
        channel_ids: 저장된 텍스트/음성 채널 ID (None은 무시)

    반환: (카테고리 상태, 대상 목록, 불명확 여부)
        - 카테고리 상태: "present" / "gone" / "unknown"
        - 대상 목록: 카테고리가 먼저, 이어서 카테고리 하위 채널(캐시 기준)과 저장된 ID의
          채널을 중복 없이 나열한다.
        - 불명확 여부: 조회가 불명확한 리소스가 하나라도 있으면 True.
          NotFound는 "그 리소스는 없음"일 뿐이므로 불명확으로 보지 않는다.

    업무 규칙:
        채널 위치가 바뀌어도 저장된 ID가 기준이다. 캐시에 없거나 다른 카테고리로 옮겨진
        채널도 ID로 조회해서 대상에 포함한다. 권한 부여/회수가 이런 채널을 놓치지 않게 하기 위해서다.
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
