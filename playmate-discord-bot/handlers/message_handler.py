"""Discord 메시지에서 모임 채널의 마지막 활동 시각만 갱신한다. 메시지 내용은 읽거나 저장하지 않는다."""
from datetime import datetime

import discord

from config import KST
from repositories.meeting_repository import MeetingRepository, call
from services.lifecycle import DELETE_CANCELLED_TEXT, channel_lock, note_activity


async def handle_message(message: discord.Message, repository: MeetingRepository):
    """관리 중인 모임 채널의 사용자 메시지를 활동 시각으로 기록한다 (본문은 읽지 않음).

    모임은 메시지가 올라온 채널 ID(`message.channel.id`)로 찾는다. Bot 메시지, DM, 모임 채널이
    아닌 채널(상시 오픈채팅 등)은 무시한다. 삭제 경고나 예약이 있었다면 활동 기록과 함께 예약이
    취소되고, 가능하면 채널에 취소 안내를 남긴다.
    """
    if message.author.bot:
        return
    if message.guild is None:
        return
    channel_id = message.channel.id
    # 이 채널을 지우려는 중이면 await 이전에 알린다 (삭제는 channel.delete() 직전에 이를 확인한다).
    note_activity(channel_id)
    meeting = await call(repository.get_managed_meeting, channel_id)
    if meeting is None:
        return
    now = datetime.now(KST)
    # 채널 락 아래에서 처리한다: 삭제 작업이 진행 중이면 끝날 때까지 기다리고, 먼저 처리된 활동은 삭제가
    # 다시 확인한다. 그래서 예약이 취소된 뒤에 같은 삭제 작업이 채널을 지우는 일이 없다.
    async with channel_lock(channel_id):
        meeting = await call(repository.get_managed_meeting, channel_id)
        if meeting is None or meeting.get('discord_deleted_at') is not None:
            return
        recruit_id = meeting['recruit_id']
        # 활동 기록 전에 "삭제 경고/예약이 있었는지"를 기억해 둔다 (메모리 저장소는 같은 dict를 바로 바꾼다).
        had_pending_delete = (
            meeting.get('inactivity_warned_at') is not None
            or meeting.get('scheduled_delete_at') is not None
        )
        # 활동 시각 갱신과 경고/삭제 예약 취소를 하나의 조건부 UPDATE로 처리한다.
        # 활동이 항상 우선하므로, 오래된 경고 정보가 새 활동을 덮어쓰지 못한다.
        recorded = await call(repository.record_activity, channel_id, now)
    if not recorded:
        return
    if had_pending_delete:
        print(f'\n[모임 채널 활동 재개]\nrecruit_id={recruit_id}\n자동 삭제 예약 취소')
        try:
            await message.channel.send(DELETE_CANCELLED_TEXT)
        except Exception as error:
            # 안내 메시지는 부가 기능이다. 실패해도 예약 취소와 활동 기록에는 영향이 없다.
            print(f'삭제 예약 취소 안내 전송 실패: recruit_id={recruit_id} / {error!r}')
    print(
        f"\n[모임 채널 활동 감지]\nrecruit_id={recruit_id} channel_id={channel_id}"
        f"\nlast_activity_at={now.strftime('%Y-%m-%d %H:%M:%S')}"
    )
