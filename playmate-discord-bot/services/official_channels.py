"""상시 오픈채팅 채널(자격증 / 기술스택 / 직무)을 확인하고 없으면 만든다.

이 채널들은 모임 채널이 아니다. recruit_id와 연결하지 않고 DB 행도 만들지 않으므로 lifecycle의 비활성
자동 삭제 대상이 될 수 없다. 그래도 실수로 지워지지 않도록 채널 ID를 보호 목록(PROTECTED_CHANNEL_IDS)에
넣고, 모임 채널 삭제 함수가 이 목록의 채널은 거부한다. 이름 세분화(sqld, python 등)는 이번 범위가 아니다.
"""
import discord

from config import CAREER_CHANNEL_ID, HOT_CHANNEL_ID, OFFICIAL_CATEGORY_NAME, OFFICIAL_CHANNEL_NAMES

# 자동 삭제하면 안 되는 채널 ID (상시 오픈채팅, 공식 서버의 HOT / 취업 소식 채널).
PROTECTED_CHANNEL_IDS: set[int] = set()


async def ensure_official_channels(guild: discord.Guild) -> list[discord.TextChannel]:
    """상시 오픈채팅 카테고리와 채널 3개가 있는지 확인하고, 없는 것만 만든다 (이미 있으면 재사용).

    Bot이 시작될 때마다 호출해도 중복 생성되지 않는다: 같은 이름의 채널이 서버 어디에든 이미 있으면
    새로 만들지 않고 그 채널을 쓴다. 채널 하나의 생성이 실패해도 나머지는 계속 시도한다.
    반환: 확인했거나 만든 채널 목록. 모든 채널 ID는 보호 목록에 등록된다.
    """
    for configured_id in (HOT_CHANNEL_ID, CAREER_CHANNEL_ID):
        if configured_id is not None:
            PROTECTED_CHANNEL_IDS.add(configured_id)

    category = discord.utils.get(guild.categories, name=OFFICIAL_CATEGORY_NAME)
    if category is None:
        category = await guild.create_category(name=OFFICIAL_CATEGORY_NAME)
        print(f'상시 오픈채팅 카테고리 생성: {OFFICIAL_CATEGORY_NAME} (ID: {category.id})')

    channels = []
    for name in OFFICIAL_CHANNEL_NAMES:
        channel = discord.utils.get(guild.text_channels, name=name)
        if channel is None:
            try:
                channel = await guild.create_text_channel(name=name, category=category)
                print(f'상시 오픈채팅 채널 생성: #{name} (ID: {channel.id})')
            except Exception as error:
                print(f'상시 오픈채팅 채널 생성 실패 #{name}: {error!r}')
                continue
        PROTECTED_CHANNEL_IDS.add(channel.id)
        channels.append(channel)
    return channels
