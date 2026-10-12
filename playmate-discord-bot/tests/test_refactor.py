import ast
import asyncio
import copy
import io
import os
import sys
from contextlib import redirect_stdout
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
from services import lifecycle, meeting_space, permissions

NOW = datetime(2026, 10, 12, 11, 30, tzinfo=KST)
class Clock:
    @classmethod
    def now(cls, tz):
        return NOW

source = (ROOT / "tests" / "fixtures" / "original_bot.py").read_text(encoding="utf-8-sig")
tree = ast.parse(source)
namespace = {
    "discord": discord, "datetime": Clock, "timedelta": timedelta,
    "KST": KST, "GUILD_ID": 1, "TEST_MODE": True,
    "INACTIVITY_DAYS": 30, "INACTIVITY_GRACE_DAYS": 7,
    "ONE_TIME_DELETE_GRACE_HOURS": 24,
}
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        node.decorator_list = []
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<original>", "exec"), namespace)
lifecycle.datetime = Clock
message_handler.datetime = Clock
checks = 0

def equal(a, b, label):
    global checks
    assert a == b, f"{label}: {a!r} != {b!r}"
    checks += 1

def executable_ast(node):
    """Ignore documentation-only changes when comparing executable logic."""
    node = copy.deepcopy(node)
    if (node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)):
        node.body.pop(0)
    return ast.dump(node)

def ongoing(**changes):
    record = dict(
        recruit_id=2, host_id=7,
        last_activity_at=NOW - timedelta(days=31),
        inactivity_warned_at=None, scheduled_delete_at=None, discord_deleted_at=None,
    )
    record.update(changes)
    return record

def one_time(hours, deleted=None):
    return dict(recruit_id=1, category_id=100,
                end_at=NOW - timedelta(hours=hours), discord_deleted_at=deleted)

def discord_error(kind):
    status = {"NotFound": 404, "Forbidden": 403, "HTTPException": 500}[kind]
    return getattr(discord, kind)(SimpleNamespace(status=status, reason="test"), "test")

async def compare_lifecycle(single, ongoing_data, delete_result=True, dm_failure=None, fetch_failure=None, missing_guild=False):
    outcomes = []
    for original in (True, False):
        singles, ongoing_records = copy.deepcopy(single), copy.deepcopy(ongoing_data)
        host = SimpleNamespace(send=AsyncMock(side_effect=dm_failure))
        guild = SimpleNamespace(fetch_member=AsyncMock(return_value=host, side_effect=fetch_failure))
        client = SimpleNamespace(get_guild=Mock(return_value=None if missing_guild else guild))
        delete = AsyncMock(return_value=delete_result)
        stream = io.StringIO()
        with redirect_stdout(stream):
            if original:
                namespace.update(TEST_ONE_TIME_MEETINGS=singles, TEST_ONGOING_MEETINGS=ongoing_records,
                                 client=client, delete_meeting_space=delete)
                await namespace["check_meeting_lifecycle"]()
            else:
                lifecycle.delete_meeting_space = delete
                await lifecycle.check_meeting_lifecycle(client, InMemoryMeetingRepository(singles, ongoing_records))
        outcomes.append((singles, ongoing_records, stream.getvalue(),
                         [(c.kwargs["category_id"]) for c in delete.await_args_list],
                         host.send.await_args_list, guild.fetch_member.await_args_list))
    equal(outcomes[0], outcomes[1], "lifecycle")

async def compare_message(record, bot_author=False, dm=False, no_category=False, unknown=False):
    outcomes = []
    for original in (True, False):
        records = {} if record is None else {100: copy.deepcopy(record)}
        # No content field: any access to message content fails this scenario.
        message = SimpleNamespace(
            author=SimpleNamespace(bot=bot_author),
            guild=None if dm else object(),
            channel=SimpleNamespace(category=None if no_category else SimpleNamespace(id=999 if unknown else 100)),
        )
        stream = io.StringIO()
        with redirect_stdout(stream):
            if original:
                namespace["TEST_ONGOING_MEETINGS"] = records
                await namespace["on_message"](message)
            else:
                await message_handler.handle_message(message, InMemoryMeetingRepository(ongoing_meetings=records))
        outcomes.append((records, stream.getvalue()))
    equal(outcomes[0], outcomes[1], "message")

async def main():
    # Copied resource/permission functions have exactly the original executable AST.
    original_functions = {
        n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for module, names in (
        (meeting_space, ("create_meeting_space", "delete_meeting_space")),
        (permissions, ("grant_participant_permissions", "remove_participant_permissions", "grant_host_permissions")),
    ):
        targets = {n.name: n for n in ast.parse(Path(module.__file__).read_text(encoding="utf-8")).body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for name in names:
            equal(executable_ast(original_functions[name]), executable_ast(targets[name]), "AST " + name)

    for hours in (23.99, 24, 25):
        await compare_lifecycle([one_time(hours)], {})
    await compare_lifecycle([one_time(25, NOW)], {})
    await compare_lifecycle([one_time(25)], {}, delete_result=False)
    await compare_lifecycle([], {})
    await compare_lifecycle([one_time(25)], {100: ongoing()}, missing_guild=True)
    for duration in (None, timedelta(days=29, hours=23, minutes=59), timedelta(days=30), timedelta(days=38)):
        activity = NOW - duration if duration is not None else None
        await compare_lifecycle([], {100: ongoing(last_activity_at=activity)})
    await compare_lifecycle([], {100: ongoing(discord_deleted_at=NOW)})
    await compare_lifecycle([], {100: ongoing(inactivity_warned_at=NOW-timedelta(days=8))})
    for schedule in (NOW+timedelta(seconds=1), NOW, NOW-timedelta(days=1)):
        await compare_lifecycle([], {100: ongoing(
            inactivity_warned_at=NOW-timedelta(days=8), scheduled_delete_at=schedule)})
    await compare_lifecycle([], {100: ongoing(
        last_activity_at=NOW-timedelta(days=7),
        inactivity_warned_at=NOW-timedelta(days=8),
        scheduled_delete_at=NOW-timedelta(days=1))})
    await compare_lifecycle([], {100: ongoing(
        last_activity_at=NOW-timedelta(days=8),
        inactivity_warned_at=NOW-timedelta(days=8),
        scheduled_delete_at=NOW-timedelta(days=1))})
    await compare_lifecycle([], {100: ongoing(
        inactivity_warned_at=NOW-timedelta(days=8),
        scheduled_delete_at=NOW-timedelta(days=1))}, delete_result=False)
    for kind in ("NotFound", "Forbidden", "HTTPException"):
        await compare_lifecycle([], {100: ongoing()}, dm_failure=discord_error(kind))
        await compare_lifecycle([], {100: ongoing()}, fetch_failure=discord_error(kind))
    for changes in ({}, {"bot_author": True}, {"dm": True}, {"no_category": True}, {"unknown": True}):
        await compare_message(ongoing(), **changes)
    await compare_message(None)
    await compare_message(ongoing(discord_deleted_at=NOW))
    for warning, schedule in ((NOW, None), (None, NOW), (NOW, NOW)):
        await compare_message(ongoing(inactivity_warned_at=warning, scheduled_delete_at=schedule))

    # Entry-point event wiring, unchanged intents and duplicate-loop guard.
    mock_repo = InMemoryMeetingRepository(ongoing_meetings={100: ongoing()})
    bot.repository = mock_repo
    bot.handle_message = AsyncMock()
    msg = object()
    await bot.on_message(msg)
    bot.handle_message.assert_awaited_once_with(msg, mock_repo)
    equal(bot.intents.value, discord.Intents.default().value, "intents")
    for missing, running in ((False, False), (False, True), (True, False)):
        outputs = []
        for original in (True, False):
            client = SimpleNamespace(user="bot", get_guild=Mock(return_value=None if missing else SimpleNamespace(name="guild")))
            loop = SimpleNamespace(is_running=Mock(return_value=running), start=Mock())
            stream = io.StringIO()
            with redirect_stdout(stream):
                if original:
                    namespace.update(client=client, check_meeting_lifecycle=loop)
                    await namespace["on_ready"]()
                else:
                    bot.client, bot.check_meeting_lifecycle = client, loop
                    await bot.on_ready()
            outputs.append((stream.getvalue(), loop.start.call_count))
        equal(outputs[0], outputs[1], "ready")
    client = SimpleNamespace(wait_until_ready=AsyncMock())
    loop = lifecycle.create_lifecycle_task(client, InMemoryMeetingRepository())
    await loop._before_loop()
    client.wait_until_ready.assert_awaited_once()
    equal(loop.seconds, 60.0, "test loop interval")
    print(f"PASS: {checks} original/refactor equivalence assertions; event wiring and readiness guard passed.")

asyncio.run(main())
