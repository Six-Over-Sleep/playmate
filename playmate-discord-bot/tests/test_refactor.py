"""Discord와 DB에 연결하지 않는 정책 회귀 테스트 (mock 테스트).

모임 채널 구조(모임 하나에 채널 하나), 7일 경고 + 24시간 삭제 정책, 채널 ID 기준 활동 감지,
상시 오픈채팅 채널, 삭제 안전 확인을 가짜 Discord 객체로 확인한다. 실제 Discord 서버 동작은
이 테스트로 증명하지 않는다.
"""

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
import config
from config import KST
from handlers import message_handler
from repositories.meeting_repository import InMemoryMeetingRepository
from services import lifecycle, meeting_space, official_channels

NOW = datetime(2026, 10, 12, 11, 30, tzinfo=KST)


class Clock:
    @classmethod
    def now(cls, timezone):
        return NOW


lifecycle.datetime = Clock
message_handler.datetime = Clock
REAL_DELETE_MEETING_CHANNEL = lifecycle.delete_meeting_channel  # run_lifecycle이 mock으로 바꾸기 전의 실제 함수
checks = 0


def check(condition, label):
    global checks
    assert condition, label
    checks += 1


def meeting(**changes):
    record = {
        "recruit_id": 2,
        "channel_id": 100,
        "last_activity_at": NOW - timedelta(days=8),
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


class FakeMember:
    """overwrite 딕셔너리의 키로 쓸 수 있는 가짜 멤버."""

    def __init__(self, member_id):
        self.id = member_id


class FakeTextChannel:
    """삭제 안전 확인을 시험하는 가짜 텍스트 채널."""

    def __init__(self, channel_id, topic, channel_type=discord.ChannelType.text):
        self.id, self.topic, self.type, self.name = channel_id, topic, channel_type, f"ch{channel_id}"
        self.delete = AsyncMock()
        self.send = AsyncMock()
        self.messages = []  # 최신순 Discord 기록
        self.history_error = None

    def history(self, limit=None):
        return fake_history(self.messages, self.history_error)


def fake_history(messages, error=None):
    """channel.history(...)처럼 최신 메시지부터 내놓는 async iterator."""
    async def generate():
        if error is not None:
            raise error
        for message in messages:
            yield message
    return generate()


def history_message(created_at, *, bot_author=False):
    return SimpleNamespace(created_at=created_at, author=SimpleNamespace(bot=bot_author))


def fake_guild(channels=None, categories=()):
    channels = channels or {}
    return SimpleNamespace(
        default_role=object(),
        categories=list(categories),
        text_channels=[c for c in channels.values()],
        get_channel=lambda channel_id: channels.get(channel_id),
        fetch_channel=AsyncMock(side_effect=discord_error("NotFound")),
        fetch_member=AsyncMock(return_value=FakeMember(7)),
        create_category=AsyncMock(),
        create_text_channel=AsyncMock(),
        create_voice_channel=AsyncMock(),
    )


# ---------------------------------------------------------------- 설정 정책
def test_policy_constants():
    check(config.INACTIVITY_DAYS == 7 and config.INACTIVITY_GRACE_HOURS == 24,
          "비활성 정책: 7일 무활동 + 24시간 유예")
    check(not hasattr(config, "INACTIVITY_GRACE_DAYS"), "예전 30일/7일 유예 상수는 폐기")
    check(config.CHECK_INTERVAL_SECONDS == 60, "테스트 모드 점검 주기 60초")
    check(config.CHANNEL_RECRUIT_MODES == ("regular", "short"), "regular / short 모두 채널 대상")
    check(config.OFFICIAL_CHANNEL_NAMES == ("자격증-정보공유", "기술스택-정보공유", "직무-정보공유"),
          "상시 오픈채팅은 큰 분류 3개만")


# ---------------------------------------------------------------- 채널 구조
async def test_channel_structure():
    category = SimpleNamespace(id=10, name="모임별 채널", channels=[])
    channel = SimpleNamespace(id=11, name="파이썬 스터디")
    guild = fake_guild(categories=[category])
    guild.create_text_channel = AsyncMock(return_value=channel)

    created = await meeting_space.create_meeting_channel(guild, "파이썬 스터디", 5, [7], "PUBLIC")
    check(created is channel, "모임 채널 하나를 만든다")
    check(guild.create_category.await_count == 0, "공용 카테고리가 있으면 새 카테고리를 만들지 않는다")
    check(guild.create_text_channel.await_count == 1, "텍스트 채널은 정확히 하나")
    check(guild.create_voice_channel.await_count == 0, "음성 채널은 만들지 않는다")
    kwargs = guild.create_text_channel.await_args.kwargs
    check(kwargs["category"] is category, "공용 카테고리 아래에 만든다")
    check(kwargs["topic"].startswith("PlayMate 모임 #5 "), "채널 주제에 recruit_id 표지")
    overwrites = kwargs["overwrites"]
    member_overwrite = overwrites[guild.fetch_member.return_value]
    check(member_overwrite.send_messages is True and member_overwrite.view_channel is True,
          "참여자는 보기/읽기/쓰기")
    check(overwrites[guild.default_role].send_messages is False
          and overwrites[guild.default_role].view_channel is True, "PUBLIC 비참여자는 읽기만")
    check(member_overwrite.manage_channels is None and member_overwrite.manage_messages is None,
          "HOST를 포함해 누구에게도 채널 관리 권한을 주지 않는다")

    # 모임별 Category를 만들지 않고, 공용 카테고리가 없을 때만 한 번 만든다
    guild = fake_guild(categories=[])
    guild.create_category = AsyncMock(return_value=SimpleNamespace(id=20, name="모임별 채널", channels=[]))
    guild.create_text_channel = AsyncMock(return_value=channel)
    await meeting_space.create_meeting_channel(guild, "A", 1)
    await meeting_space.create_meeting_channel(guild, "B", 2)
    check(guild.create_category.await_count == 2, "공용 카테고리가 없으면 만든다 (모임마다 만들지는 않음: 아래 확인)")

    # 가득 찬 공용 카테고리는 "모임별 채널 2"로 넘어간다
    full = SimpleNamespace(id=30, name="모임별 채널", channels=list(range(config.MEETING_CATEGORY_CHANNEL_LIMIT)))
    second = SimpleNamespace(id=31, name="모임별 채널 2", channels=[])
    guild = fake_guild(categories=[full, second])
    guild.create_text_channel = AsyncMock(return_value=channel)
    await meeting_space.create_meeting_channel(guild, "C", 3)
    check(guild.create_text_channel.await_args.kwargs["category"] is second, "50개가 찬 카테고리는 다음 공용 카테고리 사용")

    try:
        await meeting_space.create_meeting_channel(guild, "D", 4, visibility="SECRET")
    except ValueError:
        pass
    else:
        raise AssertionError("알 수 없는 visibility는 거부해야 함")
    check(True, "잘못된 visibility 거부")


# ---------------------------------------------------------------- 삭제 안전
async def test_delete_safety():
    topic = "PlayMate 모임 #5 (PUBLIC)"
    target = FakeTextChannel(11, topic)
    other = FakeTextChannel(12, "PlayMate 모임 #6 (PUBLIC)")
    category = FakeTextChannel(13, None, discord.ChannelType.category)
    official = FakeTextChannel(14, topic)
    guild = fake_guild({11: target, 12: other, 13: category, 14: official})

    ok = await meeting_space.delete_meeting_channel(guild, 11, 5)
    check(ok and target.delete.await_count == 1, "매핑된 채널 하나를 삭제한다")
    check(other.delete.await_count == 0 and category.delete.await_count == 0,
          "다른 모임 채널과 카테고리는 삭제하지 않는다")

    ok = await meeting_space.delete_meeting_channel(guild, 12, 5)
    check(not ok and other.delete.await_count == 0, "주제의 recruit_id가 다르면 삭제하지 않는다")
    ok = await meeting_space.delete_meeting_channel(guild, 13, 5)
    check(not ok and category.delete.await_count == 0, "카테고리는 삭제하지 않는다")
    ok = await meeting_space.delete_meeting_channel(guild, 14, 5, protected_ids={14})
    check(not ok and official.delete.await_count == 0, "보호된 채널은 삭제하지 않는다")

    ok = await meeting_space.delete_meeting_channel(fake_guild({}), 99, 5)
    check(ok, "이미 없는 채널(NotFound)은 삭제된 것으로 본다")
    unknown_guild = fake_guild({})
    unknown_guild.fetch_channel = AsyncMock(side_effect=discord_error("Forbidden"))
    ok = await meeting_space.delete_meeting_channel(unknown_guild, 99, 5)
    check(not ok, "조회가 불명확하면(Forbidden) 삭제 완료로 보지 않는다")
    failing = FakeTextChannel(15, "PlayMate 모임 #5 (PUBLIC)")
    failing.delete = AsyncMock(side_effect=discord_error("Forbidden"))
    ok = await meeting_space.delete_meeting_channel(fake_guild({15: failing}), 15, 5)
    check(not ok, "삭제 권한이 없으면 실패")


# ---------------------------------------------------------------- 7일 + 24시간 lifecycle
async def run_lifecycle(record, *, delete_result=True, missing_guild=False, send_failure=None,
                        messages=(), history_error=None):
    """가짜 서버에서 lifecycle을 한 번 실행한다. 삭제가 성공하면 이후 API가 NotFound를 돌려준다."""
    gone = {"value": False}
    channel = SimpleNamespace(
        id=100, send=AsyncMock(side_effect=send_failure),
        history=lambda limit=None: fake_history(list(messages), history_error),
    )

    async def fetch_channel(channel_id):
        if gone["value"]:
            raise discord_error("NotFound")
        return channel

    guild = SimpleNamespace(
        get_channel=Mock(side_effect=lambda channel_id: None if gone["value"] else channel),
        fetch_channel=fetch_channel,
    )
    client = SimpleNamespace(get_guild=Mock(return_value=None if missing_guild else guild))
    repository = InMemoryMeetingRepository(meetings={} if record is None else {100: record})

    async def delete_channel(*args, **kwargs):
        if delete_result:
            gone["value"] = True
        return delete_result

    delete = AsyncMock(side_effect=delete_channel)
    lifecycle.delete_meeting_channel = delete
    await lifecycle.check_meeting_lifecycle(client, repository)
    return channel, guild, delete


async def test_inactivity_policy():
    # 7일 미만이면 경고도 삭제도 없다
    record = meeting(last_activity_at=NOW - timedelta(days=6, hours=23))
    channel, _, delete = await run_lifecycle(record)
    check(channel.send.await_count == 0, "7일 미만이면 경고 메시지가 없다")
    check(record["inactivity_warned_at"] is None and delete.await_count == 0, "7일 미만이면 예약/삭제 없음")

    # 7일이면 모임 채널에 경고 (DM 아님) + 24시간 뒤 삭제 예약
    record = meeting(last_activity_at=NOW - timedelta(days=7))
    channel, _, delete = await run_lifecycle(record)
    check(channel.send.await_count == 1, "7일 무활동이면 모임 채널에 경고 메시지")
    text = channel.send.await_args.args[0]
    check("7일" in text and "24시간" in text and "삭제" in text, "경고 문구에 7일/24시간/삭제 안내")
    check(record["inactivity_warned_at"] == NOW, "경고 시각 저장")
    check(record["scheduled_delete_at"] == NOW + timedelta(hours=24), "24시간 뒤 삭제 예약")
    check(delete.await_count == 0, "경고 직후에는 삭제하지 않는다")

    # 이미 경고했으면 같은 경고를 반복하지 않는다
    channel, _, delete = await run_lifecycle(record)
    check(channel.send.await_count == 0 and delete.await_count == 0, "경고 후 24시간 전에는 재경고/삭제 없음")

    # 경고 메시지 전송 실패는 예약을 저장하지 않는다 (다음 주기에 재시도)
    for kind in ("NotFound", "Forbidden", "HTTPException"):
        record = meeting()
        await run_lifecycle(record, send_failure=discord_error(kind))
        check(record["inactivity_warned_at"] is None and record["scheduled_delete_at"] is None,
              f"{kind} 경고 전송 실패 시 예약 미저장")

    # 24시간이 지났고 활동이 없으면 삭제
    record = meeting(
        last_activity_at=NOW - timedelta(days=9),
        inactivity_warned_at=NOW - timedelta(hours=25),
        scheduled_delete_at=NOW - timedelta(hours=1),
    )
    channel, _, delete = await run_lifecycle(record)
    check(delete.await_count == 1, "24시간 뒤 활동이 없으면 채널 삭제")
    check(record["discord_deleted_at"] == NOW, "삭제 확인 후 discord_deleted_at 기록")
    check(delete.await_args.args[1] == 100 and delete.await_args.args[2] == 2,
          "삭제 대상은 매핑된 채널 하나 (channel_id, recruit_id)")

    # 24시간이 지나기 전에는 삭제하지 않는다
    record = meeting(
        last_activity_at=NOW - timedelta(days=8),
        inactivity_warned_at=NOW - timedelta(hours=23),
        scheduled_delete_at=NOW + timedelta(hours=1),
    )
    _, _, delete = await run_lifecycle(record)
    check(delete.await_count == 0, "24시간 전에는 삭제하지 않는다")

    # 경고 이후 활동이 있으면 삭제하지 않고 예약을 취소한다 (삭제 직전 재확인)
    record = meeting(
        last_activity_at=NOW - timedelta(hours=2),
        inactivity_warned_at=NOW - timedelta(hours=25),
        scheduled_delete_at=NOW - timedelta(hours=1),
    )
    _, _, delete = await run_lifecycle(record)
    check(delete.await_count == 0, "삭제 직전 활동이 있으면 삭제하지 않는다")
    check(record["inactivity_warned_at"] is None and record["scheduled_delete_at"] is None, "예약 취소")

    # 삭제가 실패하면 삭제 완료로 기록하지 않는다
    record = meeting(
        inactivity_warned_at=NOW - timedelta(hours=25),
        scheduled_delete_at=NOW - timedelta(hours=1),
    )
    _, _, delete = await run_lifecycle(record, delete_result=False)
    check(delete.await_count == 1 and record["discord_deleted_at"] is None, "삭제 실패 시 삭제 완료 미기록")

    # 이미 삭제 기록된 모임, 서버를 못 찾은 경우
    record = meeting(discord_deleted_at=NOW)
    channel, _, delete = await run_lifecycle(record)
    check(channel.send.await_count == 0 and delete.await_count == 0, "삭제 완료된 모임은 건드리지 않는다")
    channel, _, delete = await run_lifecycle(meeting(), missing_guild=True)
    check(channel.send.await_count == 0 and delete.await_count == 0, "서버를 못 찾으면 아무것도 하지 않는다")


# ---------------------------------------------------------------- 활동 재개와 삭제 사이의 경쟁
def due_record(**changes):
    values = dict(
        last_activity_at=NOW - timedelta(days=9),
        inactivity_warned_at=NOW - timedelta(hours=25),
        scheduled_delete_at=NOW - timedelta(hours=1),
    )
    values.update(changes)
    return meeting(**values)


def race_setup(record):
    """실제 delete_meeting_channel과 가짜 서버로 삭제 경쟁을 시험할 준비. 삭제하면 채널이 서버에서 사라진다."""
    channel = FakeTextChannel(100, "PlayMate 모임 #2 (PUBLIC)")
    channels = {100: channel}

    async def fetch_channel(channel_id):
        if channel_id in channels:
            return channels[channel_id]
        raise discord_error("NotFound")

    async def really_delete(reason=None):
        channels.pop(100, None)

    channel.delete = AsyncMock(side_effect=really_delete)
    guild = SimpleNamespace(get_channel=lambda channel_id: channels.get(channel_id), fetch_channel=fetch_channel)
    client = SimpleNamespace(get_guild=Mock(return_value=guild))
    lifecycle.delete_meeting_channel = REAL_DELETE_MEETING_CHANNEL
    return channel, client


class RacingRepository(InMemoryMeetingRepository):
    """is_delete_due가 True를 돌려준 직후 사용자 메시지가 도착하는 상황을 만든다."""

    def __init__(self, *args, loop, **kwargs):
        super().__init__(*args, **kwargs)
        self.loop, self.on_due, self.handlers = loop, None, []

    def is_delete_due(self, channel_id, now):
        result = super().is_delete_due(channel_id, now)
        if result and self.on_due is not None:
            hook, self.on_due = self.on_due, None
            # worker thread에서 호출된다: 메시지 이벤트가 판정 직후 이벤트 루프에 도착한다.
            self.loop.call_soon_threadsafe(lambda: self.handlers.append(self.loop.create_task(hook())))
        return result


async def test_activity_delete_race():
    loop = asyncio.get_running_loop()

    # 1) 삭제 대상 확인(is_delete_due=True) 직후 사용자 메시지가 도착 -> 채널을 지우지 않고 예약을 취소한다
    record = due_record()
    channel, client = race_setup(record)
    repository = RacingRepository(meetings={100: record}, loop=loop)
    message = channel_message(100)
    repository.on_due = lambda: message_handler.handle_message(message, repository)
    await lifecycle.check_meeting_lifecycle(client, repository)
    await asyncio.gather(*repository.handlers)
    check(channel.delete.await_count == 0, "삭제 판정 직후 메시지가 오면 채널을 삭제하지 않는다")
    check(record["scheduled_delete_at"] is None and record["inactivity_warned_at"] is None
          and record["last_activity_at"] == NOW and record["discord_deleted_at"] is None,
          "활동이 기록되고 삭제 예약이 취소된다")
    check(message.channel.send.await_count == 1
          and message.channel.send.await_args.args[0] == lifecycle.DELETE_CANCELLED_TEXT,
          "취소 안내가 한 번 나가고, 그 뒤에 삭제 작업이 채널을 지우지 않는다")
    check(100 not in lifecycle._delete_in_flight, "삭제 시도 표시는 항상 정리된다")
    await lifecycle.check_meeting_lifecycle(client, repository)
    check(channel.delete.await_count == 0, "취소된 뒤 다음 점검에서도 삭제되지 않는다")

    # 2) 삭제 호출이 이미 진행 중일 때 도착한 메시지: 활동 처리는 삭제가 끝난 뒤에 실행되어
    #    이미 삭제된 모임에 취소 안내를 보내거나 예약을 "취소"하지 않는다
    record = due_record()
    channel, client = race_setup(record)
    repository = InMemoryMeetingRepository(meetings={100: record})
    message = channel_message(100)
    handlers = []
    real_delete = channel.delete.side_effect

    async def delete_while_message_arrives(reason=None):
        handlers.append(asyncio.create_task(message_handler.handle_message(message, repository)))
        await asyncio.sleep(0.3)  # 메시지 이벤트가 삭제 도중에 처리되려고 시도할 시간을 준다 (worker thread 포함)
        check(record["scheduled_delete_at"] is not None, "삭제 진행 중에는 활동 처리가 예약을 취소하지 못한다 (채널 락)")
        await real_delete(reason)

    channel.delete.side_effect = delete_while_message_arrives
    await lifecycle.check_meeting_lifecycle(client, repository)
    await asyncio.gather(*handlers)
    check(channel.delete.await_count == 1 and record["discord_deleted_at"] == NOW, "삭제가 시작된 뒤에는 그대로 완료된다")
    check(record["scheduled_delete_at"] is not None and message.channel.send.await_count == 0,
          "삭제된 모임에는 취소 안내를 보내지 않고 예약을 바꾸지 않는다")

    # 3) 메시지 이벤트가 아직 도착하지 않았어도 Discord 기록의 사용자 메시지를 삭제 직전에 확인한다
    record = due_record()
    channel, client = race_setup(record)
    repository = InMemoryMeetingRepository(meetings={100: record})
    channel.messages = [history_message(NOW - timedelta(hours=2))]
    await lifecycle.check_meeting_lifecycle(client, repository)
    check(channel.delete.await_count == 0, "Discord 기록에 경고 이후 사용자 메시지가 있으면 삭제하지 않는다")
    check(record["scheduled_delete_at"] is None and record["last_activity_at"] == NOW - timedelta(hours=2),
          "발견한 메시지 시각으로 활동을 기록하고 예약을 취소한다")
    check(channel.send.await_count == 1 and channel.send.await_args.args[0] == lifecycle.DELETE_CANCELLED_TEXT,
          "취소 안내를 보낸다")

    # 4) Bot 메시지와 경고 이전 메시지는 사용자 활동이 아니다 -> 삭제된다
    record = due_record()
    channel, client = race_setup(record)
    repository = InMemoryMeetingRepository(meetings={100: record})
    channel.messages = [
        history_message(NOW - timedelta(hours=3), bot_author=True),   # 경고/취소 안내 같은 Bot 메시지
        history_message(NOW - timedelta(hours=30)),                    # 경고(25시간 전) 이전의 사용자 메시지
        history_message(NOW - timedelta(hours=40)),
    ]
    await lifecycle.check_meeting_lifecycle(client, repository)
    check(channel.delete.await_count == 1 and record["discord_deleted_at"] == NOW,
          "Bot 메시지와 경고 이전 메시지만 있으면 사용자 활동으로 세지 않고 삭제한다")

    # 5) Discord 기록을 확인할 수 없으면 지우지 않고 다음 주기에 다시 시도한다
    for kind in ("Forbidden", "HTTPException"):
        record = due_record()
        channel, client = race_setup(record)
        channel.history_error = discord_error(kind)
        repository = InMemoryMeetingRepository(meetings={100: record})
        await lifecycle.check_meeting_lifecycle(client, repository)
        check(channel.delete.await_count == 0 and record["discord_deleted_at"] is None
              and record["scheduled_delete_at"] is not None, f"{kind}: 최근 메시지를 확인하지 못하면 삭제를 보류")

    # 6) 안전 확인을 모두 마치고 channel.delete() 직전에 활동 표시가 들어와도 한 번 더 막는다
    record = due_record()
    channel, client = race_setup(record)
    repository = InMemoryMeetingRepository(meetings={100: record})
    original_get = client.get_guild.return_value.get_channel
    seen = []

    def get_channel_then_message(channel_id):
        seen.append(channel_id)
        if len(seen) == 2:  # delete_meeting_channel 안의 조회 = 안전 확인을 마치고 삭제하기 직전
            lifecycle.note_activity(100)
        return original_get(channel_id)

    client.get_guild.return_value.get_channel = get_channel_then_message
    await lifecycle.check_meeting_lifecycle(client, repository)
    check(channel.delete.await_count == 0 and record["discord_deleted_at"] is None,
          "삭제 직전에 들어온 활동 표시가 channel.delete() 호출을 막는다")

    # 7) 활동 처리와 lifecycle은 같은 채널 락을 쓴다
    record = meeting()
    repository = InMemoryMeetingRepository(meetings={100: record})
    async with lifecycle.channel_lock(100):
        task = asyncio.create_task(message_handler.handle_message(channel_message(100), repository))
        await asyncio.sleep(0.3)
        check(record["last_activity_at"] != NOW, "채널 락이 잡혀 있는 동안 활동 처리는 기다린다")
    await task
    check(record["last_activity_at"] == NOW, "락이 풀리면 활동이 기록된다")


# ---------------------------------------------------------------- 채널 ID 기준 활동 감지
def channel_message(channel_id, *, bot_author=False, guild=True):
    channel = SimpleNamespace(id=channel_id, send=AsyncMock())
    return SimpleNamespace(
        author=SimpleNamespace(bot=bot_author),
        guild=object() if guild else None,
        channel=channel,
    )


async def test_activity_tracking():
    record = meeting(
        inactivity_warned_at=NOW - timedelta(hours=1),
        scheduled_delete_at=NOW + timedelta(hours=23),
    )
    repository = InMemoryMeetingRepository(meetings={100: record})
    message = channel_message(100)
    await message_handler.handle_message(message, repository)
    check(record["last_activity_at"] == NOW, "채널 ID로 모임을 찾아 활동 시각 갱신")
    check(record["inactivity_warned_at"] is None, "활동 시 경고 초기화")
    check(record["scheduled_delete_at"] is None, "활동 시 삭제 예약 취소")
    check(message.channel.send.await_count == 1
          and message.channel.send.await_args.args[0] == lifecycle.DELETE_CANCELLED_TEXT,
          "예약이 있었다면 채널에 취소 안내 메시지")

    # 예약이 없던 채널의 활동에는 안내 메시지를 보내지 않는다
    quiet = meeting()
    repository = InMemoryMeetingRepository(meetings={100: quiet})
    message = channel_message(100)
    await message_handler.handle_message(message, repository)
    check(message.channel.send.await_count == 0, "예약이 없었으면 안내 메시지 없음")

    # 취소 안내 전송이 실패해도 활동 기록과 예약 취소는 유지된다
    record = meeting(inactivity_warned_at=NOW - timedelta(hours=1), scheduled_delete_at=NOW + timedelta(hours=23))
    repository = InMemoryMeetingRepository(meetings={100: record})
    message = channel_message(100)
    message.channel.send = AsyncMock(side_effect=discord_error("Forbidden"))
    await message_handler.handle_message(message, repository)
    check(record["scheduled_delete_at"] is None and record["last_activity_at"] == NOW,
          "안내 전송 실패에도 예약 취소/활동 기록은 유지")

    # 무관한 메시지는 상태를 바꾸지 않는다 (Bot, DM, 다른 채널, 상시 채널)
    record = meeting()
    repository = InMemoryMeetingRepository(meetings={100: record})
    before = dict(record)
    for ignored in (
        channel_message(100, bot_author=True),
        channel_message(100, guild=False),
        channel_message(999),
    ):
        await message_handler.handle_message(ignored, repository)
    check(record == before, "Bot/DM/다른 채널 메시지는 무시")

    # 다른 모임의 채널 메시지는 그 모임만 갱신한다
    other = meeting(recruit_id=3, channel_id=200)
    repository = InMemoryMeetingRepository(meetings={100: meeting(), 200: other})
    await message_handler.handle_message(channel_message(200), repository)
    check(other["last_activity_at"] == NOW and repository.get_managed_meeting(100)["last_activity_at"] != NOW,
          "메시지가 온 채널의 모임만 활동 처리")


# ---------------------------------------------------------------- 상시 오픈채팅
async def test_official_channels():
    official_channels.PROTECTED_CHANNEL_IDS.clear()
    created = []
    category = SimpleNamespace(id=50, name=config.OFFICIAL_CATEGORY_NAME)
    existing = SimpleNamespace(id=61, name="자격증-정보공유")

    async def create_text_channel(name, category=None, **kwargs):
        channel = SimpleNamespace(id=70 + len(created), name=name)
        created.append(name)
        return channel

    guild = SimpleNamespace(
        categories=[category], text_channels=[existing],
        create_category=AsyncMock(), create_text_channel=create_text_channel,
    )
    channels = await official_channels.ensure_official_channels(guild)
    check(created == ["기술스택-정보공유", "직무-정보공유"], "없는 채널만 만든다 (있는 채널은 재사용)")
    check(len(channels) == 3 and guild.create_category.await_count == 0, "큰 분류 3개, 카테고리 재사용")
    check(61 in official_channels.PROTECTED_CHANNEL_IDS
          and all(c.id in official_channels.PROTECTED_CHANNEL_IDS for c in channels), "모두 삭제 보호 목록에 등록")

    # 다시 시작해도 중복 생성하지 않는다
    guild.text_channels = list(channels)
    created.clear()
    await official_channels.ensure_official_channels(guild)
    check(created == [], "두 번째 확인에서는 아무것도 만들지 않는다")

    # 카테고리가 없으면 한 번 만든다. 채널 하나가 실패해도 나머지는 계속한다
    created.clear()
    new_category = SimpleNamespace(id=55, name=config.OFFICIAL_CATEGORY_NAME)
    calls = []

    async def flaky_create(name, category=None, **kwargs):
        calls.append(name)
        if name == "기술스택-정보공유":
            raise discord_error("HTTPException")
        return SimpleNamespace(id=80 + len(calls), name=name)

    guild = SimpleNamespace(
        categories=[], text_channels=[],
        create_category=AsyncMock(return_value=new_category), create_text_channel=flaky_create,
    )
    channels = await official_channels.ensure_official_channels(guild)
    check(guild.create_category.await_count == 1 and len(channels) == 2 and len(calls) == 3,
          "카테고리 생성, 채널 하나 실패해도 나머지 계속")

    # 상시 채널은 삭제 함수가 거부하고, DB 행이 없어 lifecycle 대상도 아니다
    protected = FakeTextChannel(61, "PlayMate 모임 #1 (PUBLIC)")
    guild = fake_guild({61: protected})
    ok = await meeting_space.delete_meeting_channel(guild, 61, 1, official_channels.PROTECTED_CHANNEL_IDS)
    check(not ok and protected.delete.await_count == 0, "보호 목록 채널은 삭제 거부")
    repository = InMemoryMeetingRepository()
    check(repository.get_managed_meeting(61) is None and repository.list_managed_meetings() == [],
          "상시 채널은 모임 저장소에 없다 (자동삭제 대상 아님)")


# ---------------------------------------------------------------- 배선
async def test_wiring():
    repository = InMemoryMeetingRepository(meetings={100: meeting()})
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

    # 상시 채널 확인은 한 번 성공하면 재연결 때 반복하지 않고, 실패해도 예외를 밖으로 내지 않는다
    calls = []

    async def fake_ensure(guild):
        calls.append(guild)
        return [SimpleNamespace(name=name) for name in config.OFFICIAL_CHANNEL_NAMES]

    original = bot.ensure_official_channels
    bot.ensure_official_channels = fake_ensure
    bot.official_channels_ready = False
    await bot.ensure_official_channels_once("guild")
    await bot.ensure_official_channels_once("guild")
    check(len(calls) == 1 and bot.official_channels_ready, "상시 채널 확인은 성공 후 반복하지 않는다")

    async def failing_ensure(guild):
        raise RuntimeError("boom")

    bot.ensure_official_channels = failing_ensure
    bot.official_channels_ready = False
    await bot.ensure_official_channels_once("guild")
    check(not bot.official_channels_ready, "상시 채널 확인 실패는 삼키고 다음 on_ready에 재시도")
    bot.ensure_official_channels = original

    # 필수 3개가 모두 있을 때만 완료: 일부만 만들어지면 완료로 보지 않고, 재시도는 누락된 채널만 만든다
    state = {"fail": True}
    made = []
    category = SimpleNamespace(id=50, name=config.OFFICIAL_CATEGORY_NAME)

    async def create_text_channel(name, category=None, **kwargs):
        if state["fail"] and name == "기술스택-정보공유":
            raise discord_error("HTTPException")
        created = SimpleNamespace(id=100 + len(made), name=name)
        made.append(name)
        guild.text_channels.append(created)
        return created

    guild = SimpleNamespace(categories=[category], text_channels=[], create_category=AsyncMock(),
                            create_text_channel=create_text_channel)
    bot.official_channels_ready = False
    await bot.ensure_official_channels_once(guild)
    check(made == ["자격증-정보공유", "직무-정보공유"] and not bot.official_channels_ready,
          "3개 중 일부만 만들어지면 완료로 판단하지 않는다")
    state["fail"] = False
    await bot.ensure_official_channels_once(guild)
    check(made == ["자격증-정보공유", "직무-정보공유", "기술스택-정보공유"] and bot.official_channels_ready,
          "재시도는 누락된 채널만 만들고, 3개가 모두 있으면 완료")
    await bot.ensure_official_channels_once(guild)
    check(len(made) == 3, "완료 후에는 다시 만들지 않는다")

    # 재시도 task: 완료되지 않았으면 on_ready 외에도 주기적으로 다시 시도하고, 완료되면 멈춘다
    check(bot.retry_official_channels.minutes == config.OFFICIAL_RETRY_MINUTES, "상시 채널 재시도 주기")
    state["fail"] = True
    made.clear()
    guild.text_channels.clear()
    bot.official_channels_ready = False
    original_get_guild = bot.client.get_guild
    bot.client.get_guild = lambda guild_id: guild
    await bot.retry_official_channels.coro()
    check(made == [], "재시도 task의 첫 실행은 건너뛴다 (on_ready가 방금 시도함)")
    bot.retry_official_channels._current_loop = 1
    await bot.retry_official_channels.coro()
    check(not bot.official_channels_ready and len(made) == 2, "재시도에서도 실패한 채널은 계속 미완료")
    state["fail"] = False
    await bot.retry_official_channels.coro()
    check(bot.official_channels_ready and sorted(made) == sorted(config.OFFICIAL_CHANNEL_NAMES),
          "재시도로 누락된 채널이 만들어지면 완료")
    bot.retry_official_channels._current_loop = 0
    bot.client.get_guild = original_get_guild


async def main():
    test_policy_constants()
    await test_channel_structure()
    await test_delete_safety()
    await test_inactivity_policy()
    await test_activity_delete_race()
    await test_activity_tracking()
    await test_official_channels()
    await test_wiring()
    print(f"PASS: {checks} policy and regression assertions passed.")


asyncio.run(main())
