"""Create and delete Discord resources; names are never used as identifiers."""
import discord


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
    text_channel = await guild.create_text_channel(name='채팅', category=category, topic=f'[{visibility}] {meeting_name}')
    print(f'텍스트 채널 생성 완료: {text_channel.name} (ID: {text_channel.id})')
    voice_channel = None
    if create_voice_channel:
        voice_channel = await guild.create_voice_channel(name='음성', category=category)
        print(f'음성 채널 생성 완료: {voice_channel.name} (ID: {voice_channel.id})')
    else:
        print('음성 채널 생성 안 함')
    return (category, text_channel, voice_channel)


async def delete_meeting_space(guild: discord.Guild, category_id: int) -> bool:
    """
    모임 종료 시 Discord 공간 전체 삭제.

    Discord 카테고리 50개 제한을 고려하여
    종료된 모임 공간은 보관하지 않는다.

    순서:

    1. 하위 채널 삭제
    2. 카테고리 삭제
    """
    category = guild.get_channel(category_id)
    if category is None:
        print(f'카테고리를 찾을 수 없음 또는 이미 삭제됨: {category_id}')
        return False
    print(f'\n모임 Discord 공간 삭제 시작: {category.name}')
    for channel in list(category.channels):
        try:
            channel_name = channel.name
            channel_id = channel.id
            await channel.delete(reason='PlayMate 모임 종료')
            print(f'채널 삭제 완료: {channel_name} (ID: {channel_id})')
        except discord.Forbidden:
            print(f'채널 삭제 권한 없음: {channel.name}')
            return False
        except discord.HTTPException as e:
            print(f'채널 삭제 실패: {channel.name} / {e}')
            return False
    try:
        category_name = category.name
        category_id_value = category.id
        await category.delete(reason='PlayMate 모임 종료')
        print(f'카테고리 삭제 완료: {category_name} (ID: {category_id_value})')
        return True
    except discord.Forbidden:
        print(f'카테고리 삭제 권한 없음: {category.name}')
        return False
    except discord.HTTPException as e:
        print(f'카테고리 삭제 실패: {category.name} / {e}')
        return False
