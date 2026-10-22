"""Discord 메시지에서 모임의 마지막 활동 시각만 갱신한다. 메시지 내용은 읽거나 저장하지 않는다."""
from datetime import datetime

import discord

from config import KST
from repositories.meeting_repository import MeetingRepository, call


async def handle_message(message: discord.Message, repository: MeetingRepository):
    """regular 모임 카테고리 안의 사용자 메시지를 활동 시각으로 기록한다 (본문은 읽지 않음).

    Bot 메시지, DM, 카테고리 밖 채널, 관리 대상이 아닌 카테고리는 무시한다.
    """
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
    # 활동 시각 갱신과 경고/삭제 예약 취소를 하나의 조건부 UPDATE로 처리한다.
    # 활동이 항상 우선하므로, 오래된 경고 정보가 새 활동을 덮어쓰지 못한다.
    recorded = await call(repository.record_activity, category_id, now)
    if not recorded:
        return
    if (
        meeting.get('inactivity_warned_at') is not None
        or meeting.get('scheduled_delete_at') is not None
    ):
        print(f'\n[상시모임 활동 재개]\nrecruit_id={recruit_id}\n자동 종료 예약 취소')
    print(
        f"\n[상시모임 활동 감지]\nrecruit_id={recruit_id}\ncategory_id={category_id}"
        f"\nlast_activity_at={now.strftime('%Y-%m-%d %H:%M:%S')}"
    )
