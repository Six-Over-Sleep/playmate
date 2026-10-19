"""Discord 메시지에서 모임의 마지막 활동 시각만 갱신한다. 메시지 내용은 읽거나 저장하지 않는다."""
from datetime import datetime

import discord

from config import KST
from repositories.meeting_repository import MeetingRepository, call


async def handle_message(message: discord.Message, repository: MeetingRepository):
    """regular 모임 카테고리 안의 사용자 메시지를 활동으로 기록한다.

    입력:
        message: Discord가 전달한 메시지 (작성자, 서버, 채널 카테고리만 사용)
        repository: 모임 상태 저장소

    처리 순서:
        1. Bot 메시지, DM, 카테고리 밖 채널의 메시지는 무시한다.
        2. 메시지가 속한 카테고리 ID로 관리 중인 regular 모임을 찾는다. 없으면 무시한다.
        3. `record_activity`로 마지막 활동 시각을 갱신하고 비활성 경고/삭제 예약을 함께 취소한다.

    업무 규칙:
        저장하는 것은 활동 시각뿐이다. 메시지 본문(content)은 읽거나 저장하지 않는다.

    실패 처리:
        이미 삭제 완료로 기록된 모임이거나 갱신 대상이 아니면(`record_activity`가 False)
        아무것도 하지 않는다.
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
