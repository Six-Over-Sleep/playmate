"""공용 PlayMate DB와 Discord를 맞추는 DB polling 연동.

Backend는 평소처럼 자신의 테이블만 쓰고, Bot이 주기적으로 읽어서 Discord에 반영한다.

1. 생성(provision): Discord 공간이 없는 regular 모임에 공간을 만들고 ID를
   recruit_discord_channels에 저장한다. short 모임은 건드리지 않는다.
2. 참여자(participants): JOINED 참여자에게 권한을 주고 CANCELED 참여자의 권한을 회수한다.
   members.discord_id를 사용하며, 쓸 수 없는 값(개발용 member_id=-1 포함)은
   저장소 쿼리에서 이미 제외된다.

중복 생성 방지:
    PENDING 행을 먼저 선점한다 (recruit_id PK에 INSERT ... ON CONFLICT DO NOTHING).
    선점 SQL 안에서 regular 여부도 다시 확인한다. recruits.state(모집 상태)와
    meeting_end는 사용하지 않는다.

생성 실패의 분류:
    - Discord 생성 실패, 부분 생성물 정리 성공  -> FAILED (자동 재시도)
    - 생성 실패 + 정리도 실패                   -> 'MANUAL:' (자동 재시도 안 함)
    - 생성 중 regular가 아니게 됨 (정리 성공)   -> 'ABORTED:' (자동 재시도 안 함)
    - 저장 결과를 확인할 수 없거나 ID 불일치     -> 'MANUAL:' (공간은 유지, 자동 삭제/재생성 안 함)
    - 저장이 확실히 실패                        -> 공간 삭제 후 FAILED

TODO: HOST는 아직 알 수 없다 (Backend가 recruit_members.role='HOST'를 저장하지 않음).
공개 범위(PUBLIC/PRIVATE)도 임시로 DEFAULT_VISIBILITY(PUBLIC)를 쓴다.
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

CATEGORY_NAME_LIMIT = 100  # Discord 카테고리 이름 최대 길이
MISSING_MEMBER_BACKOFF = timedelta(minutes=5)  # 서버에 없는 참여자를 다시 조회하기까지의 대기


def _is_member_target(target) -> bool:
    """overwrite 대상이 역할(Role)이 아니라 개별 사용자인지 판별한다."""
    if isinstance(target, discord.Role):
        return False
    if isinstance(target, discord.Object):
        return target.type is not discord.Role
    return True


def _member_overwrite(location, discord_id: int):
    """채널/카테고리(location)에서 특정 사용자의 개인 overwrite를 찾는다. 없으면 None."""
    for target, overwrite in location.overwrites.items():
        if _is_member_target(target) and target.id == discord_id:
            return overwrite
    return None


def _member_has_access(location, discord_id: int) -> bool:
    """사용자가 이 위치에서 쓰기 권한(send_messages) overwrite를 가졌는지 간단히 확인한다."""
    overwrite = _member_overwrite(location, discord_id)
    return overwrite is not None and overwrite.send_messages is True


# 참여자 overwrite가 허용하는 권한. 카테고리, 텍스트, 음성에 같은 세트를 적용한다.
# (services/permissions.py의 grant_participant_permissions와 같은 권한이어야 한다.)
_PARTICIPANT_FLAGS = ("view_channel", "read_message_history", "send_messages", "connect", "speak")


def _joined_ok(location, discord_id: int) -> bool:
    """JOINED 참여자의 목표 상태인지 확인한다: 보기/읽기/쓰기/음성 연결이 모두 명시적으로 허용."""
    overwrite = _member_overwrite(location, discord_id)
    return overwrite is not None and all(
        getattr(overwrite, flag) is True for flag in _PARTICIPANT_FLAGS
    )


def _revoked_ok(location, discord_id: int, visibility: str) -> bool:
    """CANCELED 참여자의 권한이 목표 상태로 회수되었는지 확인한다.

    공통: 쓰기/음성 연결/발언 권한이 하나라도 남아 있으면 회수되지 않은 것이다.
    PUBLIC: 비참여자도 볼 수 있어야 하므로 보기/읽기를 명시적으로 막아 둔 것은 잘못된 상태다.
    PRIVATE: 어떤 접근 권한(보기 포함)도 남아 있으면 안 된다.
    개인 overwrite가 없으면 @everyone 정책을 따르므로 회수된 상태로 본다.
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
    """공용 DB와 Discord를 한 번씩 맞춘다. PostgresMeetingRepository가 필요하다.

    `run_once`가 한 번의 동기화이며, `create_sync_task`가 이를 주기적으로 실행한다.
    """

    def __init__(self, client: discord.Client, repository, visibility: str = DEFAULT_VISIBILITY):
        self.client = client
        self.repository = repository
        self.visibility = visibility  # TODO: Backend가 모임별 값을 저장하면 그 값으로 교체
        self._skip_until: dict[tuple[int, int], datetime] = {}

    # -- 1. regular 모임 -> Discord 공간 -------------------------------
    async def provision_regular_meetings(self, guild: discord.Guild) -> None:
        """Discord 공간이 없는 regular 모임마다 카테고리/채팅/음성을 만들고 ID를 저장한다.

        처리 순서 (모임 하나 기준):
            1. PENDING 행을 선점한다. 이미 처리 중이거나 regular가 아니면 건너뛴다.
            2. 참여 중인 사용자를 포함해 Discord 공간을 만든다.
            3. 생성 도중 모임이 regular가 아니게 되었는지 확인한다. 바뀌었다면 공간을 정리하고
               ABORTED로 기록한다.
            4. 생성된 ID를 DB에 저장한다 (SUCCESS 확정). HOST를 알면 HOST 권한을 부여한다.

        실패 처리:
            모든 실패는 모임별로 recruit_discord_channels에 기록하고 다음 모임으로 넘어간다.
            추적되지 않는 Discord 공간이 남거나 중복 생성되지 않는 것이 목적이다.
            - 생성 실패: 부분 생성물을 정리하고 FAILED (5분 뒤 자동 재시도)
            - 정리까지 실패: 남은 ID와 함께 'MANUAL:' (자동 재시도 안 함)
            - 저장 결과 불명확: 공간을 유지하고 'MANUAL:' (저장이 실제로 되었을 수 있으므로)
            - 저장 확정 실패: 공간을 삭제하고 FAILED (공간이 DB에 추적되지 않으므로)
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
                print(
                    f"[Discord 동기화] 생성 실패 + 정리 실패 "
                    f"recruit_id={recruit_id} remaining={remaining}"
                )
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
                print(
                    f"[Discord 동기화] 생성 중 regular가 아니게 됨, "
                    f"공간 정리 recruit_id={recruit_id}"
                )
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
            host_id = repo.get_host_discord_id(recruit_id)
            if host_id is not None:
                await grant_host_permissions(guild, category.id, host_id)

    async def _record_failure(self, recruit_id: int, message: str) -> None:
        """생성 실패 사유를 PENDING 행에 FAILED로 기록한다.

        기록 자체가 실패해도 예외를 올리지 않는다. 그 경우 PENDING으로 남은 행은
        오래된 PENDING 정리(`fail_stale_pending`)가 나중에 'MANUAL:'로 표시한다.
        """
        try:
            await call(self.repository.fail_provisioning, recruit_id, message)
        except Exception as error:
            print(f"[Discord 동기화] 실패 상태 저장 불가 recruit_id={recruit_id}: {error!r}")

    # -- 2. 참여자 권한 ----------------------------------------
    async def sync_participants(self, guild: discord.Guild) -> None:
        """JOINED 참여자에게 권한을 주고, CANCELED 참여자의 권한을 회수한다.

        처리 순서:
            1. 라이브 regular 모임의 JOINED/CANCELED 참여자 목록을 읽는다
               (discord_id가 없는 회원과 member_id=-1은 이미 제외되어 있다).
            2. 모임별로 대상 위치(카테고리/텍스트/음성)를 DB에 저장된 ID 기준으로 찾는다.
            3. 모든 위치가 목표 상태이면 아무것도 하지 않는다 (같은 poll을 반복해도 안전).
            4. 아니면 recruits 행에 row lock을 잡고 권한을 변경한다.

        업무 규칙:
            채널 위치는 카테고리 하위 목록이나 캐시가 아니라 저장된 ID가 기준이다.
            조회가 불명확한 채널(Forbidden/HTTP 오류 등)이 있으면 조회 가능한 채널은 처리하되
            완료로 보지 않고 매 poll 다시 시도한다.

        row lock이 필요한 이유:
            권한을 바꾸는 동안 Backend가 모임을 short로 바꾸면 short 모임의 Discord 권한을
            건드리게 된다. FOR SHARE 락을 잡으면 그 UPDATE는 작업이 끝날 때까지 대기하고,
            이미 short로 commit되었다면 락을 얻는 순간 GuardRejected로 작업이 시작되지 않는다.
            Discord 작업이 멈춰도 락이 무기한 유지되지 않도록 DISCORD_LOCK_HOLD_SECONDS 안에
            끝나지 않으면 중단하고 ROLLBACK한다.

        실패 처리:
            참여자별로 실패를 로그에 남기고 다음 참여자로 넘어간다. 일부만 적용된 변경은
            다음 poll에서 모든 위치를 다시 확인해 이어서 맞춘다.
            서버에 없는 참여자는 MISSING_MEMBER_BACKOFF 동안 다시 조회하지 않는다.
        """
        now = datetime.now(KST)
        by_category: dict[int, list[dict]] = {}
        for state in await call(self.repository.list_participant_states):
            by_category.setdefault(state["discord_category_id"], []).append(state)

        for category_id, states in by_category.items():
            # 대상 위치는 캐시나 카테고리 하위 목록이 아니라 DB에 저장된 ID로 찾는다.
            # (채널이 캐시에 없거나 다른 카테고리로 옮겨졌어도 그 채널에 적용해야 한다.)
            channel_ids = [states[0].get("text_channel_id"), states[0].get("voice_channel_id")]
            _, locations, unresolved = await resolve_space(guild, category_id, channel_ids)
            if not locations:
                continue
            if unresolved:
                # 일부 채널을 조회하지 못했다. 조회된 채널은 처리하지만 완료로 보지 않고
                # 매 poll 다시 시도한다.
                print(
                    f"[Discord 동기화] 채널 조회가 불명확해 완료로 보지 않음 "
                    f"category_id={category_id}"
                )
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
                    print(
                        f"[Discord 동기화] regular 모임이 아니거나 삭제됨, "
                        f"권한 변경 안 함 {key}"
                    )
                    continue
                except RegularLockUnavailable:
                    print(
                        f"[Discord 동기화] recruits 행 잠금 대기 초과, "
                        f"다음 poll에 재시도 {key}"
                    )
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
        """동기화 한 번: 공간 생성 -> 참여자 권한 -> 활동 감지 대상 목록 갱신 순서로 실행한다."""
        guild = self.client.get_guild(GUILD_ID)
        if guild is None:
            print("Discord 서버를 찾을 수 없습니다.")
            return
        await self.provision_regular_meetings(guild)
        await self.sync_participants(guild)
        await call(self.repository.refresh_known_categories)


def create_sync_task(client: discord.Client, repository):
    """DbSync를 SYNC_INTERVAL_SECONDS마다 실행하는 discord.ext.tasks 루프를 만든다.

    한 번의 동기화가 실패해도 로그만 남기고 루프를 유지한다. tasks.loop는 처리되지 않은
    예외가 나면 멈추기 때문에, 일시적인 DB/Discord 오류로 동기화가 영구 중단되지 않게 한다.
    """
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
