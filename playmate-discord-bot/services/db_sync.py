"""공용 DB를 주기적으로 읽어 Discord에 반영한다 (DB polling).

1. 생성: Discord 공간이 없는 regular 모임에 공간을 만들고 ID를 저장한다 (short 제외).
2. 참여자: JOINED에게 권한을 주고 CANCELED의 권한을 회수한다.

생성 실패 분류 (sync_error):
    - 생성 실패, 정리 성공                -> FAILED (자동 재시도)
    - 생성 실패 + 정리도 실패             -> 'MANUAL:' (자동 재시도 안 함)
    - 생성 중 regular가 아니게 됨          -> 'ABORTED:' (자동 재시도 안 함)
    - 저장 결과 불명 / ID 불일치           -> 'MANUAL:' (공간 유지, 자동 삭제/재생성 안 함)
    - 저장이 확실히 실패                  -> 공간 삭제 후 FAILED

HOST 권한은 공간 생성 직후 한 번만 부여한다 (TODO: 기존 공간 소급, 실패 시 재시도, regular_lock 적용).
공개 범위는 임시로 DEFAULT_VISIBILITY(PUBLIC)를 쓴다.
"""
import asyncio
from datetime import datetime, timedelta

import discord
from discord.ext import tasks

from config import (
    DEFAULT_VISIBILITY,
    DISCORD_LOCK_HOLD_SECONDS,
    GUILD_ID,
    KST,
    SYNC_INTERVAL_SECONDS,
)
from repositories.meeting_repository import (
    GuardRejected,
    ProvisioningUnconfirmed,
    RegularLockUnavailable,
    call,
)
from services.meeting_space import (
    PARTICIPANT_PERMISSIONS,
    MeetingSpaceCleanupError,
    create_meeting_space,
    delete_meeting_space,
    resolve_space,
)
from services.permissions import (
    grant_host_permissions,
    grant_participant_permissions,
    remove_participant_permissions,
)

CATEGORY_NAME_LIMIT = 100  # Discord 카테고리 이름 최대 길이
MISSING_MEMBER_BACKOFF = timedelta(minutes=5)  # 서버에 없는 참여자를 다시 조회하기까지의 대기


def _is_member_target(target) -> bool:
    """overwrite 대상이 역할이 아니라 개별 사용자인지."""
    if isinstance(target, discord.Role):
        return False
    if isinstance(target, discord.Object):
        return target.type is not discord.Role
    return True


def _member_overwrite(location, discord_id: int):
    """location에서 특정 사용자의 개인 overwrite. 없으면 None."""
    for target, overwrite in location.overwrites.items():
        if _is_member_target(target) and target.id == discord_id:
            return overwrite
    return None


def _member_has_access(location, discord_id: int) -> bool:
    """사용자가 이 위치에서 send_messages overwrite를 가졌는지."""
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
    """CANCELED 목표 상태: 쓰기/음성 권한 없음.

    PUBLIC은 보기/읽기를 막아 두면 안 되고, PRIVATE은 보기/읽기도 남으면 안 된다.
    개인 overwrite가 없으면 @everyone 정책을 따르므로 회수된 것으로 본다.
    """
    overwrite = _member_overwrite(location, discord_id)
    if overwrite is None:
        return True
    if any(getattr(overwrite, flag) is True for flag in ("send_messages", "connect", "speak")):
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

    # -- 1. regular 모임 -> Discord 공간 -------------------------------
    async def provision_regular_meetings(self, guild: discord.Guild) -> None:
        """공간이 없는 regular 모임마다 선점 -> 생성 -> regular 재확인 -> ID 저장(SUCCESS) 순서로 처리한다.

        실패는 모임별로 기록하고 다음 모임으로 넘어간다 (분류는 모듈 docstring 참고).
        추적되지 않는 공간이 남거나 중복 생성되지 않는 것이 목적이다.
        """
        repo = self.repository
        stale = await call(repo.fail_stale_pending)
        if stale:
            print(f"[Discord 동기화] 중단된 PENDING {stale}건을 FAILED(MANUAL)로 표시")

        for recruit in await call(repo.list_provisionable_recruits):
            recruit_id = recruit["recruit_id"]
            if not await call(repo.claim_provisioning, recruit_id):
                continue  # 더 이상 regular가 아니거나, 다른 worker/이전 주기가 이미 처리 중

            name = (recruit.get("title") or "").strip() or f"모임 {recruit_id}"
            name = name[:CATEGORY_NAME_LIMIT]
            try:
                participant_ids = await call(repo.list_joined_discord_ids, recruit_id)
                category, text_channel, voice_channel = await create_meeting_space(
                    guild, name, "regular", self.visibility, participant_ids, True,
                )
            except MeetingSpaceCleanupError as error:
                # Discord에 잔존물이 있을 수 있다. 자동 재시도하면 중복 생성되므로 사람이 확인한다.
                remaining = ",".join(str(i) for i in error.remaining_ids)
                print(f"[Discord 동기화] 생성 실패 + 정리 실패 recruit_id={recruit_id} remaining={remaining}")
                await self._record_failure(
                    recruit_id,
                    f"MANUAL: 생성 실패 후 정리 실패 remaining_ids={remaining} cause={error}",
                )
                continue
            except Exception as error:
                print(f"[Discord 동기화] 생성 실패 recruit_id={recruit_id}: {error!r}")
                await self._record_failure(recruit_id, f"CREATE {type(error).__name__}: {error}")
                continue

            voice_id = voice_channel.id if voice_channel else None
            try:
                still_regular = await call(repo.is_regular, recruit_id)
            except Exception:
                # 확인할 수 없으면 통과시킨다. complete_provisioning이 저장 SQL 안에서 다시 확인한다.
                still_regular = True
            if not still_regular:
                print(f"[Discord 동기화] 생성 중 regular가 아니게 됨, 공간 정리 recruit_id={recruit_id}")
                if await delete_meeting_space(
                    guild, category.id, extra_channel_ids=[text_channel.id, voice_id]
                ):
                    await self._record_failure(
                        recruit_id,
                        "ABORTED: 생성 중 recruit_mode가 regular가 아니게 되어 공간 정리",
                    )
                else:
                    await self._record_failure(
                        recruit_id,
                        f"MANUAL: recruit_mode 변경 후 정리 실패 category_id={category.id} "
                        f"text={text_channel.id} voice={voice_id}",
                    )
                continue
            try:
                await call(
                    repo.complete_provisioning, recruit_id, category.id,
                    text_channel.id, voice_id, datetime.now(KST),
                )
            except ProvisioningUnconfirmed as error:
                # 저장이 실제로 성공했을 수 있다. 공간을 지우지 말고 사람이 확인하게 남긴다.
                print(f"[Discord 동기화] 저장 결과 불명 recruit_id={recruit_id}: {error}")
                await self._record_failure(
                    recruit_id,
                    f"MANUAL: 저장 결과 확인 불가 category_id={category.id} "
                    f"text={text_channel.id} voice={voice_id}: {error}",
                )
                continue
            except Exception as error:
                # UPDATE가 적용되지 않은 것이 확실하다: DB가 추적하지 못하는 공간을 다시 지운다.
                print(f"[Discord 동기화] ID 저장 실패 recruit_id={recruit_id}: {error!r}")
                if await delete_meeting_space(
                    guild, category.id, extra_channel_ids=[text_channel.id, voice_id]
                ):
                    await self._record_failure(recruit_id, f"SAVE {type(error).__name__}: {error}")
                else:
                    await self._record_failure(
                        recruit_id,
                        f"MANUAL: ID 저장 실패 후 정리 실패 category_id={category.id}",
                    )
                continue

            print(f"[Discord 동기화] 생성 완료 recruit_id={recruit_id} category_id={category.id}")
            try:
                host_id = await call(repo.get_host_discord_id, recruit_id)
                if host_id is None:
                    print(f"[Discord 동기화] HOST 없음, HOST 권한 건너뜀 recruit_id={recruit_id}")
                else:
                    await grant_host_permissions(guild, category.id, host_id)
            except Exception as error:
                # 공간은 이미 SUCCESS로 저장됐다. HOST 권한 실패가 다른 모임 처리를 막지 않게 로그만 남긴다.
                print(f"[Discord 동기화] HOST 권한 부여 실패 recruit_id={recruit_id}: {error!r}")

    async def _record_failure(self, recruit_id: int, message: str) -> None:
        """생성 실패를 기록한다. 기록이 실패해도 남은 PENDING은 나중에 fail_stale_pending이 MANUAL로 표시한다."""
        try:
            await call(self.repository.fail_provisioning, recruit_id, message)
        except Exception as error:
            print(f"[Discord 동기화] 실패 상태 저장 불가 recruit_id={recruit_id}: {error!r}")

    # -- 2. 참여자 권한 ----------------------------------------
    async def sync_participants(self, guild: discord.Guild) -> None:
        """JOINED 참여자에게 권한을 주고 CANCELED 참여자의 권한을 회수한다.

        채널은 캐시나 카테고리 하위 목록이 아니라 저장된 ID로 찾는다. 모든 위치가 목표 상태면
        건너뛰고, 조회가 불명확한 채널이 있으면 완료로 보지 않고 매 poll 다시 시도한다.
        변경은 recruits 행 락(FOR SHARE) 안에서 DISCORD_LOCK_HOLD_SECONDS 안에만 한다:
        그동안 Backend의 short 변경은 대기하고, 이미 short라면 GuardRejected로 시작하지 않는다.
        """
        now = datetime.now(KST)
        by_category: dict[int, list[dict]] = {}
        for state in await call(self.repository.list_participant_states):
            by_category.setdefault(state["discord_category_id"], []).append(state)

        for category_id, states in by_category.items():
            channel_ids = [states[0].get("text_channel_id"), states[0].get("voice_channel_id")]
            _, locations, unresolved = await resolve_space(guild, category_id, channel_ids)
            if not locations:
                continue
            if unresolved:
                print(f"[Discord 동기화] 채널 조회가 불명확해 완료로 보지 않음 category_id={category_id}")
            for state in states:
                discord_id = state["discord_id"]
                key = (category_id, discord_id)
                if self._skip_until.get(key, now) > now:
                    continue
                # 카테고리와 저장된 모든 채널이 목표 상태일 때만 완료로 본다.
                if state["status"] == "JOINED":
                    needs_change = unresolved or not all(
                        _joined_ok(l, discord_id) for l in locations
                    )
                else:
                    needs_change = unresolved or not all(
                        _revoked_ok(l, discord_id, self.visibility) for l in locations
                    )
                if not needs_change:
                    continue
                recruit_id = state["recruit_id"]
                try:
                    # recruits 행에 FOR SHARE 락을 잡고 Discord 변경이 끝날 때까지 유지한다.
                    async with self.repository.regular_lock(recruit_id):
                        if state["status"] == "JOINED":
                            work = grant_participant_permissions(
                                guild, category_id, discord_id, channel_ids
                            )
                        else:
                            work = remove_participant_permissions(
                                guild, category_id, discord_id, self.visibility, channel_ids
                            )
                        ok = await asyncio.wait_for(work, DISCORD_LOCK_HOLD_SECONDS)
                except GuardRejected:
                    print(f"[Discord 동기화] regular 모임이 아니거나 삭제됨, 권한 변경 안 함 {key}")
                    continue
                except RegularLockUnavailable:
                    print(f"[Discord 동기화] recruits 행 잠금 대기 초과, 다음 poll에 재시도 {key}")
                    continue
                except Exception as error:
                    # 일부만 적용되었을 수 있다. 다음 poll에서 모든 위치를 다시 확인한다.
                    print(f"[Discord 동기화] 권한 변경 실패 {key}: {error!r}")
                    continue
                if ok:
                    self._skip_until.pop(key, None)
                else:  # 서버에 없거나 조회할 수 없는 참여자: 잠시 다시 조회하지 않는다
                    self._skip_until[key] = now + MISSING_MEMBER_BACKOFF

    # -- 한 번의 동기화 ---------------------------------------------------------------
    async def run_once(self) -> None:
        """공간 생성 -> 참여자 권한 -> 활동 감지 대상 목록 갱신."""
        guild = self.client.get_guild(GUILD_ID)
        if guild is None:
            print("Discord 서버를 찾을 수 없습니다.")
            return
        await self.provision_regular_meetings(guild)
        await self.sync_participants(guild)
        await call(self.repository.refresh_known_categories)


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
