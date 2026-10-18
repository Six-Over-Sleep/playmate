"""모임 참여자와 HOST의 Discord 권한 정책을 적용한다.

참여자 권한은 카테고리와 그 안의 모든 채널(텍스트/음성)에 같은 overwrite를 적용한다.
HOST 권한은 참여자 권한에 manage_channels를 더한 것이다.
"""
import discord

from services.meeting_space import resolve_space


class ChannelUnresolved(RuntimeError):
    """저장된 채널 중 일부를 조회하지 못했을 때 발생한다 (Forbidden / HTTP 오류 / 타임아웃).

    조회된 채널에는 권한을 이미 적용했지만, 이 변경을 "완료"로 보고하면 안 된다.
    호출자(db_sync)가 예외를 받으면 완료로 기록하지 않고 다음 poll에서 다시 시도한다.
    """


async def grant_participant_permissions(
    guild: discord.Guild,
    category_id: int,
    participant_id: int,
    channel_ids=(),
):
    """
    PlayMate 모임 참여 성공 시
    Discord 사용 권한을 부여한다.

    PUBLIC / PRIVATE 관계없이
    참여자는 해당 모임 공간을 사용할 수 있다.

    대상 채널은 카테고리 하위 목록이나 캐시가 아니라 DB에 저장된
    category / text / voice ID로 찾는다 (캐시에 없으면 API 조회, 다른 카테고리로
    옮겨져 있어도 해당 채널에 적용).

    반환:
        True: 모든 대상에 적용함 / False: 카테고리가 없거나 참여자를 서버에서 찾을 수 없음
    실패 처리:
        일부 채널 조회가 불명확하면 조회된 채널에는 적용한 뒤 ChannelUnresolved를 올린다.
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
    participant_overwrite = discord.PermissionOverwrite(
        view_channel=True, read_message_history=True,
        send_messages=True, connect=True, speak=True,
    )
    for target in targets:
        await target.set_permissions(member, overwrite=participant_overwrite)
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

    반환/실패 처리는 grant_participant_permissions와 같다.
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
    # manage_messages는 원래 정책대로 지정하지 않는다(None). False로 막지 않고 Discord 상속을 따른다.
    host_overwrite = discord.PermissionOverwrite(
        view_channel=True, read_message_history=True,
        send_messages=True, connect=True, speak=True,
        manage_channels=True,
    )
    await category.set_permissions(host, overwrite=host_overwrite)
    for channel in category.channels:
        await channel.set_permissions(host, overwrite=host_overwrite)
    print(f'HOST 권한 부여 완료: {host} → {category.name}')
    return True
