"""PlayMate Discord Bot 진입점 (`python bot.py`).

DB_* 환경변수가 있으면 공용 PostgreSQL, 없으면 메모리 저장소로 모임 기능을 실행한다.
알림 / 공식 채널 기능은 DB 연결 시에만 켜지고, 모임 작업을 먼저 시작한 뒤 따로 시작한다.
"""
import discord
from discord import app_commands
from discord.ext import tasks

from config import (
    ADMIN_ROLE_ID,
    CAREER_CHANNEL_ID,
    DB_CONFIGURED,
    GUILD_ID,
    HOT_CHANNEL_ID,
    OFFICIAL_CHANNEL_NAMES,
    OFFICIAL_RETRY_MINUTES,
    TEST_MODE,
    TOKEN,
)
from handlers.message_handler import handle_message
from handlers.notification_command_handler import build_notification_command
from handlers.promotion_command_handler import build_promotion_command
from repositories.career_content_repository import UnconnectedCareerContentRepository
from repositories.content_repository import PostgresContentRepository
from repositories.db import Database
from repositories.meeting_repository import (
    InMemoryMeetingRepository,
    PostgresMeetingRepository,
)
from repositories.notification_repository import PostgresNotificationRepository
from services.career_content_service import CareerContentService, create_career_tasks
from services.db_sync import create_sync_task
from services.hot_content_service import HotContentService, create_hot_task
from services.lifecycle import create_lifecycle_task
from services.notification_service import NotificationService, create_notification_task
from services.official_channels import ensure_official_channels

# 기본 intents만 사용한다. 메시지 본문(message content)은 필요하지도, 저장하지도 않는다.
intents = discord.Intents.default()
client = discord.Client(intents=intents)
if DB_CONFIGURED:
    repository = PostgresMeetingRepository.from_env()
else:
    print('DB 설정이 없어 메모리 저장소를 사용합니다 (재시작 시 상태 유실).')
    repository = InMemoryMeetingRepository()
check_meeting_lifecycle = create_lifecycle_task(client, repository)
sync_db = create_sync_task(client, repository) if DB_CONFIGURED else None

# -- 알림 / 공식 채널 기능 -------------------------------------------------------
# 모임 저장소와 다른 DB 연결을 쓴다. 명령은 설정된 서버(GUILD_ID)에만 등록한다.
tree = app_commands.CommandTree(client)
guild_object = discord.Object(id=GUILD_ID)
feature_tasks: list[tuple[str, object]] = []
commands_synced = False
official_channels_ready = False
if DB_CONFIGURED:
    feature_db = Database.from_env()
    notification_service = NotificationService(client, PostgresNotificationRepository(feature_db))
    hot_service = HotContentService(client, PostgresContentRepository(feature_db), HOT_CHANNEL_ID)
    tree.add_command(build_notification_command(notification_service), guild=guild_object)
    tree.add_command(build_promotion_command(hot_service, ADMIN_ROLE_ID), guild=guild_object)
    feature_tasks.append(("알림 polling (10초)", create_notification_task(client, notification_service)))
    if HOT_CHANNEL_ID is not None:
        feature_tasks.append(("HOT PLAYMATE 자동 게시 (13:00, 19:00)", create_hot_task(client, hot_service)))
# TODO: 취업 담당자 스키마가 나오면 실제 CareerContentRepository 구현으로 바꾼다.
career_repository = UnconnectedCareerContentRepository()
if CAREER_CHANNEL_ID is not None and career_repository.connected:
    career_service = CareerContentService(client, career_repository, CAREER_CHANNEL_ID)
    career_new, career_reminder = create_career_tasks(client, career_service)
    feature_tasks.append(("취업 소식 신규 포워딩", career_new))
    feature_tasks.append(("취업 소식 마감 재노출 (13:00)", career_reminder))


async def ensure_official_channels_once(guild: discord.Guild) -> None:
    """상시 오픈채팅 채널(자격증/기술스택/직무)을 확인하고 없으면 만든다 (필수 3개가 모두 있을 때까지 반복).

    필수 채널이 하나라도 없으면 완료로 보지 않는다. 실패하면 로그만 남기고 모임 기능은 그대로 동작하며,
    다음 on_ready 또는 재시도 task(`retry_official_channels`)가 없는 채널만 다시 만든다 (있는 채널은 재사용).
    """
    global official_channels_ready
    if official_channels_ready:
        return
    try:
        channels = await ensure_official_channels(guild)
    except Exception as error:
        print(f'상시 오픈채팅 채널 확인 실패: {error!r}')
        return
    present = {channel.name for channel in channels}
    missing = [name for name in OFFICIAL_CHANNEL_NAMES if name not in present]
    if missing:
        print(f'상시 오픈채팅 채널 일부 누락, 다시 시도합니다: {", ".join(missing)}')
        return
    official_channels_ready = True
    print(f'상시 오픈채팅 채널 확인 완료: {", ".join(channel.name for channel in channels)}')


@tasks.loop(minutes=OFFICIAL_RETRY_MINUTES)
async def retry_official_channels():
    """상시 채널 확인이 끝나지 않았을 때 주기적으로 다시 시도하고, 완료되면 스스로 멈춘다."""
    if retry_official_channels.current_loop == 0:
        return  # 시작 직후는 on_ready가 방금 시도했다
    guild = client.get_guild(GUILD_ID)
    if guild is not None:
        await ensure_official_channels_once(guild)
    if official_channels_ready:
        retry_official_channels.cancel()


@retry_official_channels.before_loop
async def before_retry_official_channels():
    await client.wait_until_ready()


async def start_feature_tasks() -> None:
    """알림 / 공식 채널 루프를 시작하고 slash command를 한 번 동기화한다 (실패해도 기존 기능은 계속)."""
    global commands_synced
    for name, task in feature_tasks:
        if not task.is_running():
            task.start()
            print(f'{name} 시작')
    if commands_synced or not DB_CONFIGURED:
        return
    try:
        synced = await tree.sync(guild=guild_object)
        commands_synced = True
        print(f'slash command 동기화 완료: {", ".join(command.name for command in synced)}')
    except Exception as error:
        print(f'slash command 동기화 실패: {error!r}')


@client.event
async def on_message(message: discord.Message):
    """모임 채널의 활동 기록을 message_handler에 넘긴다."""
    await handle_message(message, repository)


@client.event
async def on_ready():
    """주기 작업을 시작한다. 재연결 때 다시 호출되므로 실행 중인 작업은 다시 시작하지 않는다."""
    print(f'\nBot 로그인 성공: {client.user}')
    guild = client.get_guild(GUILD_ID)
    if guild is None:
        print('테스트 서버를 찾지 못했습니다.')
        return
    print(f'서버 연결 성공: {guild.name}')
    print('PlayMate Discord Bot 라이프사이클 관리 준비 완료')
    await ensure_official_channels_once(guild)
    if not official_channels_ready and not retry_official_channels.is_running():
        retry_official_channels.start()
    if sync_db is not None and not sync_db.is_running():
        sync_db.start()
        print('PlayMate DB 동기화 시작')
    if not check_meeting_lifecycle.is_running():
        check_meeting_lifecycle.start()
        if TEST_MODE:
            print('모임 라이프사이클 검사 시작 (테스트: 1분 주기)')
        else:
            print('모임 라이프사이클 검사 시작 (실서비스: 1시간 주기)')
    try:
        await start_feature_tasks()
    except Exception as error:
        print(f'알림 / 공식 채널 기능 시작 실패: {error!r}')


if __name__ == "__main__":
    client.run(TOKEN)
