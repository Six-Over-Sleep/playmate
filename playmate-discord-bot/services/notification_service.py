"""Discord DM 알림: 수신 동의(/알림설정)와 notifications polling (10초, 모임 동기화와 별도 task).

동의: external_dm_opt_in = true일 때만 보낸다 (false/NULL은 미허용).
처리: 보낼 대상이 아니면 SKIPPED, 성공 SENT, 실패는 retry_count + 1 후 총 3회 실패 시 FAILED
(그 전에는 PENDING으로 남아 재시도). 한 건의 실패가 다른 알림이나 루프를 멈추지 않는다.

제한 사항 (MVP에서 허용): PROCESSING 상태가 없어 DM 전송 직후 SENT 저장 전에 Bot이 죽으면
같은 DM이 다시 갈 수 있다. Bot은 한 프로세스로만 실행한다는 전제다.
"""
import discord
from discord.ext import tasks

from config import (
    NOTIFICATION_BATCH_SIZE,
    NOTIFICATION_MAX_ATTEMPTS,
    NOTIFICATION_POLL_SECONDS,
    NOTIFICATION_RETRY_DELAY_SECONDS,
)
from repositories.meeting_repository import call
from repositories.notification_repository import NotificationRepository, PendingNotification


class MemberNotLinked(Exception):
    """Discord 계정에 연결된 PlayMate 회원이 없다."""


class SettingSaveFailed(Exception):
    """수신 동의 값을 저장하지 못했다 (DB 권한 부족, 연결 오류 등)."""


def dm_allowed(opt_in: bool | None) -> bool:
    """true만 허용한다. false와 NULL(아직 선택하지 않음)은 모두 미허용이다."""
    return opt_in is True


def build_dm_message(notification: PendingNotification) -> str | None:
    """알림 종류에 맞는 DM 문구. 아직 지원하지 않는 종류면 None (SKIPPED 처리)."""
    if notification["notification_type"] == "COMMENT":
        title = (notification.get("post_title") or "").strip()
        message = "💬 내 게시글에 새 댓글이 달렸어요."
        return f"{message}\n게시글: {title}" if title else message
    return None


def _to_int(value) -> int | None:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


class NotificationService:
    def __init__(self, client: discord.Client, repository: NotificationRepository):
        self.client = client
        self.repository = repository
        self._reported: set[str] = set()

    def _report_once(self, key: str, message: str) -> None:
        if key not in self._reported:
            self._reported.add(key)
            print(message)

    # -- /알림설정 -----------------------------------------------------------
    async def get_opt_in(self, discord_id: int) -> bool | None:
        """현재 저장된 동의 값을 돌려준다. 연결된 회원이 없으면 MemberNotLinked."""
        member = await call(self.repository.find_member_by_discord_id, discord_id)
        if member is None:
            raise MemberNotLinked
        return member["external_dm_opt_in"]

    async def toggle_opt_in(self, discord_id: int) -> bool:
        """DB의 최신 값을 다시 읽어 반대로 저장하고 새 값을 돌려준다.

        저장에 실패하면(권한 부족 포함) SettingSaveFailed를 던진다. 원인은 로그에만 남긴다.
        """
        member = await call(self.repository.find_member_by_discord_id, discord_id)
        if member is None:
            raise MemberNotLinked
        enabled = not dm_allowed(member["external_dm_opt_in"])
        try:
            saved = await call(self.repository.set_dm_opt_in, member["member_id"], enabled)
        except Exception as error:
            print(f"[알림 설정] 저장 실패 member_id={member['member_id']}: {error!r}")
            raise SettingSaveFailed from error
        if not saved:
            print(f"[알림 설정] 저장 대상 없음 member_id={member['member_id']}")
            raise SettingSaveFailed
        return enabled

    # -- notifications polling ---------------------------------------------
    async def poll_once(self) -> None:
        """PENDING 알림을 한 번 처리한다. 테이블이 없으면 건너뛴다. 알림이 0건이어도 정상이다."""
        if not await call(self.repository.notifications_available):
            self._report_once("missing", "[알림] notifications 테이블이 없어 알림 polling을 건너뜁니다.")
            return
        pending = await call(self.repository.claim_pending, NOTIFICATION_BATCH_SIZE,
                             NOTIFICATION_RETRY_DELAY_SECONDS)
        for notification in pending:
            try:
                await self.deliver(notification)
            except Exception as error:
                print(f"[알림] 처리 실패 notification_id={notification.get('notification_id')}: {error!r}")

    @staticmethod
    def skip_reason(notification: PendingNotification) -> str | None:
        """DM을 보내지 않아야 하는 이유. 보내야 하면 None."""
        if notification["actor_member_id"] == notification["receiver_member_id"]:
            return "본인 알림"
        if notification.get("target_missing"):
            return "대상 없음"
        if not dm_allowed(notification.get("receiver_dm_opt_in")):
            return "DM 알림 미동의"
        if _to_int(notification.get("receiver_discord_id")) is None:
            return "Discord 계정 없음"
        if build_dm_message(notification) is None:
            return f"지원하지 않는 알림 종류: {notification['notification_type']}"
        return None

    async def deliver(self, notification: PendingNotification) -> str:
        """알림 한 건을 처리하고 결과 상태(SENT / SKIPPED / PENDING / FAILED)를 돌려준다."""
        notification_id = notification["notification_id"]
        reason = self.skip_reason(notification)
        if reason is not None:
            await call(self.repository.mark_skipped, notification_id, reason)
            return "SKIPPED"
        discord_id = _to_int(notification["receiver_discord_id"])
        try:
            user = self.client.get_user(discord_id) or await self.client.fetch_user(discord_id)
        except discord.NotFound:
            await call(self.repository.mark_skipped, notification_id, "Discord 사용자 없음")
            return "SKIPPED"
        except Exception as error:
            return await self._record_failure(notification_id, f"Discord 사용자 조회 실패: {error!r}")
        try:
            await user.send(build_dm_message(notification))
        except discord.Forbidden:
            return await self._record_failure(notification_id, "DM 수신 차단 (403)")
        except Exception as error:
            return await self._record_failure(notification_id, f"DM 전송 실패: {error!r}")
        # 여기서 Bot이 죽거나 저장이 실패하면 다음 polling에서 중복 DM이 갈 수 있다 (MVP 허용).
        await call(self.repository.mark_sent, notification_id)
        return "SENT"

    async def _record_failure(self, notification_id: int, error: str) -> str:
        status = await call(self.repository.record_failure, notification_id, error,
                            NOTIFICATION_MAX_ATTEMPTS)
        print(f"[알림] DM 전송 실패 notification_id={notification_id} -> {status}: {error}")
        return status or "PENDING"


def create_notification_task(client: discord.Client, service: NotificationService):
    """NOTIFICATION_POLL_SECONDS(10초)마다 poll_once를 실행하는 루프. 예외가 나도 루프는 유지된다."""

    @tasks.loop(seconds=NOTIFICATION_POLL_SECONDS)
    async def notification_task():
        try:
            await service.poll_once()
        except Exception as error:
            print(f"[알림] polling 실패: {error!r}")

    @notification_task.before_loop
    async def before_notification():
        await client.wait_until_ready()

    return notification_task
