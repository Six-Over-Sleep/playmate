"""Existing participant and HOST Discord permission policies."""
import discord


async def grant_participant_permissions(guild: discord.Guild, category_id: int, participant_id: int):
    """
    PlayMate 모임 참여 성공 시
    Discord 사용 권한을 부여한다.

    PUBLIC / PRIVATE 관계없이
    참여자는 해당 모임 공간을 사용할 수 있다.
    """
    category = guild.get_channel(category_id)
    if category is None:
        print(f'카테고리를 찾을 수 없음: {category_id}')
        return False
    try:
        member = await guild.fetch_member(participant_id)
    except discord.NotFound:
        print(f'참여자를 찾을 수 없음: {participant_id}')
        return False
    except discord.Forbidden:
        print(f'참여자 조회 권한 없음: {participant_id}')
        return False
    participant_overwrite = discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=True, connect=True, speak=True)
    await category.set_permissions(member, overwrite=participant_overwrite)
    for channel in category.channels:
        await channel.set_permissions(member, overwrite=participant_overwrite)
    print(f'참여자 권한 부여 완료: {member} → {category.name}')
    return True


async def remove_participant_permissions(guild: discord.Guild, category_id: int, participant_id: int, visibility: str):
    """
    PlayMate에서 참여 취소 시
    Discord 권한을 회수한다.

    PUBLIC:
    비참여자 상태로 되돌림
    → 읽기 O
    → 쓰기 X
    → 음성 접속 X

    PRIVATE:
    개인 권한 제거
    → @everyone 권한을 따라가므로
      비참여자는 채널을 볼 수 없음.
    """
    visibility = visibility.upper()
    if visibility not in ('PUBLIC', 'PRIVATE'):
        raise ValueError('visibility은 PUBLIC 또는 PRIVATE여야 합니다.')
    category = guild.get_channel(category_id)
    if category is None:
        print(f'카테고리를 찾을 수 없음: {category_id}')
        return False
    try:
        member = await guild.fetch_member(participant_id)
    except discord.NotFound:
        print(f'참여자를 찾을 수 없음: {participant_id}')
        return False
    except discord.Forbidden:
        print(f'참여자 조회 권한 없음: {participant_id}')
        return False
    if visibility == 'PUBLIC':
        overwrite = discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=False, connect=False, speak=False)
        await category.set_permissions(member, overwrite=overwrite)
        for channel in category.channels:
            await channel.set_permissions(member, overwrite=overwrite)
        print(f'PUBLIC 참여 취소 처리 완료: {member} → 읽기만 허용')
    else:
        await category.set_permissions(member, overwrite=None)
        for channel in category.channels:
            await channel.set_permissions(member, overwrite=None)
        print(f'PRIVATE 참여 취소 처리 완료: {member} → 접근 권한 제거')
    return True


async def grant_host_permissions(guild: discord.Guild, category_id: int, host_id: int):
    """
    PlayMate recruit_members.role = HOST인 사용자에게
    Discord HOST 권한을 부여한다.

    현재 임시 정책:

    manage_channels = True
    manage_messages = 미설정(None)

    manage_channels 유지 여부는
    팀 회의에서 최종 결정 예정.
    """
    category = guild.get_channel(category_id)
    if category is None:
        print(f'카테고리를 찾을 수 없음: {category_id}')
        return False
    try:
        host = await guild.fetch_member(host_id)
    except discord.NotFound:
        print(f'모임장을 찾을 수 없음: {host_id}')
        return False
    except discord.Forbidden:
        print(f'모임장 조회 권한 없음: {host_id}')
        return False
    # Original manage_messages overwrite was unset (None); keep Discord inheritance.
    host_overwrite = discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=True, connect=True, speak=True, manage_channels=True)
    await category.set_permissions(host, overwrite=host_overwrite)
    for channel in category.channels:
        await channel.set_permissions(host, overwrite=host_overwrite)
    print(f'HOST 권한 부여 완료: {host} → {category.name}')
    return True
