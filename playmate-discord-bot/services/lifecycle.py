"""regular 모임 비활성 정책: 30일 무활동이면 HOST에게 DM 경고 + 7일 뒤 삭제 예약, 유예 중 활동하면 취소.

목적별 조건부 UPDATE만 쓰므로 기다리는 동안 들어온 새 활동이 오래된 값으로 덮어써지지 않는다.
discord_deleted_at은 세 리소스가 실제로 사라진 것을 API로 확인한 뒤에만 기록한다.
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

# 같은 모임에 대한 lifecycle 작업이 동시에 두 번 실행되지 않도록 카테고리별로 직렬화한다.
_category_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


async def check_meeting_lifecycle(
    client: discord.Client, repository: MeetingRepository
):
    """모든 regular 모임을 카테고리 락 아래에서 검사한다. 한 모임의 실패는 다음 모임을 막지 않는다."""
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
                # 모임 하나의 오류가 다른 모임의 검사를 막지 않도록 한다.
                print(f"[regular 모임] 검사 실패 recruit_id={meeting.get('recruit_id')}: {error!r}")


def _resource_ids(category_id: int, meeting: dict) -> list[int]:
    """[카테고리, 텍스트, 음성] ID (없는 채널은 빠짐). `ids[1:]`이 하위 채널이다."""
    return [category_id] + [
        meeting[key] for key in ("text_channel_id", "voice_channel_id")
        if meeting.get(key) is not None
    ]


async def _space_gone(guild, resource_ids: list[int], trust_cache: bool = False) -> bool:
    """모든 리소스에서 API가 NotFound를 돌려줄 때만 True (카테고리 하나나 캐시만 보고 판단하지 않는다).

    trust_cache=True면 캐시에 있는 채널을 "존재함" 증거로 쓴다 (매 주기 가벼운 확인용).
    불명확한 응답(Forbidden/HTTP/timeout)은 "아직 있을 수 있음"(False)이다.
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
    """`regular_lock` 블록 안에서만 호출: 읽기 전용 최종 확인 -> 삭제 -> API로 확인 -> 기록.

    삭제가 실패하거나 불명확하면 아무것도 기록하지 않는다 (다음 주기 재시도).
    기록은 락과 같은 연결/트랜잭션에서 남은 시간 예산만큼의 statement_timeout으로 실행된다.
    별도 연결에서 쓰면 timeout 뒤에 뒤늦게 COMMIT될 수 있기 때문이다.
    """
    deadline = asyncio.get_running_loop().time() + DISCORD_LOCK_HOLD_SECONDS
    if not await call(repository.is_delete_due, category_id, now):
        print(f"삭제 직전 상태 변경, 삭제 취소: recruit_id={recruit_id}")
        return

    print(f"\n[regular 모임 자동 종료 대상]\nrecruit_id={recruit_id}")
    await delete_meeting_space(
        guild=guild, category_id=category_id, extra_channel_ids=resource_ids[1:],
    )
    # 삭제 호출의 반환값이나 캐시를 믿지 않고 세 리소스를 API로 다시 확인한다.
    if not await _space_gone(guild, resource_ids):
        print(f"Discord 삭제 실패/불명, 다음 주기에 재시도: recruit_id={recruit_id}")
        return
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
    """모임 하나에 해당하는 첫 번째 단계만 실행한다.

    1. 이미 삭제 기록됨 -> 건너뜀  2. Discord 공간이 이미 없음 -> 삭제 기록
    3. 삭제 예약 있음 -> 대기 / 경고 후 활동 있으면 취소 / 아니면 락 아래에서 삭제
    4. INACTIVITY_DAYS 무활동 -> HOST DM 후 예약 (HOST를 모르면 하지 않음)
    recruits.state와 meeting_end는 쓰지 않는다. 경고는 DM 전송 후, 그 사이 새 활동이 없을 때만 저장한다.
    """
    recruit_id = meeting["recruit_id"]
    host_id = meeting.get("host_id")
    last_activity_at = meeting.get("last_activity_at")
    inactivity_warned_at = meeting.get("inactivity_warned_at")
    scheduled_delete_at = meeting.get("scheduled_delete_at")
    discord_deleted_at = meeting.get("discord_deleted_at")

    if discord_deleted_at is not None:
        return

    # DB는 살아 있다고 하는데 Discord 공간이 이미 없는 경우: 사실대로 기록하고 끝낸다.
    if await _space_gone(guild, _resource_ids(category_id, meeting), trust_cache=True):
        print(f"Discord 공간이 이미 없음, 삭제 완료로 기록: recruit_id={recruit_id}")
        await call(repository.mark_deleted, category_id, now)
        return

    if scheduled_delete_at is not None:
        print(f"[regular 모임] recruit_id={recruit_id} | 삭제예정={scheduled_delete_at:%Y-%m-%d %H:%M:%S}")
        if now < scheduled_delete_at:
            return

        # 목록을 읽은 뒤 await 동안 새 활동이 있었을 수 있으므로 저장된 최신 상태를 다시 읽는다.
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

        # 경고 이후 메시지가 하나라도 있으면 마지막 확인 단계에서도 삭제를 취소한다.
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
            # recruits 행에 FOR SHARE 락을 잡고 삭제와 기록이 끝날 때까지 유지한다.
            # Backend의 regular→short 변경은 그동안 대기하고, 이미 short로 commit되었다면
            # 락을 얻는 순간 GuardRejected로 이 블록에 들어오지 못한다.
            async with repository.regular_lock(recruit_id) as lock:
                # 락을 얻은 뒤의 모든 작업(채널 조회, 삭제, 최종 확인, DB 기록)에 시간 예산을
                # 하나만 둔다. Discord API가 멈춰도 락과 Backend 대기가 무기한 이어지지 않게
                # 하기 위해서다. timeout이 나면 async with가 ROLLBACK하고 락을 풀며,
                # 아무것도 기록되지 않아 다음 주기에 다시 시도한다.
                await asyncio.wait_for(
                    _delete_under_lock(
                        guild, repository, lock, recruit_id, category_id, resource_ids, now
                    ),
                    DISCORD_LOCK_HOLD_SECONDS,
                )
        except GuardRejected:
            print(f"regular 모임이 아니거나 이미 처리되어 삭제 중단: recruit_id={recruit_id}")
        except RegularLockUnavailable:
            print(f"recruits 행 잠금 대기 초과, 다음 주기에 재시도: recruit_id={recruit_id}")
        except asyncio.TimeoutError:
            print(f"Discord 삭제/확인이 {DISCORD_LOCK_HOLD_SECONDS}초 안에 끝나지 않아 중단, "
                  f"락 해제 후 다음 주기에 재시도: recruit_id={recruit_id}")
        return

    if last_activity_at is None:
        return

    inactive_duration = now - last_activity_at
    print(f"[regular 모임] recruit_id={recruit_id} | 비활성 기간={inactive_duration.days}일")
    if inactive_duration < timedelta(days=INACTIVITY_DAYS):
        return
    if inactivity_warned_at is not None:
        return

    if host_id is None:
        # HOST를 알 수 없으면(HOST 행이나 discord_id 없음) DM도, 삭제 예약도 하지 않는다.
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

    # 처음 읽은 상태와 같을 때만 경고/예약을 저장한다. DM을 보내는 동안 새 활동이 있었다면
    # 저장하지 않으며, 그 활동이 우선한다.
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
    """CHECK_INTERVAL_SECONDS(운영 하루 1회, 테스트 모드 1분)마다 lifecycle 검사를 실행하는 루프."""

    @tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
    async def lifecycle_task():
        # 예외 경계: DB나 Discord 장애는 이번 검사만 실패시킨다. 루프와 Bot 프로세스는
        # 죽지 않고 다음 주기에 다시 시도한다. (tasks.loop는 처리되지 않은 예외로 멈추기 때문)
        try:
            await check_meeting_lifecycle(client, repository)
        except Exception as error:
            print(f"[regular 모임 라이프사이클] 이번 검사 실패, 다음 주기에 재시도: {error!r}")

    @lifecycle_task.before_loop
    async def before_check_meeting_lifecycle():
        await client.wait_until_ready()

    return lifecycle_task
