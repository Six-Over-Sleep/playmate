"""PlayMate Discord Bot 진입점: 클라이언트를 만들고 저장소, 이벤트, 주기 작업을 연결한다.

실행: `python bot.py`

저장소 선택:
    DB_* 환경변수가 모두 있으면 공용 PostgreSQL(recruit_discord_channels)을 사용하고,
    없으면 메모리 저장소로 시작한다 (재시작하면 상태가 사라지고 DB 동기화도 하지 않는다).

주기 작업 (on_ready에서 시작):
    - DB 동기화(DB 연결 시): regular 모임의 Discord 공간 생성, 참여자 권한 반영
    - lifecycle 검사: 30일 비활성 경고, 7일 유예, 자동 삭제
"""
import discord

from config import DB_CONFIGURED, GUILD_ID, TEST_MODE, TOKEN
from handlers.message_handler import handle_message
from repositories.meeting_repository import (
    InMemoryMeetingRepository,
    PostgresMeetingRepository,
)
from services.db_sync import create_sync_task
from services.lifecycle import create_lifecycle_task

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


if __name__ == "__main__":
    client.run(TOKEN)
