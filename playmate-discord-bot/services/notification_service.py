"""Discord DM 알림: 수신 동의(/알림설정)와 notifications polling (10초, 모임 동기화와 별도 task).

동의: 기본값 ON. external_dm_opt_in = false(사용자가 /알림설정으로 끔)일 때만 보내지 않는다.
     NULL은 아직 선택하지 않은 회원(기존 회원·DB 기본값 적용 전 가입)이라 true와 같이 ON으로 본다.
처리: 보낼 대상이 아니면 SKIPPED, 성공 SENT, 실패는 retry_count + 1 후 총 3회 실패 시 FAILED
(그 전에는 PENDING으로 남아 재시도). 한 건의 실패가 다른 알림이나 루프를 멈추지 않는다.

공동 선점 (Issue #171): notification_dm_deliveries(053)가 있으면 **보내기 전에** DM Lambda와 같은 테이블로 선점한다
(repositories.dm_delivery_repository). 그러면 Gateway와 Lambda가 동시에 켜져 있어도 같은 알림은 한 곳만 보낸다.
  - 전송되지 않았음이 확실한 실패(403, 4xx, 사용자 조회 실패)는 기존 정책 그대로: retry_count + 1, 60초 뒤 재시도, 3회째 FAILED
  - 결과가 불명확한 실패(5xx, 타임아웃, 연결 끊김)와 선점 후 만료는 재발송하지 않고 FAILED로 마감한다 (중복 대신 누락 가능, 경고 로그)
테이블이 없으면(053 적용 전) 기존 방식으로 동작한다. 기존 방식의 제한 사항 (MVP에서 허용): PROCESSING 상태가 없어
DM 전송 직후 SENT 저장 전에 Bot이 죽으면 같은 DM이 다시 갈 수 있다. Bot은 한 프로세스로만 실행한다는 전제다.
"""
from datetime import datetime, timezone
from functools import partial

import discord
from discord.ext import tasks

from config import (
    DM_GATEWAY_CLAIM_SECONDS,
    WEB_BASE_URL,
    NOTIFICATION_BATCH_SIZE,
    NOTIFICATION_MAX_ATTEMPTS,
    NOTIFICATION_POLL_SECONDS,
    NOTIFICATION_RETRY_DELAY_SECONDS,
)
from repositories.meeting_repository import call
from repositories.notification_repository import NotificationRepository, PendingNotification
from services.notification_policy import (  # noqa: F401  (기존 import 경로 유지: 다시 내보낸다)
    DM_MESSAGES, LINK_LABEL, build_dm_message, dm_allowed, skip_reason as _policy_skip_reason,
    to_discord_id as _to_int,
)
from services.web_links import notification_post_url


class MemberNotLinked(Exception):
    """Discord 계정에 연결된 PlayMate 회원이 없다."""


class SettingSaveFailed(Exception):
    """수신 동의 값을 저장하지 못했다 (DB 권한 부족, 연결 오류 등)."""


class NotificationService:
    def __init__(self, client: discord.Client, repository: NotificationRepository,
                 base_url: str | None = WEB_BASE_URL, deliveries=None):
        self.client = client
        self.repository = repository
        self.base_url = base_url  # PLAYMATE_WEB_BASE_URL. 없으면 링크 없이 DM만 보낸다.
        # repositories.dm_delivery_repository.DmDeliveryRepository. 053이 적용돼 있으면 반드시 이걸로 선점한다.
        self.deliveries = deliveries
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
        if self.deliveries is not None and await call(self.deliveries.available):
            await self._poll_claimed()
            return
        pending = await call(self.repository.claim_pending, NOTIFICATION_BATCH_SIZE,
                             NOTIFICATION_RETRY_DELAY_SECONDS)
        for notification in pending:
            try:
                await self.deliver(notification)
            except Exception as error:
                print(f"[알림] 처리 실패 notification_id={notification.get('notification_id')}: {error!r}")

    def post_link(self, notification: PendingNotification) -> str | None:
        """원본 게시글 링크. 만들 수 없으면 None이며, 어떤 이유로든 DM 발송은 막지 않는다."""
        if not self.base_url:
            self._report_once("no_base_url", "[알림] PLAYMATE_WEB_BASE_URL이 없거나 사용할 수 없어 DM에 원본 링크를 붙이지 않습니다.")
            return None
        try:
            url = notification_post_url(self.base_url, notification)
        except Exception as error:  # 링크 생성 오류가 알림 전송을 막으면 안 된다
            print(f"[알림] 링크 생성 실패 notification_id={notification.get('notification_id')}: {type(error).__name__}")
            return None
        if url is None:
            print(f"[알림] 게시글 종류를 확인할 수 없어 링크 없이 보냅니다 notification_id={notification.get('notification_id')}")
        return url

    @staticmethod
    def skip_reason(notification: PendingNotification) -> str | None:
        """DM을 보내지 않아야 하는 이유. 보내야 하면 None (규칙은 services.notification_policy)."""
        return _policy_skip_reason(notification)

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
            await user.send(build_dm_message(notification, self.post_link(notification)))
        except discord.Forbidden:
            return await self._record_failure(notification_id, "DM 수신 차단 (403)")
        except Exception as error:
            return await self._record_failure(notification_id, f"DM 전송 실패: {error!r}")
        # 여기서 Bot이 죽거나 저장이 실패하면 다음 polling에서 중복 DM이 갈 수 있다 (MVP 허용).
        await call(self.repository.mark_sent, notification_id)
        return "SENT"

    # -- 공동 선점 경로 (053 적용 후) ------------------------------------------------------------------------
    async def _poll_claimed(self) -> None:
        now = datetime.now(timezone.utc)
        await call(self.deliveries.expire_gateway_claims, now)   # 만료된 Gateway 선점: 재발송 없이 마감 + 경고
        claims = await call(partial(self.deliveries.claim, "GATEWAY", now, limit=NOTIFICATION_BATCH_SIZE,
                                    stale_seconds=DM_GATEWAY_CLAIM_SECONDS))
        for claim in claims:
            try:
                await self.deliver_claimed(claim)
            except Exception as error:
                print(f"[알림] 처리 실패 notification_id={claim['notification'].get('notification_id')}: {error!r}")

    @staticmethod
    def _failure_certain(error: Exception) -> bool:
        """전송되지 않았음이 확실한가. 403/404/그 밖의 4xx는 확실, 5xx·타임아웃·연결 오류 등은 불명."""
        if isinstance(error, (discord.Forbidden, discord.NotFound)):
            return True
        status = getattr(error, "status", None)
        return isinstance(error, discord.HTTPException) and isinstance(status, int) and 400 <= status < 500

    async def deliver_claimed(self, claim: dict) -> str:
        """선점한 알림 한 건을 보낸다 (건너뛸 대상은 선점 단계에서 이미 SKIPPED). 결과 상태를 돌려준다."""
        notification, token = claim["notification"], claim["claim_token"]
        notification_id = notification["notification_id"]
        discord_id = _to_int(notification["receiver_discord_id"])
        try:
            user = self.client.get_user(discord_id) or await self.client.fetch_user(discord_id)
        except discord.NotFound:
            await call(self.deliveries.gateway_skipped, notification_id, token, datetime.now(timezone.utc),
                       "Discord 사용자 없음")
            return "SKIPPED"
        except Exception as error:   # 보내기 전 단계: 전송되지 않았음이 확실하다
            return await self._claimed_failure(notification_id, token, f"Discord 사용자 조회 실패: {error!r}", final=False)
        try:
            await user.send(build_dm_message(notification, self.post_link(notification)))
        except discord.Forbidden:
            return await self._claimed_failure(notification_id, token, "DM 수신 차단 (403)", final=False)
        except Exception as error:
            certain = self._failure_certain(error)
            return await self._claimed_failure(notification_id, token, f"DM 전송 실패: {error!r}", final=not certain)
        # 여기서 Bot이 죽거나 저장이 실패하면 선점이 만료된 뒤 재발송 없이 FAILED로 마감된다 (중복 대신 누락 가능).
        await call(self.deliveries.gateway_sent, notification_id, token, datetime.now(timezone.utc))
        return "SENT"

    async def _claimed_failure(self, notification_id: int, token: str, error: str, *, final: bool) -> str:
        status = await call(partial(self.deliveries.gateway_failure, notification_id, token, datetime.now(timezone.utc),
                                    error, final=final))
        print(f"[알림] DM 전송 실패 notification_id={notification_id} -> {status}: {error}"
              + (" (결과 불명: 재발송하지 않음)" if final else ""))
        return status or "PENDING"

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
