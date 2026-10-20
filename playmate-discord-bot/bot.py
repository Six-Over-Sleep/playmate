"""PlayMate Discord Bot 진입점: 클라이언트를 만들고 저장소, 이벤트, 주기 작업을 연결한다.

실행: `python bot.py`

저장소 선택:
    DB_* 환경변수가 모두 있으면 공용 PostgreSQL(recruit_discord_channels)을 사용하고,
    없으면 메모리 저장소로 시작한다 (재시작하면 상태가 사라지고 DB 동기화도 하지 않는다).

주기 작업 (on_ready에서 시작):
    - DB 동기화(DB 연결 시): regular 모임의 Discord 공간 생성, 참여자 권한 반영
    - lifecycle 검사: 30일 비활성 경고, 7일 유예, 자동 삭제

알림 / 공식 채널 기능 (DB 연결 시, 모임 기능과 분리):
    - /알림설정, notifications polling (10초)
    - /게시글추천, HOT PLAYMATE 자동 게시 (13:00, 19:00)
    - 취업 소식 (취업 저장소가 연결된 경우에만)
    기존 작업을 먼저 시작한 뒤 별도로 시작하며, 실패해도 기존 작업에 영향을 주지 않는다.
"""
import discord
from discord import app_commands

from config import (
    ADMIN_ROLE_ID,
    CAREER_CHANNEL_ID,
    DB_CONFIGURED,
    GUILD_ID,
    HOT_CHANNEL_ID,
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

# 기본 intents만 사용한다. 메시지 본문(message content)은 필요하지도, 저장하지도 않는다.
intents = discord.Intents.default()
client = discord.Client(intents=intents)
# 상태는 공용 PostgreSQL(recruit_discord_channels)에 저장한다.
# DB 설정이 없으면 기존처럼 메모리 저장소로 동작한다.
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


async def start_feature_tasks() -> None:
    """알림 / 공식 채널 루프를 시작하고 slash command를 서버에 한 번 동기화한다.

    on_ready는 재연결 때 다시 호출되므로 실행 중인 루프와 이미 끝난 동기화는 반복하지 않는다.
    명령 동기화가 실패해도(초대 scope에 applications.commands 누락 등) 루프와 기존 기능은 계속 동작한다.
    """
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
    """서버에 메시지가 올라올 때마다 호출된다. regular 모임 채널의 활동을 기록하도록 넘긴다.

    실제 판단(Bot 메시지 무시, 관리 중인 모임인지 확인, 활동 시각 갱신)은
    `handlers.message_handler.handle_message`가 한다.
    """
    await handle_message(message, repository)


@client.event
async def on_ready():
    """Bot이 Discord에 로그인하고 서버 정보를 받은 뒤 호출되며, 주기 작업을 시작한다.

    처리 순서:
        1. 설정된 서버(GUILD_ID)를 찾는다. 찾지 못하면 주기 작업을 시작하지 않는다.
        2. DB가 연결되어 있으면 DB 동기화 작업을 시작한다.
        3. lifecycle 검사 작업을 시작한다 (운영: 하루 1회, 테스트 모드: 1분).

    on_ready는 재연결 때 다시 호출될 수 있으므로, 이미 실행 중인 작업은 다시 시작하지 않는다.
    """
    print(f'\nBot 로그인 성공: {client.user}')
    guild = client.get_guild(GUILD_ID)
    if guild is None:
        print('테스트 서버를 찾지 못했습니다.')
        return
    print(f'서버 연결 성공: {guild.name}')
    print('PlayMate Discord Bot 라이프사이클 관리 준비 완료')
    if sync_db is not None and not sync_db.is_running():
        sync_db.start()
        print('PlayMate DB 동기화 시작')
    if not check_meeting_lifecycle.is_running():
        check_meeting_lifecycle.start()
        if TEST_MODE:
            print('모임 라이프사이클 검사 시작 (테스트: 1분 주기)')
        else:
            print('모임 라이프사이클 검사 시작 (실서비스: 하루 1회)')
    try:
        await start_feature_tasks()
    except Exception as error:
        print(f'알림 / 공식 채널 기능 시작 실패: {error!r}')


if __name__ == "__main__":
    client.run(TOKEN)
