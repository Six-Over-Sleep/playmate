"""regular 모임의 비활성 정책(30일 경고, 7일 유예, 자동 삭제)을 실행한다.

정책 요약:
    - 마지막 활동 후 30일이 지나면 HOST에게 DM으로 경고하고 7일 뒤 삭제를 예약한다.
    - 유예 중 활동이 생기면 예약이 취소된다 (메시지 핸들러가 DB에서 처리).
    - 유예가 끝나도 활동이 없으면 Discord 공간(카테고리/텍스트/음성)을 삭제한다.

상태 변경 원칙:
    - 모임 전체를 한 번에 덮어쓰는 저장은 쓰지 않는다. 경고 기록, 예약 취소, 삭제 기록처럼
      목적별 조건부 UPDATE만 사용하므로, Discord나 DB를 기다리는 동안 들어온 새 활동이
      오래된 값으로 덮어써지지 않는다.
    - discord_deleted_at은 Discord에서 세 리소스가 실제로 사라진 것을 확인한 뒤에만 기록한다.
      삭제가 실패하거나 결과가 불명확하면 아무것도 저장하지 않고, 다음 주기(또는 재시작 후)에
      DB 상태를 기준으로 다시 판단한다.
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
    """저장소에 있는 regular 모임을 모두 검사해 경고 또는 삭제를 진행한다.

    입력:
        client: 로그인된 Discord 클라이언트
        repository: 모임 상태 저장소 (PostgreSQL 또는 메모리)

    처리 순서:
        1. 대상 서버(guild)를 찾는다. 없으면 이번 검사는 건너뛴다.
        2. 저장소의 regular 모임 목록을 읽는다.
        3. 모임별로 카테고리 락을 잡고 `_check_meeting`을 실행한다.

    실패 처리:
        한 모임의 검사가 실패해도 로그만 남기고 다음 모임을 계속 검사한다.
        목록 조회 자체가 실패하면 예외가 호출자(`create_lifecycle_task`)로 올라간다.
    """
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
                print(
                    f"[regular 모임] 검사 실패 recruit_id={meeting.get('recruit_id')}: "
                    f"{error!r}"
                )


def _resource_ids(category_id: int, meeting: dict) -> list[int]:
    """모임이 관리하는 Discord 리소스 ID를 [카테고리, 텍스트, 음성] 순서로 돌려준다.

    텍스트/음성 ID가 없으면(NULL이거나 잘못된 값) 그 항목은 목록에서 빠진다.
    카테고리는 항상 첫 번째 원소이므로 `ids[1:]`이 하위 채널이다.
    """
    return [category_id] + [
        meeting[key] for key in ("text_channel_id", "voice_channel_id")
        if meeting.get(key) is not None
    ]


async def _space_gone(guild, resource_ids: list[int], trust_cache: bool = False) -> bool:
    """관리 대상 Discord 리소스가 모두 사라졌는지 Discord API로 확인한다.

    입력:
        resource_ids: 카테고리/텍스트/음성 ID 목록
        trust_cache: True이면 캐시에 있는 채널을 "아직 존재함"의 증거로 인정한다
            (매 주기 실행하는 가벼운 확인용). 삭제 기록 직전의 최종 확인은 항상 API만 쓴다.

    반환:
        모든 리소스에서 API가 NotFound를 돌려준 경우에만 True.

    업무 규칙:
        Discord는 카테고리를 지워도 하위 채널을 자동으로 지우지 않고, 캐시에 없다는 것이
        "없음"을 뜻하지도 않는다. 그래서 카테고리 하나만, 또는 캐시만 보고 삭제 완료로
        판단하지 않는다.

    실패 처리:
        Forbidden, HTTP 오류, 타임아웃 등 불명확한 응답은 "아직 있을 수 있음"(False)으로
        취급한다. 살아 있는 공간이 삭제 완료로 기록되는 것보다 한 번 더 확인하는 편이 안전하다.
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
    """row lock을 잡은 상태에서 Discord 공간을 삭제하고 삭제 완료를 기록한다.

    호출 조건:
        `repository.regular_lock(...)` 블록 안에서만 호출한다. 이 락 덕분에 삭제하는 동안
        Backend가 모임을 short로 바꾸는 UPDATE는 끝날 때까지 대기한다.

    처리 순서:
        1. 삭제 시점이 되었고 경고 이후 활동이 없는지 읽기 전용으로 마지막 확인 (아직 쓰기 없음)
        2. Discord 채널/카테고리 삭제
        3. 세 리소스가 모두 사라졌는지 API로 확인
        4. 같은 락의 트랜잭션 안에서 discord_deleted_at 기록 (블록이 정상 종료될 때 COMMIT)

    실패 처리:
        2~3에서 실패하거나 결과가 불명확하면 아무것도 기록하지 않고 돌아간다(다음 주기에 재시도).
        4의 UPDATE에는 남은 시간 예산만큼의 서버 statement_timeout이 걸리며, timeout이나
        취소가 나면 상위 `async with`가 트랜잭션 전체를 ROLLBACK한다.
        그래서 timeout된 작업의 기록이 나중에 뒤늦게 COMMIT되는 일이 없다.
    """
    deadline = asyncio.get_running_loop().time() + DISCORD_LOCK_HOLD_SECONDS
    # 삭제 직전 마지막 확인은 읽기 전용이다. 이 시점까지 DB에는 아무것도 쓰지 않는다.
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
    # 삭제 기록은 락을 잡고 있는 같은 DB 연결/트랜잭션에서만 쓴다.
    # 별도 연결에서 쓰면 timeout 이후에 뒤늦게 COMMIT될 수 있기 때문이다.
    remaining = max(1.0, deadline - asyncio.get_running_loop().time())
    if await lock.mark_deleted(category_id, now, remaining):
        print(
            "\n[regular 모임 자동 종료 성공]"
            f"\nrecruit_id={recruit_id}"
            f"\ndiscord_deleted_at={now:%Y-%m-%d %H:%M:%S}"
        )
    else:
        still_regular = await call(repository.is_regular, recruit_id)
        reason = (
            "regular가 아님(short로 변경됨)"
            if still_regular is False
            else "이미 기록되었거나 대상 아님"
        )
        print(f"삭제 기록 0행, 기록하지 않음: recruit_id={recruit_id} ({reason})")


async def _check_meeting(guild, repository, category_id, meeting, now):
    """모임 하나에 대해 필요한 lifecycle 단계를 한 가지만 실행한다.

    입력:
        meeting: 저장소가 돌려준 상태 (last_activity_at, inactivity_warned_at,
            scheduled_delete_at, discord_deleted_at, host_id 등)
        now: 이번 검사의 기준 시각 (KST)

    처리 순서 (위에서부터 해당하는 첫 번째 단계만 실행하고 끝낸다):
        1. 이미 삭제 완료로 기록된 모임이면 건너뛴다.
        2. DB는 살아 있다고 하지만 Discord 공간이 이미 없으면 삭제 완료로 기록한다.
           (이전 실행에서 삭제 후 기록만 실패했거나, 관리자가 직접 지운 경우)
        3. 삭제가 예약되어 있으면: 예약 시각 전이면 대기, 경고 이후 활동이 있으면 예약 취소,
           아니면 row lock을 잡고 삭제 (`_delete_under_lock`)
        4. 예약이 없으면: 마지막 활동 후 INACTIVITY_DAYS가 지났을 때 HOST에게 DM을 보내고
           INACTIVITY_GRACE_DAYS 뒤 삭제를 예약

    업무 규칙:
        - recruits.state(모집 상태)와 meeting_end는 어떤 단계에서도 사용하지 않는다.
        - HOST를 알 수 없으면(Backend가 아직 HOST를 저장하지 않음) 경고와 예약을 하지 않는다.
        - 경고는 DM이 실제로 전송된 뒤에만, 그리고 그 사이 새 활동이 없었을 때만 저장한다.

    실패 처리:
        DM 실패(NotFound/Forbidden/HTTP)는 경고를 저장하지 않고 다음 주기에 다시 시도한다.
        삭제 단계의 락 대기 초과, short 전환, 전체 timeout도 기록 없이 다음 주기로 넘긴다.
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
        print(
            f"[regular 모임] recruit_id={recruit_id} | "
            f"삭제예정={scheduled_delete_at:%Y-%m-%d %H:%M:%S}"
        )
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
        # HOST를 알 수 없으면(Backend가 아직 저장하지 않음) DM도, 삭제 예약도 하지 않는다.
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
    """주기적으로 lifecycle 검사를 실행하는 discord.ext.tasks 루프를 만든다.

    주기는 config의 CHECK_INTERVAL_SECONDS(운영 하루 1회, 테스트 모드 1분)를 따른다.
    루프는 Bot이 Discord에 완전히 연결된 뒤(`wait_until_ready`)에 시작한다.
    """

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
