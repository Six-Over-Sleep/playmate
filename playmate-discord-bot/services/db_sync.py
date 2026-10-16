"""Reconcile the shared PlayMate DB with Discord (DB polling integration).

The backend only writes its normal tables; the Bot polls and acts:

1. provision: regular recruits without a Discord space get one, and the IDs are
   stored in recruit_discord_channels. short recruits are never touched.
2. participants: JOINED members get permissions, CANCELED members lose them,
   using members.discord_id. Members without a usable discord_id (including the
   dev member_id=-1) are skipped by the repository query.

Duplicate creation is prevented by claiming a PENDING row first
(INSERT ... ON CONFLICT DO NOTHING on the recruit_id primary key; the recruit is
re-validated as regular inside that statement). recruits.state and meeting_end
are deliberately not used.

Failure classes when creating a space:
- Discord creation failed, partial resources removed -> FAILED (auto retry).
- Creation failed and cleanup also failed          -> 'MANUAL:' (no auto retry).
- Save outcome unknown / mismatching IDs            -> 'MANUAL:' and the space is
  kept (never deleted or re-created automatically).
- Save definitely failed                            -> space removed, FAILED.

TODO: HOST is not resolved yet (no recruit_members.role='HOST' written by the
backend), and visibility is the temporary DEFAULT_VISIBILITY (PUBLIC).
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

CATEGORY_NAME_LIMIT = 100  # Discord limit
MISSING_MEMBER_BACKOFF = timedelta(minutes=5)


def _is_member_target(target) -> bool:
    if isinstance(target, discord.Role):
        return False
    if isinstance(target, discord.Object):
        return target.type is not discord.Role
    return True


def _member_overwrite(location, discord_id: int):
    for target, overwrite in location.overwrites.items():
        if _is_member_target(target) and target.id == discord_id:
            return overwrite
    return None


def _member_has_access(location, discord_id: int) -> bool:
    """True when the member holds the write overwrite here (quick helper)."""
    overwrite = _member_overwrite(location, discord_id)
    return overwrite is not None and overwrite.send_messages is True


# Permissions a participant overwrite grants (applied to category, text, voice).
_PARTICIPANT_FLAGS = ("view_channel", "read_message_history", "send_messages", "connect", "speak")


def _joined_ok(location, discord_id: int) -> bool:
    """Participant target state: view, read, write and voice all explicitly allowed."""
    overwrite = _member_overwrite(location, discord_id)
    return overwrite is not None and all(
        getattr(overwrite, flag) is True for flag in _PARTICIPANT_FLAGS
    )


def _revoked_ok(location, discord_id: int, visibility: str) -> bool:
    """Non-participant target state after cancel.

    No write/voice may remain. PUBLIC: still visible (an explicit hide is wrong).
    PRIVATE: no access of any kind may remain (no view either).
    """
    overwrite = _member_overwrite(location, discord_id)
    if overwrite is None:
        return True  # falls back to @everyone, which carries the visibility policy
    if any(getattr(overwrite, flag) is True for flag in ("send_messages", "connect", "speak")):
        return False
    if visibility.upper() == "PRIVATE":
        return overwrite.view_channel is not True and overwrite.read_message_history is not True
    return overwrite.view_channel is not False and overwrite.read_message_history is not False


class DbSync:
    """DB <-> Discord reconciliation; needs a PostgresMeetingRepository."""

    def __init__(self, client: discord.Client, repository, visibility: str = DEFAULT_VISIBILITY):
        self.client = client
        self.repository = repository
        self.visibility = visibility  # TODO: per-meeting value once the backend stores it
        self._skip_until: dict[tuple[int, int], datetime] = {}

    # -- 1. regular meeting -> Discord space -------------------------------
    async def provision_regular_meetings(self, guild: discord.Guild) -> None:
        repo = self.repository
        stale = await call(repo.fail_stale_pending)
        if stale:
            print(f"[Discord 동기화] 중단된 PENDING {stale}건을 FAILED(MANUAL)로 표시")

        for recruit in await call(repo.list_provisionable_recruits):
            recruit_id = recruit["recruit_id"]
            if not await call(repo.claim_provisioning, recruit_id):
                continue  # not regular anymore, or another worker/tick owns it

            name = (recruit.get("title") or "").strip() or f"모임 {recruit_id}"
            name = name[:CATEGORY_NAME_LIMIT]
            try:
                participant_ids = await call(repo.list_joined_discord_ids, recruit_id)
                category, text_channel, voice_channel = await create_meeting_space(
                    guild, name, "regular", self.visibility, participant_ids, True,
                )
            except MeetingSpaceCleanupError as error:
                # Leftovers may exist on Discord: never auto-retry (would duplicate).
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
                still_regular = True  # unknown: complete_provisioning re-checks atomically
            if not still_regular:
                print(f"[Discord 동기화] 생성 중 regular가 아니게 됨, 공간 정리 recruit_id={recruit_id}")
                if await delete_meeting_space(
                    guild, category.id, extra_channel_ids=[text_channel.id, voice_id]):
                    await self._record_failure(
                        recruit_id, "ABORTED: 생성 중 recruit_mode가 regular가 아니게 되어 공간 정리")
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
                # The save may have succeeded: keep the space, flag for a human.
                print(f"[Discord 동기화] 저장 결과 불명 recruit_id={recruit_id}: {error}")
                await self._record_failure(
                    recruit_id,
                    f"MANUAL: 저장 결과 확인 불가 category_id={category.id} "
                    f"text={text_channel.id} voice={voice_id}: {error}",
                )
                continue
            except Exception as error:
                # The UPDATE definitely did not apply: remove the untracked space.
                print(f"[Discord 동기화] ID 저장 실패 recruit_id={recruit_id}: {error!r}")
                if await delete_meeting_space(
                    guild, category.id, extra_channel_ids=[text_channel.id, voice_id]):
                    await self._record_failure(recruit_id, f"SAVE {type(error).__name__}: {error}")
                else:
                    await self._record_failure(
                        recruit_id,
                        f"MANUAL: ID 저장 실패 후 정리 실패 category_id={category.id}",
                    )
                continue

            print(f"[Discord 동기화] 생성 완료 recruit_id={recruit_id} category_id={category.id}")
            host_id = repo.get_host_discord_id(recruit_id)
            if host_id is not None:
                await grant_host_permissions(guild, category.id, host_id)

    async def _record_failure(self, recruit_id: int, message: str) -> None:
        try:
            await call(self.repository.fail_provisioning, recruit_id, message)
        except Exception as error:
            # The stale-PENDING sweep will flag it MANUAL later.
            print(f"[Discord 동기화] 실패 상태 저장 불가 recruit_id={recruit_id}: {error!r}")

    # -- 2. participant permissions ----------------------------------------
    async def sync_participants(self, guild: discord.Guild) -> None:
        now = datetime.now(KST)
        by_category: dict[int, list[dict]] = {}
        for state in await call(self.repository.list_participant_states):
            by_category.setdefault(state["discord_category_id"], []).append(state)

        for category_id, states in by_category.items():
            # Locations come from the STORED ids (cache / API / wherever the channel
            # lives now), never from the category's child list alone.
            channel_ids = [states[0].get("text_channel_id"), states[0].get("voice_channel_id")]
            _, locations, unresolved = await resolve_space(guild, category_id, channel_ids)
            if not locations:
                continue
            if unresolved:
                # Some stored channel could not be looked up: reachable channels are
                # still handled, but the change is never judged complete -> retried every poll.
                print(f"[Discord 동기화] 채널 조회가 불명확해 완료로 보지 않음 category_id={category_id}")
            for state in states:
                discord_id = state["discord_id"]
                key = (category_id, discord_id)
                if self._skip_until.get(key, now) > now:
                    continue
                # Done only when the category AND every stored channel are in the target state.
                if state["status"] == "JOINED":
                    needs_change = unresolved or not all(_joined_ok(l, discord_id) for l in locations)
                else:
                    needs_change = unresolved or not all(
                        _revoked_ok(l, discord_id, self.visibility) for l in locations
                    )
                if not needs_change:
                    continue
                recruit_id = state["recruit_id"]
                try:
                    # recruits row locked (FOR SHARE) for the whole Discord change:
                    # a concurrent regular->short UPDATE waits for it, and a short
                    # change that committed first stops us before any Discord call.
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
                    # Partial application is re-checked (all locations) next poll.
                    print(f"[Discord 동기화] 권한 변경 실패 {key}: {error!r}")
                    continue
                if ok:
                    self._skip_until.pop(key, None)
                else:  # member not in the guild (or not fetchable): back off
                    self._skip_until[key] = now + MISSING_MEMBER_BACKOFF

    # -- tick ---------------------------------------------------------------
    async def run_once(self) -> None:
        guild = self.client.get_guild(GUILD_ID)
        if guild is None:
            print("Discord 서버를 찾을 수 없습니다.")
            return
        await self.provision_regular_meetings(guild)
        await self.sync_participants(guild)
        await call(self.repository.refresh_known_categories)


def create_sync_task(client: discord.Client, repository):
    """Periodic DB sync loop; errors are logged so the loop keeps running."""
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
