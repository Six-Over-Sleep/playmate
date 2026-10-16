"""Detect user activity without reading or storing message content."""
from datetime import datetime

import discord

from config import KST
from repositories.meeting_repository import MeetingRepository, call


async def handle_message(message: discord.Message, repository: MeetingRepository):
    if message.author.bot:
        return
    if message.guild is None:
        return
    if message.channel.category is None:
        return
    category_id = message.channel.category.id
    meeting = await call(repository.get_regular_meeting, category_id)
    if meeting is None:
        return
    if meeting.get('discord_deleted_at') is not None:
        return
    now = datetime.now(KST)
    recruit_id = meeting['recruit_id']
    # One conditional update: stamps activity and cancels any pending
    # warning/deletion. Only the time is stored, never the message content.
    recorded = await call(repository.record_activity, category_id, now)
    if not recorded:
        return
    if meeting.get('inactivity_warned_at') is not None or meeting.get('scheduled_delete_at') is not None:
        print(f'\n[상시모임 활동 재개]\nrecruit_id={recruit_id}\n자동 종료 예약 취소')
    print(f"\n[상시모임 활동 감지]\nrecruit_id={recruit_id}\ncategory_id={category_id}\nlast_activity_at={now.strftime('%Y-%m-%d %H:%M:%S')}")
