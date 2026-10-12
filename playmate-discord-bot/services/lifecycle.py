"""Existing one-time and ongoing meeting lifecycle policy."""
from datetime import datetime, timedelta

import discord
from discord.ext import tasks

from config import (
    CHECK_INTERVAL_SECONDS, GUILD_ID, INACTIVITY_DAYS,
    INACTIVITY_GRACE_DAYS, KST, ONE_TIME_DELETE_GRACE_HOURS,
)
from repositories.meeting_repository import MeetingRepository
from services.meeting_space import delete_meeting_space


def get_one_time_scheduled_delete_at(end_at: datetime) -> datetime:
    """
    일회성 모임은 end_at 이후
    24시간 뒤 Discord 공간을 삭제한다.
    """
    return end_at + timedelta(hours=ONE_TIME_DELETE_GRACE_HOURS)


async def check_meeting_lifecycle(client: discord.Client, repository: MeetingRepository):
    now = datetime.now(KST)
    print(f"\n[모임 라이프사이클 검사] {now.strftime('%Y-%m-%d %H:%M:%S')}")
    guild = client.get_guild(GUILD_ID)
    if guild is None:
        print('Discord 서버를 찾을 수 없습니다.')
        return
    for meeting in repository.list_one_time_meetings():
        recruit_id = meeting['recruit_id']
        category_id = meeting['category_id']
        end_at = meeting['end_at']
        discord_deleted_at = meeting.get('discord_deleted_at')
        if discord_deleted_at is not None:
            continue
        scheduled_delete_at = get_one_time_scheduled_delete_at(end_at)
        print(f"[일회성 모임] recruit_id={recruit_id} | 삭제예정={scheduled_delete_at.strftime('%Y-%m-%d %H:%M:%S')}")
        if now < scheduled_delete_at:
            continue
        print(f'[일회성 모임 자동 종료 대상] recruit_id={recruit_id}')
        deleted = await delete_meeting_space(guild=guild, category_id=category_id)
        if deleted:
            meeting['discord_deleted_at'] = now
            repository.save_one_time_meeting(meeting)
            print(f'[일회성 모임 자동 종료 성공] recruit_id={recruit_id}')
    for category_id, meeting in repository.list_ongoing_meetings():
        recruit_id = meeting['recruit_id']
        host_id = meeting['host_id']
        last_activity_at = meeting.get('last_activity_at')
        inactivity_warned_at = meeting.get('inactivity_warned_at')
        scheduled_delete_at = meeting.get('scheduled_delete_at')
        discord_deleted_at = meeting.get('discord_deleted_at')
        if discord_deleted_at is not None:
            continue
        if scheduled_delete_at is not None:
            print(f"[상시모임] recruit_id={recruit_id} | 삭제예정={scheduled_delete_at.strftime('%Y-%m-%d %H:%M:%S')}")
            if now < scheduled_delete_at:
                continue
            # Preserve the original last-minute safety check: later activity cancels deletion.
            if inactivity_warned_at is not None and last_activity_at is not None and (last_activity_at > inactivity_warned_at):
                print(f'경고 이후 활동 발견: recruit_id={recruit_id}')
                meeting['inactivity_warned_at'] = None
                meeting['scheduled_delete_at'] = None
                repository.save_ongoing_meeting(category_id, meeting)
                print('→ 자동삭제 예약 취소')
                continue
            print(f'\n[상시모임 자동 종료 대상]\nrecruit_id={recruit_id}')
            deleted = await delete_meeting_space(guild=guild, category_id=category_id)
            if deleted:
                meeting['discord_deleted_at'] = now
                repository.save_ongoing_meeting(category_id, meeting)
                print(f"\n[상시모임 자동 종료 성공]\nrecruit_id={recruit_id}\ndiscord_deleted_at={now.strftime('%Y-%m-%d %H:%M:%S')}")
            continue
        if last_activity_at is None:
            continue
        inactive_duration = now - last_activity_at
        print(f'[상시모임] recruit_id={recruit_id} | 비활성 기간={inactive_duration.days}일')
        if inactive_duration < timedelta(days=INACTIVITY_DAYS):
            continue
        if inactivity_warned_at is not None:
            continue
        try:
            host = await guild.fetch_member(host_id)
            scheduled_delete_at = now + timedelta(days=INACTIVITY_GRACE_DAYS)
            await host.send(f'PlayMate 모임 활동 안내\n\n모임(recruit_id={recruit_id})에서 최근 {INACTIVITY_DAYS}일 동안 Discord 활동이 확인되지 않았습니다.\n\n앞으로 {INACTIVITY_GRACE_DAYS}일 동안 활동이 없으면 모임이 자동 종료되고 Discord 공간이 삭제됩니다.\n\n모임 채널에서 다시 활동이 발생하면 자동 종료 예약은 취소됩니다.')
            meeting['inactivity_warned_at'] = now
            meeting['scheduled_delete_at'] = scheduled_delete_at
            repository.save_ongoing_meeting(category_id, meeting)
            print(f'비활성 경고 DM 전송 완료: recruit_id={recruit_id}')
            print(f"자동 삭제 예정: {scheduled_delete_at.strftime('%Y-%m-%d %H:%M:%S')}")
        except discord.NotFound:
            print(f'HOST를 찾을 수 없음: host_id={host_id}')
        except discord.Forbidden:
            print(f'HOST에게 DM을 보낼 수 없음: recruit_id={recruit_id}')
        except discord.HTTPException as e:
            print(f'DM 전송 실패: recruit_id={recruit_id} / {e}')


def create_lifecycle_task(
    client: discord.Client,
    repository: MeetingRepository,
):
    """Bind the existing loop and readiness guard to their dependencies."""
    @tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
    async def lifecycle_task():
        await check_meeting_lifecycle(client, repository)

    @lifecycle_task.before_loop
    async def before_check_meeting_lifecycle():
        await client.wait_until_ready()

    return lifecycle_task
