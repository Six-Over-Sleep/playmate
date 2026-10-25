"""모임 채널 비활성 정책: 7일 무활동이면 채널에 Bot 경고, 24시간 안에 활동이 없으면 채널 삭제.

경고는 DM이 아니라 해당 모임 채널에 Bot 메시지로 남긴다. 유예 중 메시지가 생기면 삭제 예약이 취소된다
(취소 처리는 message_handler). 프로젝트/스터디 등 모임 방식과 상관없이 같은 정책이다.
상시 오픈채팅 채널은 DB 모임 행이 없어 대상이 아니다 (삭제 함수도 보호 목록 채널을 거부한다).

목적별 조건부 UPDATE만 쓰므로 기다리는 동안 들어온 새 활동이 오래된 값으로 덮어써지지 않는다.
discord_deleted_at은 채널이 실제로 사라진 것을 API로 확인한 뒤에만 기록한다.
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
    INACTIVITY_GRACE_HOURS,
    KST,
)
from repositories.meeting_repository import (
    GuardRejected,
    MeetingLockUnavailable,
    MeetingRepository,
    call,
)
from services.meeting_space import delete_meeting_channel, resolve_channel
from services.official_channels import PROTECTED_CHANNEL_IDS

# 모임 채널에 남기는 Bot 메시지. 취소 안내는 message_handler가 활동이 다시 생겼을 때 쓴다.
INACTIVITY_WARNING_TEXT = (
    f"최근 {INACTIVITY_DAYS}일 동안 대화가 없어 이 채널은 삭제 예정입니다.\n"
    f"{INACTIVITY_GRACE_HOURS}시간 이내에 대화가 발생하면 삭제가 자동으로 취소됩니다."
)
DELETE_CANCELLED_TEXT = "대화가 다시 시작되어 채널 삭제 예약이 취소되었습니다."

# 삭제 직전에 Discord 채널의 최근 메시지를 확인할 때 훑어볼 최대 개수 (최신순).
HISTORY_CHECK_LIMIT = 50

# 같은 모임 채널에 대한 lifecycle 작업과 활동 처리(message_handler)가 동시에 실행되지 않도록 채널별로 직렬화한다.
# 활동이 먼저 처리되면 삭제는 그 결과(예약 취소)를 보고 중단하고, 삭제가 먼저 진행 중이면 활동 처리는
# 삭제가 끝난 뒤에 실행되어 이미 삭제된 모임에는 취소 안내를 보내지 않는다.
_channel_locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
# 삭제를 시도하는 채널만 들어 있다: 채널 ID -> 시도 중에 사용자 메시지 이벤트가 도착했는지.
_delete_in_flight: dict[int, bool] = {}


def channel_lock(channel_id: int) -> asyncio.Lock:
    """모임 채널 하나의 활동 처리 / lifecycle 작업을 직렬화하는 락."""
    return _channel_locks[channel_id]


def note_activity(channel_id: int) -> None:
    """사용자 메시지 이벤트를 받자마자(await 이전에) 호출한다.

    그 채널을 삭제하려는 중이면 표시만 해 두고, 삭제는 `channel.delete()` 직전에 이 표시를 보고 중단한다.
    실제 DB 기록과 예약 취소는 message_handler가 채널 락을 얻은 뒤에 한다.
    """
    if channel_id in _delete_in_flight:
        _delete_in_flight[channel_id] = True


async def check_meeting_lifecycle(
    client: discord.Client, repository: MeetingRepository
):
    """관리 중인 모든 모임 채널을 채널 락 아래에서 검사한다. 한 모임의 실패는 다음 모임을 막지 않는다."""
    now = datetime.now(KST)
    print(f"\n[모임 채널 라이프사이클 검사] {now:%Y-%m-%d %H:%M:%S}")
    guild = client.get_guild(GUILD_ID)
    if guild is None:
        print("Discord 서버를 찾을 수 없습니다.")
        return

    for channel_id, meeting in await call(repository.list_managed_meetings):
        async with channel_lock(channel_id):
            try:
                await _check_meeting(guild, repository, channel_id, meeting, now)
            except Exception as error:
                # 모임 하나의 오류가 다른 모임의 검사를 막지 않도록 한다.
                print(f"[모임 채널] 검사 실패 recruit_id={meeting.get('recruit_id')}: {error!r}")


async def _channel_gone(guild, channel_id: int, trust_cache: bool = False) -> bool:
    """API가 NotFound를 돌려줄 때만 True (캐시 미스나 불명확한 응답으로는 "삭제됨"이라고 하지 않는다).

    trust_cache=True면 캐시에 있는 채널을 "존재함" 증거로 쓴다 (매 주기 가벼운 확인용).
    불명확한 응답(Forbidden/HTTP/timeout)은 "아직 있을 수 있음"(False)이다.
    """
    try:
        if trust_cache and guild.get_channel(channel_id) is not None:
            return False
        try:
            await guild.fetch_channel(channel_id)
            return False
        except discord.NotFound:
            return True
    except Exception:
        return False


async def _latest_user_message_at(channel, since: datetime) -> datetime | None:
    """채널의 최근 메시지(최신순) 중 `since` 이후의 사용자 메시지 시각(KST). 없으면 None.

    Bot(및 다른 Bot) 메시지는 사용자 활동이 아니므로 건너뛴다. 조회 실패는 예외로 알린다.
    """
    async for message in channel.history(limit=HISTORY_CHECK_LIMIT):
        if message.created_at <= since:
            return None
        if not message.author.bot:
            return message.created_at.astimezone(KST)
    return None


async def _resume_from_history(channel, repository, recruit_id, channel_id, active_at) -> None:
    """gateway 이벤트보다 먼저 Discord 기록에서 활동을 발견한 경우: 활동을 기록해 삭제 예약을 취소한다."""
    print(f"삭제 직전 Discord 기록에서 사용자 메시지 발견, 삭제 취소: recruit_id={recruit_id}")
    if await call(repository.record_activity, channel_id, active_at):
        try:
            await channel.send(DELETE_CANCELLED_TEXT)
        except Exception as error:
            print(f"삭제 예약 취소 안내 전송 실패: recruit_id={recruit_id} / {error!r}")


async def _delete_under_lock(guild, repository, lock, recruit_id, channel_id, now):
    """`meeting_lock`과 채널 락 안에서만 호출: 최종 확인 -> 채널 하나 삭제 -> API로 확인 -> 기록.

    최종 확인은 세 겹이다. ① Discord 채널의 최근 사용자 메시지 ② DB의 삭제 예약 상태(`is_delete_due`)
    ③ 이 사이에 도착한 메시지 이벤트(`note_activity`)를 `channel.delete()` 직전에 마지막으로 확인.
    활동 처리는 같은 채널 락을 쓰므로, 예약이 취소된 뒤에는 이 삭제가 채널을 지우지 못한다.
    삭제가 실패하거나 불명확하면 아무것도 기록하지 않는다 (다음 주기 재시도).
    기록은 락과 같은 연결/트랜잭션에서 남은 시간 예산만큼의 statement_timeout으로 실행된다.
    별도 연결에서 쓰면 timeout 뒤에 뒤늦게 COMMIT될 수 있기 때문이다.
    """
    deadline = asyncio.get_running_loop().time() + DISCORD_LOCK_HOLD_SECONDS
    _delete_in_flight[channel_id] = False
    try:
        await _delete_checked(guild, repository, lock, recruit_id, channel_id, now, deadline)
    finally:
        _delete_in_flight.pop(channel_id, None)


async def _delete_checked(guild, repository, lock, recruit_id, channel_id, now, deadline):
    # ① gateway 이벤트가 아직 도착하지 않았거나 놓쳤을 수 있으므로 Discord 기록의 사용자 메시지를 확인한다.
    # 확인할 수 없으면(권한/HTTP 오류) 지우지 않고 다음 주기에 다시 시도한다.
    state, channel = await resolve_channel(guild, channel_id)
    if state == "unknown":
        print(f"채널 조회가 불명확해 삭제 보류, 다음 주기에 재시도: recruit_id={recruit_id}")
        return
    if state == "present":
        fresh = await call(repository.get_managed_meeting, channel_id)
        warned_at = None if fresh is None else fresh.get("inactivity_warned_at")
        if warned_at is None:
            print(f"경고/예약 상태가 사라져 삭제 취소: recruit_id={recruit_id}")
            return
        try:
            active_at = await _latest_user_message_at(channel, warned_at)
        except Exception as error:
            print(f"채널 최근 메시지를 확인하지 못해 삭제 보류: recruit_id={recruit_id} / {error!r}")
            return
        if active_at is not None:
            await _resume_from_history(channel, repository, recruit_id, channel_id, active_at)
            return

    # ② 삭제 직전 마지막 DB 확인 (읽기 전용). 경고 이후 활동이 있으면 여기서 멈춘다.
    if not await call(repository.is_delete_due, channel_id, now):
        print(f"삭제 직전 상태 변경, 삭제 취소: recruit_id={recruit_id}")
        return
    # ③ 위 확인들을 기다리는 동안 메시지 이벤트가 도착했다면 활동 처리가 예약을 취소할 것이다.
    if _delete_in_flight.get(channel_id):
        print(f"삭제 직전 사용자 활동 감지, 삭제 취소: recruit_id={recruit_id}")
        return

    print(f"\n[모임 채널 자동 삭제 대상]\nrecruit_id={recruit_id} channel_id={channel_id}")
    await delete_meeting_channel(
        guild, channel_id, recruit_id, PROTECTED_CHANNEL_IDS,
        should_abort=lambda: _delete_in_flight.get(channel_id, False),
    )
    # 삭제 호출의 반환값이나 캐시를 믿지 않고 API로 다시 확인한다.
    if not await _channel_gone(guild, channel_id):
        if _delete_in_flight.get(channel_id):
            print(f"삭제 직전 사용자 활동 감지, 삭제하지 않음: recruit_id={recruit_id}")
        else:
            print(f"Discord 삭제 실패/불명, 다음 주기에 재시도: recruit_id={recruit_id}")
        return
    remaining = max(1.0, deadline - asyncio.get_running_loop().time())
    if await lock.mark_deleted(channel_id, now, remaining):
        print(
            "\n[모임 채널 자동 삭제 성공]"
            f"\nrecruit_id={recruit_id}"
            f"\ndiscord_deleted_at={now:%Y-%m-%d %H:%M:%S}"
        )
    else:
        still_managed = await call(repository.is_managed, recruit_id)
        reason = "채널 대상 모임이 아님" if still_managed is False else "이미 기록되었거나 대상 아님"
        print(f"삭제 기록 0행, 기록하지 않음: recruit_id={recruit_id} ({reason})")


async def _check_meeting(guild, repository, channel_id, meeting, now):
    """모임 채널 하나에 해당하는 첫 번째 단계만 실행한다.

    1. 이미 삭제 기록됨 -> 건너뜀  2. Discord 채널이 이미 없음 -> 삭제 기록
    3. 삭제 예약 있음 -> 대기 / 경고 후 활동 있으면 취소 / 아니면 락 아래에서 채널 삭제
    4. INACTIVITY_DAYS 무활동 -> 채널에 경고 메시지 후 INACTIVITY_GRACE_HOURS 뒤 삭제 예약
    recruits.state와 meeting_end는 쓰지 않는다. 경고는 메시지 전송 후, 그 사이 새 활동이 없을 때만 저장한다.
    """
    recruit_id = meeting["recruit_id"]
    last_activity_at = meeting.get("last_activity_at")
    inactivity_warned_at = meeting.get("inactivity_warned_at")
    scheduled_delete_at = meeting.get("scheduled_delete_at")
    discord_deleted_at = meeting.get("discord_deleted_at")

    if discord_deleted_at is not None:
        return

    # DB는 살아 있다고 하는데 Discord 채널이 이미 없는 경우: 사실대로 기록하고 끝낸다.
    if await _channel_gone(guild, channel_id, trust_cache=True):
        print(f"Discord 채널이 이미 없음, 삭제 완료로 기록: recruit_id={recruit_id}")
        await call(repository.mark_deleted, channel_id, now)
        return

    if scheduled_delete_at is not None:
        print(f"[모임 채널] recruit_id={recruit_id} | 삭제예정={scheduled_delete_at:%Y-%m-%d %H:%M:%S}")
        if now < scheduled_delete_at:
            return

        # 목록을 읽은 뒤 await 동안 새 활동이 있었을 수 있으므로 저장된 최신 상태를 다시 읽는다.
        fresh = await call(repository.get_managed_meeting, channel_id)
        if (
            fresh is None
            or fresh.get("discord_deleted_at") is not None
            or fresh.get("scheduled_delete_at") is None
        ):
            return
        last_activity_at = fresh.get("last_activity_at")
        inactivity_warned_at = fresh.get("inactivity_warned_at")

        # 경고 이후 메시지가 하나라도 있으면 마지막 확인 단계에서도 삭제를 취소한다.
        if (
            inactivity_warned_at is not None
            and last_activity_at is not None
            and last_activity_at > inactivity_warned_at
        ):
            print(f"경고 이후 활동 발견: recruit_id={recruit_id}")
            await call(repository.cancel_schedule, channel_id)
            print("→ 자동삭제 예약 취소")
            return

        try:
            # recruits 행에 FOR SHARE 락을 잡고 삭제와 기록이 끝날 때까지 유지한다.
            # Backend의 모임 방식 변경은 그동안 대기하고, 이미 대상이 아니게 commit되었다면
            # 락을 얻는 순간 GuardRejected로 이 블록에 들어오지 못한다.
            async with repository.meeting_lock(recruit_id) as lock:
                # 락을 얻은 뒤의 모든 작업(채널 삭제, 최종 확인, DB 기록)에 시간 예산을 하나만 둔다.
                # Discord API가 멈춰도 락과 Backend 대기가 무기한 이어지지 않게 하기 위해서다.
                # timeout이 나면 async with가 ROLLBACK하고 락을 풀며, 아무것도 기록되지 않아
                # 다음 주기에 다시 시도한다.
                await asyncio.wait_for(
                    _delete_under_lock(guild, repository, lock, recruit_id, channel_id, now),
                    DISCORD_LOCK_HOLD_SECONDS,
                )
        except GuardRejected:
            print(f"채널 대상 모임이 아니거나 이미 처리되어 삭제 중단: recruit_id={recruit_id}")
        except MeetingLockUnavailable:
            print(f"recruits 행 잠금 대기 초과, 다음 주기에 재시도: recruit_id={recruit_id}")
        except asyncio.TimeoutError:
            print(f"Discord 삭제/확인이 {DISCORD_LOCK_HOLD_SECONDS}초 안에 끝나지 않아 중단, "
                  f"락 해제 후 다음 주기에 재시도: recruit_id={recruit_id}")
        return

    if last_activity_at is None:
        return

    inactive_duration = now - last_activity_at
    print(f"[모임 채널] recruit_id={recruit_id} | 비활성 기간={inactive_duration.days}일")
    if inactive_duration < timedelta(days=INACTIVITY_DAYS):
        return
    if inactivity_warned_at is not None:
        return

    # 경고는 DM이 아니라 해당 모임 채널에 남긴다.
    channel_state, channel = await resolve_channel(guild, channel_id)
    if channel_state != "present":
        print(f"경고할 채널을 찾지 못함, 다음 주기에 재시도: recruit_id={recruit_id}")
        return
    scheduled_delete_at = now + timedelta(hours=INACTIVITY_GRACE_HOURS)
    try:
        await channel.send(INACTIVITY_WARNING_TEXT)
    except discord.NotFound:
        print(f"경고 전송 중 채널이 사라짐: recruit_id={recruit_id}")
        return
    except discord.Forbidden:
        print(f"채널에 경고를 보낼 권한이 없음: recruit_id={recruit_id}")
        return
    except discord.HTTPException as error:
        print(f"경고 메시지 전송 실패: recruit_id={recruit_id} / {error}")
        return

    # 처음 읽은 상태와 같을 때만 경고/예약을 저장한다. 메시지를 보내는 동안 새 활동이 있었다면
    # 저장하지 않으며, 그 활동이 우선한다.
    stored = await call(
        repository.record_warning,
        channel_id, now, scheduled_delete_at, last_activity_at,
    )
    if stored:
        print(f"비활성 경고 메시지 전송 완료: recruit_id={recruit_id}")
        print(f"자동 삭제 예정: {scheduled_delete_at:%Y-%m-%d %H:%M:%S}")
    else:
        print(f"경고 전송 중 상태 변경, 삭제 예약 저장 안 함: recruit_id={recruit_id}")


def create_lifecycle_task(
    client: discord.Client,
    repository: MeetingRepository,
):
    """CHECK_INTERVAL_SECONDS(운영 1시간, 테스트 모드 1분)마다 lifecycle 검사를 실행하는 루프."""

    @tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
    async def lifecycle_task():
        # 예외 경계: DB나 Discord 장애는 이번 검사만 실패시킨다. 루프와 Bot 프로세스는
        # 죽지 않고 다음 주기에 다시 시도한다. (tasks.loop는 처리되지 않은 예외로 멈추기 때문)
        try:
            await check_meeting_lifecycle(client, repository)
        except Exception as error:
            print(f"[모임 채널 라이프사이클] 이번 검사 실패, 다음 주기에 재시도: {error!r}")

    @lifecycle_task.before_loop
    async def before_check_meeting_lifecycle():
        await client.wait_until_ready()

    return lifecycle_task
