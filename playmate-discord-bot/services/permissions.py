"""Existing participant and HOST Discord permission policies."""
import discord

from services.meeting_space import resolve_space


class ChannelUnresolved(RuntimeError):
    """A stored channel could not be looked up (Forbidden / HTTP error / timeout).

    The reachable channels were still updated, but the change must not be
    reported as complete: it is retried on the next poll.
    """


async def grant_participant_permissions(guild: discord.Guild, category_id: int, participant_id: int, channel_ids=()):
    """
    PlayMate 모임 참여 성공 시
    Discord 사용 권한을 부여한다.

    PUBLIC / PRIVATE 관계없이
    참여자는 해당 모임 공간을 사용할 수 있다.

    대상 채널은 카테고리 하위 목록이나 캐시가 아니라 DB에 저장된
    category / text / voice ID로 찾는다 (캐시에 없으면 API 조회, 다른 카테고리로
    옮겨져 있어도 해당 채널에 적용).
    """
    _, targets, unresolved = await resolve_space(guild, category_id, channel_ids)
    if not targets:
        if unresolved:
            raise ChannelUnresolved(f'채널 조회 불명확: category_id={category_id}')
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
    for target in targets:
        await target.set_permissions(member, overwrite=participant_overwrite)
    if unresolved:
        raise ChannelUnresolved(f'일부 채널 조회 불명확: category_id={category_id}')
    print(f'참여자 권한 부여 완료: {member} → category_id={category_id}')
    return True


async def remove_participant_permissions(guild: discord.Guild, category_id: int, participant_id: int, visibility: str, channel_ids=()):
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

    grant와 같이 DB에 저장된 ID 기준으로 채널을 찾으므로, 채널이 캐시에 없거나
    다른 카테고리로 옮겨져 있어도 권한이 회수된다.
    """
    visibility = visibility.upper()
    if visibility not in ('PUBLIC', 'PRIVATE'):
        raise ValueError('visibility은 PUBLIC 또는 PRIVATE여야 합니다.')
    _, targets, unresolved = await resolve_space(guild, category_id, channel_ids)
    if not targets:
        if unresolved:
            raise ChannelUnresolved(f'채널 조회 불명확: category_id={category_id}')
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
    else:
        overwrite = None
    for target in targets:
        await target.set_permissions(member, overwrite=overwrite)
    if unresolved:
        raise ChannelUnresolved(f'일부 채널 조회 불명확: category_id={category_id}')
    if visibility == 'PUBLIC':
        print(f'PUBLIC 참여 취소 처리 완료: {member} → 읽기만 허용')
    else:
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
