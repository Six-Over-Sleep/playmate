"""모임 채널의 참여자 Discord 권한을 적용한다. HOST도 일반 참여자와 같은 정책이다.

권한은 DB에 저장된 모임 채널 ID 하나에 적용한다. 채널은 캐시에 없으면 API로 조회한다.
"""
import discord

from services.meeting_space import participant_overwrite, resolve_channel


class ChannelUnresolved(RuntimeError):
    """저장된 채널을 조회하지 못했다 (Forbidden / HTTP 오류 / 타임아웃). 완료로 보면 안 되고 다음 poll에 재시도한다."""


async def _channel_and_member(guild: discord.Guild, channel_id: int, participant_id: int):
    """저장된 ID로 채널과 참여자를 찾는다: (채널, 멤버). 채널이나 참여자가 없으면 None."""
    state, channel = await resolve_channel(guild, channel_id)
    if state == "unknown":
        raise ChannelUnresolved(f'채널 조회 불명확: channel_id={channel_id}')
    if state == "gone":
        print(f'채널을 찾을 수 없음: {channel_id}')
        return None
    try:
        member = await guild.fetch_member(participant_id)
    except discord.NotFound:
        print(f'참여자를 찾을 수 없음: {participant_id}')
        return None
    except discord.Forbidden:
        print(f'참여자 조회 권한 없음: {participant_id}')
        return None
    return channel, member


async def grant_participant_permissions(guild: discord.Guild, channel_id: int, participant_id: int):
    """참여자에게 모임 채널 사용 권한(보기/읽기/쓰기)을 준다 (PUBLIC / PRIVATE 공통).

    반환: True 적용 완료 / False 채널이나 참여자를 찾을 수 없음.
    채널 조회가 불명확하면 ChannelUnresolved를 올린다 (완료로 보지 않고 다음 poll에 재시도).
    """
    found = await _channel_and_member(guild, channel_id, participant_id)
    if found is None:
        return False
    channel, member = found
    await channel.set_permissions(member, overwrite=participant_overwrite())
    print(f'참여자 권한 부여 완료: {member} → channel_id={channel_id}')
    return True


async def remove_participant_permissions(
    guild: discord.Guild,
    channel_id: int,
    participant_id: int,
    visibility: str,
):
    """참여 취소한 사용자의 권한을 회수한다.

    PUBLIC: 비참여자 상태(읽기 O, 쓰기 X). PRIVATE: 개인 권한 제거(@everyone을 따라 안 보임).
    반환/실패 처리는 grant_participant_permissions와 같다.
    """
    visibility = visibility.upper()
    if visibility not in ('PUBLIC', 'PRIVATE'):
        raise ValueError('visibility은 PUBLIC 또는 PRIVATE여야 합니다.')
    found = await _channel_and_member(guild, channel_id, participant_id)
    if found is None:
        return False
    channel, member = found
    if visibility == 'PUBLIC':
        overwrite = discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=False,
        )
    else:
        overwrite = None
    await channel.set_permissions(member, overwrite=overwrite)
    if visibility == 'PUBLIC':
        print(f'PUBLIC 참여 취소 처리 완료: {member} → 읽기만 허용')
    else:
        print(f'PRIVATE 참여 취소 처리 완료: {member} → 접근 권한 제거')
    return True
