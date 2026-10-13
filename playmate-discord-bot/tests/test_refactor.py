"""Policy and regression checks that do not connect to Discord."""

import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DISCORD_BOT_TOKEN"] = "verification-only"
os.environ["DISCORD_GUILD_ID"] = "1"
os.environ["PLAYMATE_TEST_MODE"] = "true"

import discord

import bot
from config import KST
from handlers import message_handler
from repositories.meeting_repository import InMemoryMeetingRepository
from services import lifecycle, meeting_space

NOW = datetime(2026, 10, 12, 11, 30, tzinfo=KST)


class Clock:
    @classmethod
    def now(cls, timezone):
        return NOW


lifecycle.datetime = Clock
message_handler.datetime = Clock
checks = 0


def check(condition, label):
    global checks
    assert condition, label
    checks += 1


def regular(**changes):
    record = {
        "recruit_id": 2,
        "host_id": 7,
        "last_activity_at": NOW - timedelta(days=31),
        "inactivity_warned_at": None,
        "scheduled_delete_at": None,
        "discord_deleted_at": None,
    }
    record.update(changes)
    return record


def discord_error(kind):
    status = {"NotFound": 404, "Forbidden": 403, "HTTPException": 500}[kind]
    return getattr(discord, kind)(
        SimpleNamespace(status=status, reason="test"), "test"
    )


async def test_creation_policy():
    global checks
    guild = SimpleNamespace(
        default_role=object(),
        fetch_member=AsyncMock(),
        create_category=AsyncMock(),
        create_text_channel=AsyncMock(),
        create_voice_channel=AsyncMock(),
    )

    result = await meeting_space.create_meeting_space(
        guild, "짧은 모임", "short"
    )
    check(result is None, "short 모임은 생성 결과가 없어야 함")
    check(
        guild.create_category.await_count == 0,
        "short 모임은 카테고리를 만들면 안 됨",
    )

    category = SimpleNamespace(name="정기 모임", id=10)
    text_channel = SimpleNamespace(name="채팅", id=11)
    voice_channel = SimpleNamespace(name="음성", id=12)
    guild.create_category.return_value = category
    guild.create_text_channel.return_value = text_channel
    guild.create_voice_channel.return_value = voice_channel
    result = await meeting_space.create_meeting_space(
        guild, "정기 모임", "regular", create_voice_channel=True
    )
    check(
        result == (category, text_channel, voice_channel),
        "regular 공간 생성 결과",
    )
    check(guild.create_category.await_count == 1, "regular 카테고리 생성")
    check(guild.create_text_channel.await_count == 1, "regular 텍스트 채널 생성")
    check(guild.create_voice_channel.await_count == 1, "regular 음성 채널 생성")

    try:
        await meeting_space.create_meeting_space(guild, "잘못된 모임", "unknown")
    except ValueError:
        checks += 1
    else:
        raise AssertionError("알 수 없는 recruit_mode는 거부해야 함")


async def run_lifecycle(
    record,
    *,
    delete_result=True,
    missing_guild=False,
    dm_failure=None,
    fetch_failure=None,
):
    host = SimpleNamespace(send=AsyncMock(side_effect=dm_failure))
    guild = SimpleNamespace(
        fetch_member=AsyncMock(return_value=host, side_effect=fetch_failure)
    )
    client = SimpleNamespace(
        get_guild=Mock(return_value=None if missing_guild else guild)
    )
    repository = InMemoryMeetingRepository(
        regular_meetings={} if record is None else {100: record}
    )
    delete = AsyncMock(return_value=delete_result)
    lifecycle.delete_meeting_space = delete
    await lifecycle.check_meeting_lifecycle(client, repository)
    return host, guild, delete


async def test_regular_lifecycle():
    record = regular(
        state="close",
        meeting_end=NOW - timedelta(days=10),
        last_activity_at=NOW - timedelta(days=1),
    )
    host, _, delete = await run_lifecycle(record)
    check(host.send.await_count == 0, "모집 상태와 종료일은 경고 조건이 아님")
    check(delete.await_count == 0, "모집 상태와 종료일은 삭제 조건이 아님")

    record = regular(last_activity_at=NOW - timedelta(days=29, hours=23))
    host, _, delete = await run_lifecycle(record)
    check(host.send.await_count == 0, "30일 전에는 DM을 보내면 안 됨")
    check(delete.await_count == 0, "30일 전에는 삭제하면 안 됨")

    record = regular(last_activity_at=NOW - timedelta(days=30))
    host, _, delete = await run_lifecycle(record)
    check(host.send.await_count == 1, "30일 경계에서 HOST DM")
    check(record["inactivity_warned_at"] == NOW, "경고 시각 저장")
    check(
        record["scheduled_delete_at"] == NOW + timedelta(days=7),
        "7일 유예 저장",
    )
    check(delete.await_count == 0, "경고 직후 삭제하면 안 됨")

    for kind in ("NotFound", "Forbidden", "HTTPException"):
        record = regular()
        await run_lifecycle(record, dm_failure=discord_error(kind))
        check(
            record["inactivity_warned_at"] is None,
            f"{kind} DM 실패 시 경고 미저장",
        )
        check(
            record["scheduled_delete_at"] is None,
            f"{kind} DM 실패 시 예약 미저장",
        )

        record = regular()
        await run_lifecycle(record, fetch_failure=discord_error(kind))
        check(
            record["inactivity_warned_at"] is None,
            f"{kind} HOST 조회 실패 시 경고 미저장",
        )
        check(
            record["scheduled_delete_at"] is None,
            f"{kind} HOST 조회 실패 시 예약 미저장",
        )

    record = regular(
        inactivity_warned_at=NOW - timedelta(days=6),
        scheduled_delete_at=NOW + timedelta(days=1),
    )
    _, _, delete = await run_lifecycle(record)
    check(delete.await_count == 0, "7일 유예 중에는 삭제하면 안 됨")

    record = regular(
        last_activity_at=NOW - timedelta(days=1),
        inactivity_warned_at=NOW - timedelta(days=8),
        scheduled_delete_at=NOW - timedelta(days=1),
    )
    _, _, delete = await run_lifecycle(record)
    check(delete.await_count == 0, "경고 후 활동 시 삭제 취소")
    check(record["inactivity_warned_at"] is None, "활동 재개 시 경고 초기화")
    check(record["scheduled_delete_at"] is None, "활동 재개 시 예약 초기화")

    record = regular(
        last_activity_at=NOW - timedelta(days=8),
        inactivity_warned_at=NOW - timedelta(days=8),
        scheduled_delete_at=NOW,
    )
    _, _, delete = await run_lifecycle(record)
    check(delete.await_count == 1, "경고와 같은 시각의 활동은 취소 조건이 아님")
    check(record["discord_deleted_at"] == NOW, "삭제 성공 시 삭제 시각 저장")

    record = regular(
        inactivity_warned_at=NOW - timedelta(days=8),
        scheduled_delete_at=NOW - timedelta(days=1),
    )
    _, _, delete = await run_lifecycle(record, delete_result=False)
    check(delete.await_count == 1, "예약 만료 시 삭제 시도")
    check(record["discord_deleted_at"] is None, "삭제 실패 시 삭제 시각 미저장")

    record = regular(discord_deleted_at=NOW)
    host, guild, delete = await run_lifecycle(record)
    check(guild.fetch_member.await_count == 0, "이미 삭제된 모임은 HOST 조회 안 함")
    check(host.send.await_count == 0, "이미 삭제된 모임은 DM 안 함")
    check(delete.await_count == 0, "이미 삭제된 모임은 재삭제 안 함")

    _, guild, delete = await run_lifecycle(regular(), missing_guild=True)
    check(guild.fetch_member.await_count == 0, "서버 미조회 시 처리 중단")
    check(delete.await_count == 0, "서버 미조회 시 삭제 안 함")


async def test_activity_tracking():
    record = regular(
        inactivity_warned_at=NOW - timedelta(days=1),
        scheduled_delete_at=NOW + timedelta(days=6),
    )
    repository = InMemoryMeetingRepository(regular_meetings={100: record})
    message = SimpleNamespace(
        author=SimpleNamespace(bot=False),
        guild=object(),
        channel=SimpleNamespace(category=SimpleNamespace(id=100)),
    )
    await message_handler.handle_message(message, repository)
    check(record["last_activity_at"] == NOW, "regular 활동 시각 갱신")
    check(record["inactivity_warned_at"] is None, "regular 활동 시 경고 취소")
    check(record["scheduled_delete_at"] is None, "regular 활동 시 삭제 예약 취소")

    ignored = (
        SimpleNamespace(
            author=SimpleNamespace(bot=True),
            guild=object(),
            channel=message.channel,
        ),
        SimpleNamespace(
            author=SimpleNamespace(bot=False),
            guild=None,
            channel=message.channel,
        ),
        SimpleNamespace(
            author=SimpleNamespace(bot=False),
            guild=object(),
            channel=SimpleNamespace(category=None),
        ),
        SimpleNamespace(
            author=SimpleNamespace(bot=False),
            guild=object(),
            channel=SimpleNamespace(category=SimpleNamespace(id=999)),
        ),
    )
    before = record["last_activity_at"]
    for ignored_message in ignored:
        await message_handler.handle_message(ignored_message, repository)
    check(record["last_activity_at"] == before, "무관한 메시지는 상태를 변경하지 않음")


async def test_wiring():
    repository = InMemoryMeetingRepository(regular_meetings={100: regular()})
    bot.repository = repository
    bot.handle_message = AsyncMock()
    message = object()
    await bot.on_message(message)
    bot.handle_message.assert_awaited_once_with(message, repository)
    check(bot.intents.value == discord.Intents.default().value, "기본 intents 유지")

    client = SimpleNamespace(wait_until_ready=AsyncMock())
    loop = lifecycle.create_lifecycle_task(client, InMemoryMeetingRepository())
    await loop._before_loop()
    client.wait_until_ready.assert_awaited_once()
    check(loop.seconds == 60.0, "테스트 검사 주기 60초")


async def main():
    await test_creation_policy()
    await test_regular_lifecycle()
    await test_activity_tracking()
    await test_wiring()
    print(f"PASS: {checks} policy and regression assertions passed.")


asyncio.run(main())
