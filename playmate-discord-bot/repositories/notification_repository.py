"""DM 알림 저장소: members 수신 동의 조회/변경, notifications 상태 기록.

상태: PENDING -> SENT(sent_at 기록) / SKIPPED / 실패 시 retry_count + 1 후 한도 도달하면 FAILED.
모든 상태 변경은 status = 'PENDING'인 행에만 적용되어 이미 끝난 알림을 덮어쓰지 않는다.
시각은 DB의 CURRENT_TIMESTAMP를 쓰고, updated_at은 DB trigger가 갱신하므로 SET하지 않는다.
"""
from typing import Any, Protocol, TypedDict

from repositories.db import Database

ERROR_MESSAGE_LIMIT = 500


class PendingNotification(TypedDict):
    """claim_pending이 돌려주는 값. receiver_*는 members JOIN, post_title은 posts JOIN 결과다."""
    notification_id: int
    notification_type: str  # COMMENT / REPLY / REACTION
    receiver_member_id: int
    actor_member_id: int
    post_id: int | None
    comment_id: int | None
    retry_count: int
    receiver_discord_id: str | None
    receiver_dm_opt_in: bool | None
    post_title: str | None
    target_missing: bool  # 연결된 게시글 / 댓글이 없거나 삭제됨


class NotificationRepository(Protocol):
    def find_member_by_discord_id(self, discord_id: int) -> dict[str, Any] | None: ...
    def set_dm_opt_in(self, member_id: int, enabled: bool) -> bool: ...
    def notifications_available(self) -> bool: ...
    def claim_pending(self, limit: int, retry_delay_seconds: int) -> list[PendingNotification]: ...
    def mark_sent(self, notification_id: int) -> bool: ...
    def mark_skipped(self, notification_id: int, reason: str) -> bool: ...
    def record_failure(self, notification_id: int, error: str, max_attempts: int) -> str | None: ...


class PostgresNotificationRepository:
    def __init__(self, database: Database):
        self._db = database

    # -- members: 알림 수신 동의 -------------------------------------------
    def find_member_by_discord_id(self, discord_id: int) -> dict[str, Any] | None:
        """Discord 사용자에 연결된 PlayMate 회원을 찾는다. members.discord_id는 varchar다."""
        return self._db.execute(
            """
            SELECT member_id, external_dm_opt_in
              FROM members
             WHERE discord_id = %s AND member_id <> -1
            """,
            (str(discord_id),), fetch="one",
        )

    def set_dm_opt_in(self, member_id: int, enabled: bool) -> bool:
        """external_dm_opt_in만 바꾼다. 필요한 DB 권한: members(external_dm_opt_in) UPDATE."""
        updated = self._db.execute(
            "UPDATE members SET external_dm_opt_in = %s WHERE member_id = %s",
            (enabled, member_id),
        )
        return updated == 1

    # -- notifications ------------------------------------------------------
    def notifications_available(self) -> bool:
        """notifications 테이블이 공용 DB에 있는지 확인한다. 없으면 polling을 건너뛴다."""
        return self._db.table_exists("notifications")

    def claim_pending(self, limit: int, retry_delay_seconds: int) -> list[PendingNotification]:
        """처리할 PENDING 알림을 오래된 순으로 가져온다 (idx_notifications_pending 사용).

        실패한 적이 있는 알림은 마지막 시도 후 retry_delay_seconds가 지나야 다시 가져온다.
        행을 잠그거나 상태를 바꾸지 않는다. Bot은 한 프로세스로만 실행한다는 전제다.
        """
        return self._db.execute(
            """
            SELECT n.notification_id, n.notification_type, n.receiver_member_id,
                   n.actor_member_id, n.post_id, n.comment_id, n.retry_count,
                   m.discord_id AS receiver_discord_id,
                   m.external_dm_opt_in AS receiver_dm_opt_in,
                   p.title AS post_title,
                   ((n.post_id IS NOT NULL AND (p.post_id IS NULL OR p.deleted_at IS NOT NULL))
                    OR (n.comment_id IS NOT NULL AND (c.comment_id IS NULL OR c.deleted_at IS NOT NULL))
                   ) AS target_missing
              FROM notifications n
              JOIN members m ON m.member_id = n.receiver_member_id
              LEFT JOIN posts p ON p.post_id = n.post_id
              LEFT JOIN comments c ON c.comment_id = n.comment_id
             WHERE n.status = 'PENDING'
               AND (n.last_attempt_at IS NULL
                    OR n.last_attempt_at <= CURRENT_TIMESTAMP - make_interval(secs => %s))
             ORDER BY n.created_at, n.notification_id
             LIMIT %s
            """,
            (retry_delay_seconds, limit), fetch="all",
        )

    def mark_sent(self, notification_id: int) -> bool:
        return self._db.execute(
            """
            UPDATE notifications
               SET status = 'SENT', sent_at = CURRENT_TIMESTAMP,
                   last_attempt_at = CURRENT_TIMESTAMP, error_message = NULL
             WHERE notification_id = %s AND status = 'PENDING'
            """,
            (notification_id,),
        ) == 1

    def mark_skipped(self, notification_id: int, reason: str) -> bool:
        return self._db.execute(
            """
            UPDATE notifications
               SET status = 'SKIPPED', error_message = %s, last_attempt_at = CURRENT_TIMESTAMP
             WHERE notification_id = %s AND status = 'PENDING'
            """,
            (reason[:ERROR_MESSAGE_LIMIT], notification_id),
        ) == 1

    def record_failure(self, notification_id: int, error: str, max_attempts: int) -> str | None:
        """DM 전송 실패를 기록하고 새 상태(PENDING / FAILED)를 돌려준다. 대상 행이 없으면 None.

        SET 오른쪽의 retry_count는 갱신 전 값이므로 retry_count + 1이 이번 실패까지의 시도 횟수다.
        """
        row = self._db.execute(
            """
            UPDATE notifications
               SET retry_count = retry_count + 1,
                   last_attempt_at = CURRENT_TIMESTAMP,
                   error_message = %s,
                   status = CASE WHEN retry_count + 1 >= %s THEN 'FAILED' ELSE 'PENDING' END
             WHERE notification_id = %s AND status = 'PENDING'
            RETURNING status
            """,
            (error[:ERROR_MESSAGE_LIMIT], max_attempts, notification_id),
            fetch="one", write=True,
        )
        return row["status"] if row else None
