"""취업게시판 신규 글 자동 공지 저장소 (career_discord_announcements, database/sql/013).

대상: 취준 도감(reviews)·커리어 연구소(lab) 글 중 공개(post_status='PUBLISHED')이고 삭제되지 않은 글.
공지 이력이 없거나 FAILED(재시도 한도 미만)인 글을 작성 순서(created_at, post_id)로 고른다.
BASELINE(013 적용 시점의 기존 글), PENDING, SENT는 다시 고르지 않는다.

여러 Bot 프로세스가 동시에 실행되어도:
  - 한 글은 post_id 기본키 + 'FAILED일 때만 갱신' 조건으로 한 곳만 선점한다.
  - 하루 최대 공지 수는 advisory lock을 잡은 한 트랜잭션 안에서 집계·선점하므로 넘지 않는다.
"""
from datetime import date
from typing import Any, Protocol

from repositories.db import Database

ERROR_MESSAGE_LIMIT = 500
# pg_advisory_xact_lock 키 (취업 자동 공지 선점 전용)
CLAIM_LOCK_KEY = 610_018_001
# 결과가 이 시간 넘게 저장되지 않은 PENDING은 확인이 필요하다고 로그를 남긴다.
STUCK_PENDING_MINUTES = 30


class CareerNoticeRepository(Protocol):
    def available(self) -> bool: ...
    def claim_due(self, announce_date: date, daily_limit: int, max_attempts: int,
                  categories: tuple[str, ...]) -> list[dict[str, Any]]: ...
    def mark_sent(self, post_id: int, channel_id: int, message_id: int) -> bool: ...
    def mark_failed(self, post_id: int, error: str) -> bool: ...
    def count_stuck_pending(self) -> int: ...


class PostgresCareerNoticeRepository:
    def __init__(self, database: Database):
        self._db = database

    def available(self) -> bool:
        """013 마이그레이션이 적용되었는지 확인한다. 없으면 공지하지 않는다."""
        return self._db.table_exists("career_discord_announcements")

    def claim_due(self, announce_date: date, daily_limit: int, max_attempts: int,
                  categories: tuple[str, ...]) -> list[dict[str, Any]]:
        """오늘 남은 공지 수만큼 오래된 신규 글을 PENDING으로 선점하고 돌려준다 (한 트랜잭션)."""

        def work(cur) -> list[dict[str, Any]]:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (CLAIM_LOCK_KEY,))
            cur.execute(
                """
                SELECT COUNT(*) AS used
                  FROM career_discord_announcements
                 WHERE announce_date = %s AND status IN ('PENDING', 'SENT')
                """,
                (announce_date,),
            )
            remaining = daily_limit - cur.fetchone()["used"]
            if remaining <= 0:
                return []
            cur.execute(
                """
                SELECT p.post_id, cp.category_code, p.title
                  FROM posts p
                  JOIN career_posts cp ON cp.post_id = p.post_id
                  LEFT JOIN career_discord_announcements a ON a.post_id = p.post_id
                 WHERE cp.category_code = ANY(%s)
                   AND p.post_type = 'CAREER'
                   AND p.post_status = 'PUBLISHED'
                   AND p.deleted_at IS NULL
                   AND (a.post_id IS NULL OR (a.status = 'FAILED' AND a.attempt_count < %s))
                 ORDER BY p.created_at, p.post_id
                 LIMIT %s
                """,
                (list(categories), max_attempts, remaining),
            )
            candidates = cur.fetchall()
            claimed = []
            for row in candidates:
                cur.execute(
                    """
                    INSERT INTO career_discord_announcements
                           (post_id, category_code, status, announce_date, attempt_count,
                            claimed_at, updated_at)
                    VALUES (%s, %s, 'PENDING', %s, 1,
                            CURRENT_TIMESTAMP AT TIME ZONE 'UTC', CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
                    ON CONFLICT (post_id) DO UPDATE
                       SET status = 'PENDING',
                           announce_date = EXCLUDED.announce_date,
                           attempt_count = career_discord_announcements.attempt_count + 1,
                           error_message = NULL,
                           claimed_at = EXCLUDED.claimed_at,
                           updated_at = EXCLUDED.updated_at
                     WHERE career_discord_announcements.status = 'FAILED'
                    RETURNING post_id
                    """,
                    (row["post_id"], row["category_code"], announce_date),
                )
                if cur.fetchone() is not None:
                    claimed.append(row)
            return claimed

        return self._db.transaction(work)

    def mark_sent(self, post_id: int, channel_id: int, message_id: int) -> bool:
        return self._db.execute(
            """
            UPDATE career_discord_announcements
               SET status = 'SENT', discord_channel_id = %s, discord_message_id = %s,
                   error_message = NULL,
                   sent_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC',
                   updated_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
             WHERE post_id = %s AND status = 'PENDING'
            """,
            (str(channel_id), str(message_id), post_id),
        ) == 1

    def mark_failed(self, post_id: int, error: str) -> bool:
        return self._db.execute(
            """
            UPDATE career_discord_announcements
               SET status = 'FAILED', error_message = %s,
                   updated_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
             WHERE post_id = %s AND status = 'PENDING'
            """,
            (error[:ERROR_MESSAGE_LIMIT], post_id),
        ) == 1

    def count_stuck_pending(self) -> int:
        """전송 결과가 저장되지 않은 오래된 PENDING 수. 중복 공지를 막기 위해 자동 재시도하지 않는다."""
        row = self._db.execute(
            """
            SELECT COUNT(*) AS stuck
              FROM career_discord_announcements
             WHERE status = 'PENDING'
               AND claimed_at < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC') - make_interval(mins => %s)
            """,
            (STUCK_PENDING_MINUTES,), fetch="one",
        )
        return int(row["stuck"]) if row else 0
