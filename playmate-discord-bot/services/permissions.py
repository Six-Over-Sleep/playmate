"""모임 참여자와 HOST의 Discord 권한 정책을 적용한다.

참여자 권한은 카테고리와 그 안의 모든 채널(텍스트/음성)에 같은 overwrite를 적용한다.
HOST 권한은 참여자 권한과 같다 (채널 구조를 바꾸는 manage_channels / manage_messages는 주지 않는다).
"""
import discord

from services.meeting_space import participant_overwrite, resolve_space


class ChannelUnresolved(RuntimeError):
    """저장된 채널 일부를 조회하지 못했다. 조회된 채널에는 적용했지만 완료로 보면 안 된다 (다음 poll 재시도)."""


async def _targets_and_member(guild: discord.Guild, category_id: int, participant_id: int, channel_ids):
    """저장된 ID로 대상 위치와 참여자를 찾는다: (대상, 불명확 여부, 멤버). 대상이나 참여자가 없으면 None."""
    _, targets, unresolved = await resolve_space(guild, category_id, channel_ids)
    if not targets:
        if unresolved:
            raise ChannelUnresolved(f'채널 조회 불명확: category_id={category_id}')
        print(f'카테고리를 찾을 수 없음: {category_id}')
        return None
    try:
        member = await guild.fetch_member(participant_id)
    except discord.NotFound:
        print(f'참여자를 찾을 수 없음: {participant_id}')
        return None
    except discord.Forbidden:
        print(f'참여자 조회 권한 없음: {participant_id}')
        return None
    return targets, unresolved, member


async def grant_participant_permissions(
    guild: discord.Guild,
    category_id: int,
    participant_id: int,
    channel_ids=(),
):
    """참여자에게 모임 공간 사용 권한을 준다 (PUBLIC / PRIVATE 공통).

    반환: True 적용 완료 / False 카테고리나 참여자를 찾을 수 없음.
    일부 채널 조회가 불명확하면 조회된 채널에 적용한 뒤 ChannelUnresolved를 올린다.
    """
    found = await _targets_and_member(guild, category_id, participant_id, channel_ids)
    if found is None:
        return False
    targets, unresolved, member = found
    overwrite = participant_overwrite()
    for target in targets:
        await target.set_permissions(member, overwrite=overwrite)
    if unresolved:
        raise ChannelUnresolved(f'일부 채널 조회 불명확: category_id={category_id}')
    print(f'참여자 권한 부여 완료: {member} → category_id={category_id}')
    return True


async def remove_participant_permissions(
    guild: discord.Guild,
    category_id: int,
    participant_id: int,
    visibility: str,
    channel_ids=(),
):
    """참여 취소한 사용자의 권한을 회수한다.

    PUBLIC: 비참여자 상태(읽기 O, 쓰기 X, 음성 접속 X). PRIVATE: 개인 권한 제거(@everyone을 따라 안 보임).
    반환/실패 처리는 grant_participant_permissions와 같다.
    """
    visibility = visibility.upper()
    if visibility not in ('PUBLIC', 'PRIVATE'):
        raise ValueError('visibility은 PUBLIC 또는 PRIVATE여야 합니다.')
    found = await _targets_and_member(guild, category_id, participant_id, channel_ids)
    if found is None:
        return False
    targets, unresolved, member = found
    if visibility == 'PUBLIC':
        overwrite = discord.PermissionOverwrite(
            view_channel=True, read_message_history=True,
            send_messages=False, connect=False, speak=False,
        )
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
    """recruit_members.role='HOST'인 사용자에게 모임 공간 사용 권한(채팅/음성)을 준다.

    확정 정책: manage_channels = 미부여, manage_messages = 미설정(None).
    HOST가 채널/카테고리를 삭제하거나 옮기면 Bot이 일부 삭제 상태를 복구하지 못하고
    활동 감지가 끊기거나 다른 모임으로 기록될 수 있어서 채널 관리 권한은 주지 않는다.
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
    host_overwrite = discord.PermissionOverwrite(
        view_channel=True, read_message_history=True,
        send_messages=True, connect=True, speak=True,
    )
    await category.set_permissions(host, overwrite=host_overwrite)
    for channel in category.channels:
        await channel.set_permissions(host, overwrite=host_overwrite)
    print(f'HOST 권한 부여 완료: {host} → {category.name}')
    return True
