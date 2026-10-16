"""Regular meeting lifecycle policy (30-day inactivity, 7-day grace, deletion).

State changes go through purpose-specific conditional repository operations
(record_warning / cancel_schedule / mark_deleted), never a whole-snapshot save,
so activity recorded while this loop awaits Discord or the DB can not be
overwritten by stale data. discord_deleted_at is written only AFTER Discord has
deleted the space; is_delete_due is a read-only last check right before it. If
the deletion fails or its outcome is unclear nothing is persisted, so the next
cycle (or a restart) simply re-evaluates the meeting from the DB.
"""
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta

import discord
from discord.ext import tasks

from config import (
    CHECK_INTERVAL_SECONDS,
    DISCORD_LOCK_HOLD_SECONDS,
    GUILD_ID,
    INACTIVITY_DAYS,
    INACTIVITY_GRACE_DAYS,
    KST,
)
from repositories.meeting_repository import (
    GuardRejected,
    MeetingRepository,
    RegularLockUnavailable,
    call,
)
from services.meeting_space import delete_meeting_space

# One lifecycle step per meeting at a time (e.g. overlapping manual/periodic runs).
_category_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


async def check_meeting_lifecycle(
    client: discord.Client, repository: MeetingRepository
):
    """Warn and eventually delete inactive regular meeting spaces."""
    now = datetime.now(KST)
    print(f"\n[regular 모임 라이프사이클 검사] {now:%Y-%m-%d %H:%M:%S}")
    guild = client.get_guild(GUILD_ID)
    if guild is None:
        print("Discord 서버를 찾을 수 없습니다.")
        return

    for category_id, meeting in await call(repository.list_regular_meetings):
        async with _category_locks[category_id]:
            try:
                await _check_meeting(guild, repository, category_id, meeting, now)
            except Exception as error:
                # One broken meeting must not stop the others.
                print(
                    f"[regular 모임] 검사 실패 recruit_id={meeting.get('recruit_id')}: "
                    f"{error!r}"
                )


def _resource_ids(category_id: int, meeting: dict) -> list[int]:
    """The (up to) three managed Discord resources: category, text, voice."""
    return [category_id] + [
        meeting[key] for key in ("text_channel_id", "voice_channel_id")
        if meeting.get(key) is not None
    ]


async def _space_gone(guild, resource_ids: list[int], trust_cache: bool = False) -> bool:
    """True only when the Discord API reports NotFound for EVERY managed resource.

    Discord does not delete a category's channels with it, so a missing
    category alone proves nothing, and neither does a cache miss. Forbidden,
    HTTP errors, timeouts or missing guild methods count as "not gone" so a
    live resource is never recorded as deleted. With trust_cache a cached
    channel is accepted as proof that the space still exists (cheap shortcut
    for the routine per-cycle check); the final pre-mark check uses the API only.
    """
    try:
        for resource_id in resource_ids:
            if trust_cache and guild.get_channel(resource_id) is not None:
                return False
            try:
                await guild.fetch_channel(resource_id)
                return False
            except discord.NotFound:
                continue
        return True
    except Exception:
        return False


async def _delete_under_lock(guild, repository, lock, recruit_id, category_id, resource_ids, now):
    deadline = asyncio.get_running_loop().time() + DISCORD_LOCK_HOLD_SECONDS
    # Read-only last check right before deleting (nothing is written yet).
    if not await call(repository.is_delete_due, category_id, now):
        print(f"삭제 직전 상태 변경, 삭제 취소: recruit_id={recruit_id}")
        return

    print(f"\n[regular 모임 자동 종료 대상]\nrecruit_id={recruit_id}")
    await delete_meeting_space(
        guild=guild, category_id=category_id, extra_channel_ids=resource_ids[1:],
    )
    # Never trust the delete call or the cache: ask the API about all three.
    if not await _space_gone(guild, resource_ids):
        print(f"Discord 삭제 실패/불명, 다음 주기에 재시도: recruit_id={recruit_id}")
        return
    # discord_deleted_at is written only once Discord no longer has any of the
    # three resources, so a failed/unclear deletion is simply retried next cycle.
    # The write runs INSIDE the lock's transaction (same connection) and is
    # committed only when this whole block succeeds; on timeout/cancel/error it is
    # cancelled and rolled back, so it can never be committed late.
    remaining = max(1.0, deadline - asyncio.get_running_loop().time())
    if await lock.mark_deleted(category_id, now, remaining):
        print(
            "\n[regular 모임 자동 종료 성공]"
            f"\nrecruit_id={recruit_id}"
            f"\ndiscord_deleted_at={now:%Y-%m-%d %H:%M:%S}"
        )
    else:
        still_regular = await call(repository.is_regular, recruit_id)
        reason = "regular가 아님(short로 변경됨)" if still_regular is False else "이미 기록되었거나 대상 아님"
        print(f"삭제 기록 0행, 기록하지 않음: recruit_id={recruit_id} ({reason})")


async def _check_meeting(guild, repository, category_id, meeting, now):
    recruit_id = meeting["recruit_id"]
    host_id = meeting.get("host_id")
    last_activity_at = meeting.get("last_activity_at")
    inactivity_warned_at = meeting.get("inactivity_warned_at")
    scheduled_delete_at = meeting.get("scheduled_delete_at")
    discord_deleted_at = meeting.get("discord_deleted_at")

    if discord_deleted_at is not None:
        return

    # The DB may still say "live" for a space Discord no longer has (deleted by
    # an earlier run whose DB write failed, or by an admin): record that fact.
    if await _space_gone(guild, _resource_ids(category_id, meeting), trust_cache=True):
        print(f"Discord 공간이 이미 없음, 삭제 완료로 기록: recruit_id={recruit_id}")
        await call(repository.mark_deleted, category_id, now)
        return

    if scheduled_delete_at is not None:
        print(
            f"[regular 모임] recruit_id={recruit_id} | "
            f"삭제예정={scheduled_delete_at:%Y-%m-%d %H:%M:%S}"
        )
        if now < scheduled_delete_at:
            return

        # Re-read the stored state: activity may have arrived while we awaited.
        fresh = await call(repository.get_regular_meeting, category_id)
        if (
            fresh is None
            or fresh.get("discord_deleted_at") is not None
            or fresh.get("scheduled_delete_at") is None
        ):
            return
        meeting = fresh
        last_activity_at = fresh.get("last_activity_at")
        inactivity_warned_at = fresh.get("inactivity_warned_at")

        # A message after the warning cancels deletion, even at the last check.
        if (
            inactivity_warned_at is not None
            and last_activity_at is not None
            and last_activity_at > inactivity_warned_at
        ):
            print(f"경고 이후 활동 발견: recruit_id={recruit_id}")
            await call(repository.cancel_schedule, category_id)
            print("→ 자동삭제 예약 취소")
            return

        resource_ids = _resource_ids(category_id, meeting)
        try:
            # The recruits row stays locked (FOR SHARE) until the whole Discord
            # deletion and its DB record are done: a regular->short change waits
            # for us, and one that committed first stops us right here.
            async with repository.regular_lock(recruit_id) as lock:
                # ONE time budget for everything after the lock is taken: channel
                # resolve/fetch, child + category deletes, the final API check of
                # all three resources and the DB record. On timeout the `async with`
                # rolls back and frees the row lock, nothing is recorded, and the
                # next cycle retries.
                await asyncio.wait_for(
                    _delete_under_lock(guild, repository, lock, recruit_id, category_id, resource_ids, now),
                    DISCORD_LOCK_HOLD_SECONDS,
                )
        except GuardRejected:
            print(f"regular 모임이 아니거나 이미 처리되어 삭제 중단: recruit_id={recruit_id}")
        except RegularLockUnavailable:
            print(f"recruits 행 잠금 대기 초과, 다음 주기에 재시도: recruit_id={recruit_id}")
        except asyncio.TimeoutError:
            print(
                f"Discord 삭제/확인이 {DISCORD_LOCK_HOLD_SECONDS}초 안에 끝나지 않아 중단, "
                f"락 해제 후 다음 주기에 재시도: recruit_id={recruit_id}"
            )
        return

    if last_activity_at is None:
        return

    inactive_duration = now - last_activity_at
    print(
        f"[regular 모임] recruit_id={recruit_id} | "
        f"비활성 기간={inactive_duration.days}일"
    )
    if inactive_duration < timedelta(days=INACTIVITY_DAYS):
        return
    if inactivity_warned_at is not None:
        return

    if host_id is None:
        # No HOST known (backend has not provided one yet): no DM, no countdown.
        print(f"HOST 정보 없음, 경고 건너뜀: recruit_id={recruit_id}")
        return

    try:
        host = await guild.fetch_member(host_id)
        scheduled_delete_at = now + timedelta(days=INACTIVITY_GRACE_DAYS)
        await host.send(
            "PlayMate 모임 활동 안내\n\n"
            f"모임(recruit_id={recruit_id})에서 최근 "
            f"{INACTIVITY_DAYS}일 동안 Discord 활동이 "
            "확인되지 않았습니다.\n\n"
            f"앞으로 {INACTIVITY_GRACE_DAYS}일 동안 활동이 없으면 "
            "모임이 자동 종료되고 Discord 공간이 삭제됩니다.\n\n"
            "모임 채널에서 다시 활동이 발생하면 자동 종료 예약은 "
            "취소됩니다."
        )
    except discord.NotFound:
        print(f"HOST를 찾을 수 없음: host_id={host_id}")
        return
    except discord.Forbidden:
        print(f"HOST에게 DM을 보낼 수 없음: recruit_id={recruit_id}")
        return
    except discord.HTTPException as error:
        print(f"DM 전송 실패: recruit_id={recruit_id} / {error}")
        return

    # Only store the warning if nothing changed since our snapshot (activity
    # during the DM await keeps winning).
    stored = await call(
        repository.record_warning,
        category_id, now, scheduled_delete_at, last_activity_at,
    )
    if stored:
        print(f"비활성 경고 DM 전송 완료: recruit_id={recruit_id}")
        print(f"자동 삭제 예정: {scheduled_delete_at:%Y-%m-%d %H:%M:%S}")
    else:
        print(f"경고 전송 중 상태 변경, 삭제 예약 저장 안 함: recruit_id={recruit_id}")


def create_lifecycle_task(
    client: discord.Client,
    repository: MeetingRepository,
):
    """Bind the periodic loop and readiness guard to their dependencies."""

    @tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
    async def lifecycle_task():
        # Exception boundary: a DB/Discord outage fails this cycle only; the
        # loop (and the Bot process) keep running and try again next interval.
        try:
            await check_meeting_lifecycle(client, repository)
        except Exception as error:
            print(f"[regular 모임 라이프사이클] 이번 검사 실패, 다음 주기에 재시도: {error!r}")

    @lifecycle_task.before_loop
    async def before_check_meeting_lifecycle():
        await client.wait_until_ready()

    return lifecycle_task
