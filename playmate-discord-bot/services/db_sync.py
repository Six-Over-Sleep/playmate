"""공용 DB를 주기적으로 읽어 Discord에 반영한다 (DB polling).

1. 생성: 모집 마감(deadline_at)이 지난 모임에 Discord 채널 하나를 만들고, 그 시점의 최종 참여자에게
   권한을 준 뒤 채널 ID를 저장한다. 마감 전에는 만들지 않는다. 모임 방식(regular/short)과 무관하다.
2. 참여자: JOINED에게 권한을 주고 CANCELED의 권한을 회수한다 (HOST도 일반 참여자).

마감을 놓친 모임(Bot 재시작/장애)은 같은 조회가 "마감이 지났고 채널 행이 없는 모임"을 매번 다시
찾으므로 따로 복구 작업 없이 만들어진다 (기간 제한 없음). 오래된 데이터가 한꺼번에 채널이 되지 않도록
한 번의 poll에서 config.CHANNEL_PROVISION_BATCH_LIMIT개까지만 만든다.

생성 실패 분류 (sync_error):
    - 생성 실패                           -> FAILED (자동 재시도)
    - 마감 기준을 알 수 없음              -> 'MANUAL:' (채널을 만들지 않음, 자동 재시도 안 함)
    - 생성 중 모임 방식이 대상이 아니게 됨  -> 'ABORTED:' (자동 재시도 안 함)
    - 생성 중 마감 연장 / 글 삭제          -> 'RECHECK:' (채널 정리 후 조건이 다시 맞으면 자동 재시도)
    - 저장 결과 불명 / ID 불일치           -> 'MANUAL:' (채널 유지, 자동 삭제/재생성 안 함)
    - 저장이 확실히 실패                  -> 채널 삭제 후 FAILED

공개 범위는 임시로 DEFAULT_VISIBILITY(PUBLIC)를 쓴다.
"""
import asyncio
from datetime import datetime, timedelta

import discord
from discord.ext import tasks

from config import (
    CHANNEL_PROVISION_BATCH_LIMIT,
    DEFAULT_VISIBILITY,
    DISCORD_LOCK_HOLD_SECONDS,
    GUILD_ID,
    KST,
    SYNC_INTERVAL_SECONDS,
)
from repositories.meeting_repository import (
    GuardRejected,
    MeetingLockUnavailable,
    ProvisioningRejected,
    ProvisioningUnconfirmed,
    call,
    kst_naive_now,
)
from services.meeting_space import (
    PARTICIPANT_PERMISSIONS,
    create_meeting_channel,
    delete_meeting_channel,
    resolve_channel,
)
from services.official_channels import PROTECTED_CHANNEL_IDS
from services.permissions import (
    grant_participant_permissions,
    remove_participant_permissions,
)

CHANNEL_NAME_LIMIT = 100  # Discord 채널 이름 최대 길이
MISSING_MEMBER_BACKOFF = timedelta(minutes=5)  # 서버에 없는 참여자를 다시 조회하기까지의 대기


def _is_member_target(target) -> bool:
    """overwrite 대상이 역할이 아니라 개별 사용자인지."""
    if isinstance(target, discord.Role):
        return False
    if isinstance(target, discord.Object):
        return target.type is not discord.Role
    return True


def _member_overwrite(location, discord_id: int):
    """채널에서 특정 사용자의 개인 overwrite. 없으면 None."""
    for target, overwrite in location.overwrites.items():
        if _is_member_target(target) and target.id == discord_id:
            return overwrite
    return None


def _member_has_access(location, discord_id: int) -> bool:
    """사용자가 이 채널에서 send_messages overwrite를 가졌는지."""
    overwrite = _member_overwrite(location, discord_id)
    return overwrite is not None and overwrite.send_messages is True


# 참여자 권한 이름 (meeting_space.PARTICIPANT_PERMISSIONS와 같은 세트).
_PARTICIPANT_FLAGS = tuple(PARTICIPANT_PERMISSIONS)


def _joined_ok(location, discord_id: int) -> bool:
    """JOINED 목표 상태: 참여자 권한이 모두 명시적으로 허용됨."""
    overwrite = _member_overwrite(location, discord_id)
    return overwrite is not None and all(
        getattr(overwrite, flag) is True for flag in _PARTICIPANT_FLAGS
    )


def _revoked_ok(location, discord_id: int, visibility: str) -> bool:
    """CANCELED 목표 상태: 쓰기 권한 없음.

    PUBLIC은 보기/읽기를 막아 두면 안 되고, PRIVATE은 보기/읽기도 남으면 안 된다.
    개인 overwrite가 없으면 @everyone 정책을 따르므로 회수된 것으로 본다.
    """
    overwrite = _member_overwrite(location, discord_id)
    if overwrite is None:
        return True
    if overwrite.send_messages is True:
        return False
    if visibility.upper() == "PRIVATE":
        return overwrite.view_channel is not True and overwrite.read_message_history is not True
    return overwrite.view_channel is not False and overwrite.read_message_history is not False


class DbSync:
    """공용 DB와 Discord를 맞춘다 (`run_once` 한 번 = 동기화 한 번). PostgresMeetingRepository가 필요하다."""

    def __init__(self, client: discord.Client, repository, visibility: str = DEFAULT_VISIBILITY):
        self.client = client
        self.repository = repository
        self.visibility = visibility  # TODO: Backend가 모임별 값을 저장하면 그 값으로 교체
        self._skip_until: dict[tuple[int, int], datetime] = {}

    # -- 1. 모집 마감된 모임 -> Discord 채널 -------------------------------
    async def provision_meetings(self, guild: discord.Guild) -> None:
        """마감이 지난 모임마다 선점 -> 채널 생성 -> 대상 재확인 -> ID 저장(SUCCESS) 순서로 처리한다.

        마감 시각은 deadline_at이고, 없는 예전 데이터만 시작일 당일 00:00이다. 기준이 전혀 없으면
        채널을 만들지 않고 'MANUAL:' 실패 행을 남긴다 (임의로 지금 만들지 않는다).
        실패는 모임별로 기록하고 다음 모임으로 넘어간다 (분류는 모듈 docstring 참고).
        추적되지 않는 채널이 남거나 중복 생성되지 않는 것이 목적이다.
        """
        repo = self.repository
        stale = await call(repo.fail_stale_pending)
        if stale:
            print(f"[Discord 동기화] 중단된 PENDING {stale}건을 FAILED(MANUAL)로 표시")
        unschedulable = await call(repo.record_unschedulable_recruits)
        if unschedulable:
            print(f"[Discord 동기화] 마감 기준이 없어 채널을 만들지 않음 recruit_id={unschedulable}")

        now = kst_naive_now()
        batch = await call(repo.list_provisionable_recruits, now, CHANNEL_PROVISION_BATCH_LIMIT)
        if len(batch) >= CHANNEL_PROVISION_BATCH_LIMIT:
            print(f"[Discord 동기화] 한 번에 {CHANNEL_PROVISION_BATCH_LIMIT}개까지만 생성, 남은 모임은 다음 poll에서 처리")
        for recruit in batch:
            recruit_id = recruit["recruit_id"]
            if not await call(repo.claim_provisioning, recruit_id, now):
                continue  # 마감이 미뤄졌거나 삭제됨, 또는 다른 worker/이전 주기가 이미 처리 중

            name = (recruit.get("title") or "").strip() or f"모임-{recruit_id}"
            name = name[:CHANNEL_NAME_LIMIT]
            try:
                participant_ids = await call(repo.list_joined_discord_ids, recruit_id)
                channel = await create_meeting_channel(
                    guild, name, recruit_id, participant_ids, self.visibility,
                )
            except Exception as error:
                # 채널 하나를 만드는 호출이라 정리할 부분 생성물이 없다. 일시 오류이므로 자동 재시도한다.
                print(f"[Discord 동기화] 생성 실패 recruit_id={recruit_id}: {error!r}")
                await self._record_failure(recruit_id, f"CREATE {type(error).__name__}: {error}")
                continue

            try:
                # SUCCESS로 확정하는 SQL이 같은 트랜잭션에서 모임 상태를 다시 확인한다 (대상 방식, 글 미삭제, 마감 경과).
                await call(repo.complete_provisioning, recruit_id, channel.id, datetime.now(KST))
            except ProvisioningRejected as rejected:
                # 채널을 만드는 동안 모임이 바뀌었다: SUCCESS로 기록하지 않고 방금 만든 이 채널만 정리한다.
                print(f"[Discord 동기화] 생성 중 대상 모임이 아니게 됨({rejected.reason}), 채널 정리 recruit_id={recruit_id}")
                cleaned = await delete_meeting_channel(guild, channel.id, recruit_id, PROTECTED_CHANNEL_IDS)
                if not cleaned:
                    await self._record_failure(
                        recruit_id, f"MANUAL: 모임 상태 변경 후 정리 실패 channel_id={channel.id}",
                    )
                elif rejected.reason == "mode":
                    await self._record_failure(
                        recruit_id, "ABORTED: 생성 중 recruit_mode가 채널 대상이 아니게 되어 채널 정리",
                    )
                else:
                    # 마감 연장이나 글 삭제: 조건이 다시 맞으면(마감 도달, 글 복구) 자동 재시도 대상이다.
                    await self._record_failure(
                        recruit_id, "RECHECK: 생성 중 마감 연장 또는 글 삭제로 채널 정리, 조건이 다시 맞으면 재시도",
                    )
                continue
            except ProvisioningUnconfirmed as error:
                # 저장이 실제로 성공했을 수 있다. 채널을 지우지 말고 사람이 확인하게 남긴다.
                print(f"[Discord 동기화] 저장 결과 불명 recruit_id={recruit_id}: {error}")
                await self._record_failure(
                    recruit_id,
                    f"MANUAL: 저장 결과 확인 불가 channel_id={channel.id}: {error}",
                )
                continue
            except Exception as error:
                # UPDATE가 적용되지 않은 것이 확실하다: DB가 추적하지 못하는 채널을 다시 지운다.
                print(f"[Discord 동기화] ID 저장 실패 recruit_id={recruit_id}: {error!r}")
                if await delete_meeting_channel(guild, channel.id, recruit_id, PROTECTED_CHANNEL_IDS):
                    await self._record_failure(recruit_id, f"SAVE {type(error).__name__}: {error}")
                else:
                    await self._record_failure(
                        recruit_id,
                        f"MANUAL: ID 저장 실패 후 정리 실패 channel_id={channel.id}",
                    )
                continue

            print(f"[Discord 동기화] 생성 완료 recruit_id={recruit_id} channel_id={channel.id}")

    async def _record_failure(self, recruit_id: int, message: str) -> None:
        """생성 실패를 기록한다. 기록이 실패해도 남은 PENDING은 나중에 fail_stale_pending이 MANUAL로 표시한다."""
        try:
            await call(self.repository.fail_provisioning, recruit_id, message)
        except Exception as error:
            print(f"[Discord 동기화] 실패 상태 저장 불가 recruit_id={recruit_id}: {error!r}")

    # -- 2. 참여자 권한 ----------------------------------------
    async def sync_participants(self, guild: discord.Guild) -> None:
        """JOINED 참여자에게 권한을 주고 CANCELED 참여자의 권한을 회수한다.

        채널은 캐시나 카테고리가 아니라 저장된 채널 ID로 찾는다. 이미 목표 상태면 건너뛰고,
        채널 조회가 불명확하면 완료로 보지 않고 다음 poll에 다시 시도한다.
        변경은 recruits 행 락(FOR SHARE) 안에서 DISCORD_LOCK_HOLD_SECONDS 안에만 한다:
        그동안 Backend의 모임 방식 변경은 대기하고, 이미 대상이 아니면 GuardRejected로 시작하지 않는다.
        """
        now = datetime.now(KST)
        by_channel: dict[int, list[dict]] = {}
        for state in await call(self.repository.list_participant_states):
            by_channel.setdefault(state["channel_id"], []).append(state)

        for channel_id, states in by_channel.items():
            channel_state, channel = await resolve_channel(guild, channel_id)
            if channel_state == "gone":
                continue  # 채널이 없어졌다: lifecycle이 삭제 완료로 기록한다
            if channel_state == "unknown":
                print(f"[Discord 동기화] 채널 조회가 불명확해 이번 poll은 건너뜀 channel_id={channel_id}")
                continue
            for state in states:
                discord_id = state["discord_id"]
                key = (channel_id, discord_id)
                if self._skip_until.get(key, now) > now:
                    continue
                if state["status"] == "JOINED":
                    needs_change = not _joined_ok(channel, discord_id)
                else:
                    needs_change = not _revoked_ok(channel, discord_id, self.visibility)
                if not needs_change:
                    continue
                recruit_id = state["recruit_id"]
                try:
                    # recruits 행에 FOR SHARE 락을 잡고 Discord 변경이 끝날 때까지 유지한다.
                    async with self.repository.meeting_lock(recruit_id):
                        if state["status"] == "JOINED":
                            work = grant_participant_permissions(guild, channel_id, discord_id)
                        else:
                            work = remove_participant_permissions(
                                guild, channel_id, discord_id, self.visibility
                            )
                        ok = await asyncio.wait_for(work, DISCORD_LOCK_HOLD_SECONDS)
                except GuardRejected:
                    print(f"[Discord 동기화] 대상 모임이 아니거나 삭제됨, 권한 변경 안 함 {key}")
                    continue
                except MeetingLockUnavailable:
                    print(f"[Discord 동기화] recruits 행 잠금 대기 초과, 다음 poll에 재시도 {key}")
                    continue
                except Exception as error:
                    # 다음 poll에서 다시 확인한다.
                    print(f"[Discord 동기화] 권한 변경 실패 {key}: {error!r}")
                    continue
                if ok:
                    self._skip_until.pop(key, None)
                else:  # 서버에 없는 참여자: 잠시 다시 조회하지 않는다
                    self._skip_until[key] = now + MISSING_MEMBER_BACKOFF

    # -- 한 번의 동기화 ---------------------------------------------------------------
    async def run_once(self) -> None:
        """채널 생성 -> 참여자 권한 -> 활동 감지 대상 목록 갱신."""
        guild = self.client.get_guild(GUILD_ID)
        if guild is None:
            print("Discord 서버를 찾을 수 없습니다.")
            return
        await self.provision_meetings(guild)
        await self.sync_participants(guild)
        await call(self.repository.refresh_known_channels)


def create_sync_task(client: discord.Client, repository):
    """SYNC_INTERVAL_SECONDS마다 동기화하는 루프. tasks.loop는 예외로 멈추므로 예외는 로그만 남긴다."""
    sync = DbSync(client, repository)

    @tasks.loop(seconds=SYNC_INTERVAL_SECONDS)
    async def sync_task():
        try:
            await sync.run_once()
        except Exception as error:
            print(f"[Discord 동기화] 검사 실패: {error!r}")

    @sync_task.before_loop
    async def before_sync():
        await client.wait_until_ready()

    return sync_task
