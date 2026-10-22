"""모임 상태 저장소: 메모리 구현(DB 없을 때)과 PostgreSQL 구현(recruit_discord_channels).

키는 Discord 카테고리 ID, 모임 식별자는 recruit_id다.
lifecycle/활동 상태는 목적별 조건부 연산으로만 바꾼다. 저장된 상태가 전제 조건과 같을 때만
적용되므로 오래된 snapshot이 더 새로운 상태를 덮어쓸 수 없다.
저장소 메서드는 동기 함수이며, 비동기 코드는 `call()`로 worker thread에서 실행한다.
"""
import asyncio
import threading
import time
from datetime import datetime
from typing import Any, Callable, Protocol

from config import (
    DB_LOCK_IDLE_IN_TRANSACTION_MS,
    DB_LOCK_TIMEOUT_MS,
    KST,
    SYNC_RETRY_AFTER_SECONDS,
    SYNC_STALE_PENDING_SECONDS,
)
from repositories.db import connect_from_env

Meeting = dict[str, Any]


async def call(method: Callable, *args):
    """동기 저장소 메서드를 worker thread에서 실행한다 (DB가 느려도 이벤트 루프가 멈추지 않게)."""
    return await asyncio.to_thread(method, *args)


class GuardRejected(Exception):
    """모임이 short로 바뀌었거나 삭제 처리되어 Discord 작업을 시작하지 않는다."""


class RegularLockUnavailable(Exception):
    """recruits 행 락을 제한 시간 안에 얻지 못했다 (다음 주기에 재시도)."""


class ProvisioningUnconfirmed(RuntimeError):
    """공간 ID 저장 결과를 확인할 수 없다.

    실제로는 저장됐을 수 있으므로 공간을 지우거나 다시 만들지 말고 MANUAL로 남긴다.
    """


class MeetingRepository(Protocol):
    def list_regular_meetings(self) -> list[tuple[int, Meeting]]: ...

    def get_regular_meeting(self, category_id: int) -> Meeting | None: ...

    def record_activity(self, category_id: int, now: datetime) -> bool: ...

    def record_warning(self, category_id: int, warned_at: datetime,
                       scheduled_at: datetime,
                       expected_last_activity: datetime | None) -> bool: ...

    def cancel_schedule(self, category_id: int) -> bool: ...

    def is_delete_due(self, category_id: int, now: datetime) -> bool: ...

    def regular_lock(self, recruit_id: int): ...

    def is_regular(self, recruit_id: int) -> bool: ...

    def mark_deleted(self, category_id: int, now: datetime) -> bool: ...


class InMemoryMeetingRepository:
    """DB 없이 실행할 때와 테스트용 메모리 저장소. 조건부 연산은 PostgreSQL 구현과 같은 의미다."""
    def __init__(
        self,
        regular_meetings: dict[int, Meeting] | None = None,
    ):
        self._regular_meetings = (
            regular_meetings if regular_meetings is not None else {}
        )

    def list_regular_meetings(self) -> list[tuple[int, Meeting]]:
        return list(self._regular_meetings.items())

    def get_regular_meeting(self, category_id: int) -> Meeting | None:
        return self._regular_meetings.get(category_id)

    # -- 조건부 lifecycle 연산 (PostgreSQL 구현과 같은 의미) -------
    def _live(self, category_id: int) -> Meeting | None:
        meeting = self._regular_meetings.get(category_id)
        if meeting is None or meeting.get("discord_deleted_at") is not None:
            return None
        return meeting

    def record_activity(self, category_id: int, now: datetime) -> bool:
        meeting = self._live(category_id)
        if meeting is None:
            return False
        last = meeting.get("last_activity_at")
        meeting["last_activity_at"] = now if last is None or now > last else last
        meeting["inactivity_warned_at"] = None
        meeting["scheduled_delete_at"] = None
        return True

    def record_warning(self, category_id, warned_at, scheduled_at, expected_last_activity) -> bool:
        meeting = self._live(category_id)
        if (meeting is None
                or meeting.get("inactivity_warned_at") is not None
                or meeting.get("scheduled_delete_at") is not None
                or meeting.get("last_activity_at") != expected_last_activity):
            return False
        meeting["inactivity_warned_at"] = warned_at
        meeting["scheduled_delete_at"] = scheduled_at
        return True

    @staticmethod
    def _active_after_warning(meeting: Meeting) -> bool:
        warned = meeting.get("inactivity_warned_at")
        last = meeting.get("last_activity_at")
        return warned is not None and last is not None and last > warned

    def cancel_schedule(self, category_id: int) -> bool:
        meeting = self._live(category_id)
        if (meeting is None or meeting.get("scheduled_delete_at") is None
                or not self._active_after_warning(meeting)):
            return False
        meeting["inactivity_warned_at"] = None
        meeting["scheduled_delete_at"] = None
        return True

    def is_delete_due(self, category_id: int, now: datetime) -> bool:
        meeting = self._live(category_id)
        scheduled = None if meeting is None else meeting.get("scheduled_delete_at")
        return not (meeting is None or scheduled is None or scheduled > now
                    or self._active_after_warning(meeting))

    def mark_deleted(self, category_id: int, now: datetime) -> bool:
        meeting = self._live(category_id)
        if meeting is None:
            return False
        meeting["discord_deleted_at"] = now
        return True

    def regular_lock(self, recruit_id: int):
        """메모리에는 row lock이 없어 "삭제되지 않은 모임인가"만 확인한다."""
        return _InMemoryRegularLock(self, recruit_id)

    def is_regular(self, recruit_id: int) -> bool:
        return self._manageable(recruit_id)

    def _manageable(self, recruit_id: int) -> bool:
        return any(m.get("recruit_id") == recruit_id and m.get("discord_deleted_at") is None
                   for m in self._regular_meetings.values())


class _InMemoryRegularLock:
    """메모리 저장소용 락 (InMemoryMeetingRepository.regular_lock)."""
    def __init__(self, repository, recruit_id: int):
        self._repository, self._recruit_id = repository, recruit_id

    async def __aenter__(self):
        if not self._repository._manageable(self._recruit_id):
            raise GuardRejected()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def mark_deleted(self, category_id: int, now: datetime, timeout_seconds=None) -> bool:
        return self._repository.mark_deleted(category_id, now)


# ---------------------------------------------------------------------------
# PostgreSQL 구현 (공용 PlayMate DB의 recruit_discord_channels 테이블)
# ---------------------------------------------------------------------------

# 테스트용 override 훅: recruit_id -> HOST의 Discord 사용자 ID (모르면 None).
# 운영에서는 넣지 않으며, 저장소가 recruit_members(role='HOST', status='JOINED')를 직접 조회한다.
HostResolver = Callable[[int], "int | None"]

PING_AFTER_IDLE_SECONDS = 30


def _to_int(value: Any) -> int | None:
    """varchar Discord ID를 정수로 바꾼다. 잘못된 값은 None (호출자가 그 행만 건너뛴다)."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _aware(value: datetime | None) -> datetime | None:
    """naive 시각에 KST를 붙인다."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=KST)
    return value


def _regular(alias: str) -> str:
    """regular 모임만 관리한다는 SQL 조건. short 모임이 어떤 경로로도 대상이 되지 않게 하는 공통 방어선."""
    return (f"EXISTS (SELECT 1 FROM recruits r WHERE r.recruit_id = {alias}.recruit_id"
            " AND r.recruit_mode = 'regular')")


def _host_discord_id_sql(recruit_ref: str) -> str:
    """모임 HOST의 discord_id를 고르는 서브쿼리 (JOINED, 개발용 -1 제외).

    Backend 정책상 HOST는 1명이지만, 여러 명이어도 member_id가 가장 작은 한 명으로 결정적으로 고른다.
    """
    return f"""(SELECT m.discord_id
                  FROM recruit_members rm
                  JOIN members m ON m.member_id = rm.member_id
                 WHERE rm.recruit_id = {recruit_ref}
                   AND rm.role = 'HOST' AND rm.status = 'JOINED'
                   AND m.member_id <> -1 AND m.discord_id IS NOT NULL
                 ORDER BY rm.member_id
                 LIMIT 1)"""


# discord_deleted_at은 살아 있는 regular 모임에만 기록한다. 일반 저장소 메서드와
# 락 트랜잭션 안의 기록이 같은 SQL을 쓰도록 한 곳에 둔다.
_MARK_DELETED_SQL = f"""
    UPDATE recruit_discord_channels rc
       SET discord_deleted_at = %s, updated_at = now()
     WHERE rc.discord_category_id = %s AND rc.sync_status = 'SUCCESS'
       AND rc.discord_deleted_at IS NULL AND {_regular('rc')}
"""


class PostgresMeetingRepository:
    """MeetingRepository 구현 + 생성(provisioning)/참여자 조회 (공용 PostgreSQL).

    Discord ID는 varchar(32)라 쓰고 비교할 때는 str, discord.py에 넘길 때만 int로 바꾼다.
    읽기는 연결이 끊기면 한 번 재시도하고, 쓰기는 재시도하지 않는다 (응답만 유실되고
    실제로는 commit되었을 수 있기 때문). 오래 쉰 연결은 먼저 ping해 첫 쓰기 실패를 줄인다.
    recruits.discord_channel_id / discord_channel_status(예전 컬럼)는 읽지도 쓰지도 않는다.
    """

    _LIFECYCLE_SELECT = f"""
        SELECT rc.recruit_id, rc.discord_category_id, rc.discord_text_channel_id,
               rc.discord_voice_channel_id, rc.last_activity_at,
               rc.inactivity_warned_at, rc.scheduled_delete_at,
               rc.discord_deleted_at,
               {_host_discord_id_sql('rc.recruit_id')} AS host_discord_id
          FROM recruit_discord_channels rc
         WHERE rc.sync_status = 'SUCCESS'
           AND rc.discord_deleted_at IS NULL
           AND rc.discord_category_id IS NOT NULL
           AND {_regular('rc')}
    """

    def __init__(self, connect: Callable[[], Any], host_resolver: HostResolver | None = None):
        self._connect = connect
        self._host_resolver = host_resolver
        self._conn = None
        self._last_used = 0.0
        self._lock = threading.RLock()
        # 관리 중인 카테고리 ID 집합. 메시지 핸들러가 관리 대상이 아닌 카테고리의 메시지마다
        # DB를 조회하지 않게 한다. None이면 아직 읽지 않은 상태(필터 없음).
        self._known_categories: set[int] | None = None

    @classmethod
    def from_env(cls, host_resolver: HostResolver | None = None):
        """환경변수(DB_*)로 저장소를 만든다. 실제 연결은 첫 쿼리 때 연다."""
        return cls(connect_from_env, host_resolver)

    # -- 연결 ---------------------------------------------------------
    def _connection(self):
        """공유 연결을 돌려준다. PING_AFTER_IDLE_SECONDS 넘게 쉰 연결은 `SELECT 1`로 확인한다."""
        import psycopg

        if self._conn is not None and self._conn.closed:
            self._conn = None
        if self._conn is not None and time.monotonic() - self._last_used > PING_AFTER_IDLE_SECONDS:
            try:
                with self._conn.cursor() as cur:
                    cur.execute("SELECT 1")
            except psycopg.Error:
                self._reset_connection()
        if self._conn is None:
            self._conn = self._connect()
        return self._conn

    def _reset_connection(self) -> None:
        """공유 연결을 버린다 (다음 사용 때 새로 연결)."""
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        self._conn = None

    def _execute(self, sql: str, params: tuple = (), *, fetch: str | None = None):
        """SQL 한 개를 실행한다 (스레드 안전).

        fetch=None: 쓰기, 영향 받은 행 수. 재시도하지 않는다 (이미 commit되었을 수 있음).
        fetch="one"/"all": 읽기. 연결이 끊기면 다시 열고 한 번 재시도한다.
        """
        import psycopg

        attempts = 1 if fetch is None else 2
        with self._lock:
            for attempt in range(1, attempts + 1):
                try:
                    conn = self._connection()
                    with conn.cursor() as cur:
                        cur.execute(sql, params)
                        rowcount = cur.rowcount
                        names = [d.name for d in cur.description] if cur.description else []
                        rows = cur.fetchall() if fetch and cur.description else []
                    self._last_used = time.monotonic()
                    if fetch is None:
                        return rowcount
                    dicts = [dict(zip(names, row)) for row in rows]
                    if fetch == "one":
                        return dicts[0] if dicts else None
                    return dicts
                except psycopg.OperationalError:
                    self._reset_connection()
                    if attempt == attempts:
                        raise

    # -- MeetingRepository 구현 (lifecycle / 활동) --------------------------
    def get_host_discord_id(self, recruit_id: int) -> int | None:
        """모임 HOST의 Discord ID. host_resolver(테스트용)가 있으면 그것을, 없으면 DB를 조회한다."""
        if self._host_resolver is not None:
            return self._host_resolver(recruit_id)
        row = self._execute(
            f"SELECT {_host_discord_id_sql('%s')} AS host_discord_id", (recruit_id,), fetch="one",
        )
        return _to_int(row["host_discord_id"]) if row else None

    def refresh_known_categories(self) -> None:
        """관리 중인 카테고리 ID 집합을 다시 읽는다."""
        self._known_categories = {c for c, _ in self.list_regular_meetings()}

    def _to_meeting(self, row: dict) -> Meeting:
        """DB 행을 lifecycle이 쓰는 dict로 바꾼다 (ID는 int, 시각은 KST, HOST는 같은 조회 결과)."""
        if self._host_resolver is not None:
            host_id = self._host_resolver(row["recruit_id"])
        else:
            host_id = _to_int(row["host_discord_id"])
        return {
            "recruit_id": row["recruit_id"],
            "host_id": host_id,
            "text_channel_id": _to_int(row["discord_text_channel_id"]),
            "voice_channel_id": _to_int(row["discord_voice_channel_id"]),
            "last_activity_at": _aware(row["last_activity_at"]),
            "inactivity_warned_at": _aware(row["inactivity_warned_at"]),
            "scheduled_delete_at": _aware(row["scheduled_delete_at"]),
            "discord_deleted_at": _aware(row["discord_deleted_at"]),
        }

    def list_regular_meetings(self) -> list[tuple[int, Meeting]]:
        """관리 중인 regular 모임을 (카테고리 ID, 상태) 목록으로. 잘못된 카테고리 ID 행은 건너뛴다."""
        rows = self._execute(self._LIFECYCLE_SELECT, fetch="all")
        meetings = []
        for row in rows:
            category_id = _to_int(row["discord_category_id"])
            if category_id is None:
                print(f"잘못된 discord_category_id 건너뜀: recruit_id={row['recruit_id']}")
                continue
            meetings.append((category_id, self._to_meeting(row)))
        return meetings

    def get_regular_meeting(self, category_id: int) -> Meeting | None:
        """카테고리 ID로 관리 중인 모임을 읽는다. 알려진 카테고리가 아니면 DB를 조회하지 않는다."""
        if self._known_categories is not None and category_id not in self._known_categories:
            return None
        row = self._execute(
            self._LIFECYCLE_SELECT + " AND rc.discord_category_id = %s",
            (str(category_id),), fetch="one",
        )
        return self._to_meeting(row) if row else None

    # -- 조건부 lifecycle 연산 ---------------------------------------
    _LIVE = ("rc.discord_category_id = %s AND rc.sync_status = 'SUCCESS' "
             "AND rc.discord_deleted_at IS NULL")

    def record_activity(self, category_id: int, now: datetime) -> bool:
        """활동을 기록하고 경고/삭제 예약을 취소한다. 활동이 항상 우선하며 시각은 뒤로 가지 않는다."""
        return bool(self._execute(
            f"""
            UPDATE recruit_discord_channels rc
               SET last_activity_at = GREATEST(rc.last_activity_at, %s),
                   inactivity_warned_at = NULL, scheduled_delete_at = NULL,
                   updated_at = now()
             WHERE {self._LIVE} AND {_regular('rc')}
            """,
            (now, str(category_id)),
        ))

    def record_warning(self, category_id: int, warned_at: datetime,
                       scheduled_at: datetime,
                       expected_last_activity: datetime | None) -> bool:
        """경고/삭제 예약을 저장한다.

        읽어 둔 상태 그대로일 때만 저장하므로, DM을 보내는 동안 새 활동이 있었다면
        오래된 경고가 그 활동을 덮어쓰지 못한다.
        """
        return bool(self._execute(
            f"""
            UPDATE recruit_discord_channels rc
               SET inactivity_warned_at = %s, scheduled_delete_at = %s, updated_at = now()
             WHERE {self._LIVE} AND {_regular('rc')}
               AND rc.inactivity_warned_at IS NULL AND rc.scheduled_delete_at IS NULL
               AND rc.last_activity_at IS NOT DISTINCT FROM %s
            """,
            (warned_at, scheduled_at, str(category_id), expected_last_activity),
        ))

    def cancel_schedule(self, category_id: int) -> bool:
        """경고 이후 활동이 있었던 모임의 경고/삭제 예약을 취소한다. 취소했으면 True."""
        return bool(self._execute(
            f"""
            UPDATE recruit_discord_channels rc
               SET inactivity_warned_at = NULL, scheduled_delete_at = NULL, updated_at = now()
             WHERE {self._LIVE} AND {_regular('rc')}
               AND rc.scheduled_delete_at IS NOT NULL
               AND rc.inactivity_warned_at IS NOT NULL
               AND rc.last_activity_at > rc.inactivity_warned_at
            """,
            (str(category_id),),
        ))

    def is_delete_due(self, category_id: int, now: datetime) -> bool:
        """예약 시각이 지났고 경고 이후 활동이 없는지 읽기 전용으로 확인한다.

        아무것도 쓰지 않는다. 삭제 기록은 Discord에서 삭제가 확인된 뒤 mark_deleted로만 남긴다.
        """
        row = self._execute(
            f"""
            SELECT 1 AS due
              FROM recruit_discord_channels rc
             WHERE {self._LIVE} AND {_regular('rc')}
               AND rc.scheduled_delete_at IS NOT NULL AND rc.scheduled_delete_at <= %s
               AND NOT (rc.inactivity_warned_at IS NOT NULL
                        AND rc.last_activity_at > rc.inactivity_warned_at)
            """,
            (str(category_id), now), fetch="one",
        )
        return row is not None

    def mark_deleted(self, category_id: int, now: datetime) -> bool:
        """Discord 공간이 없어졌음을 기록한다 (멱등, regular 모임만, 0행이면 대상 아님).

        공유 autocommit 연결에서 바로 commit된다. lifecycle 삭제 경로는 이것을 쓰지 말고
        락 트랜잭션 안의 `regular_lock(...).mark_deleted`를 써야 한다.
        """
        return bool(self._execute(_MARK_DELETED_SQL, (now, str(category_id))))

    lock_timeout_ms = DB_LOCK_TIMEOUT_MS

    def regular_lock(self, recruit_id: int):
        """Discord 작업과 모임 모드 변경을 직렬화하는 비동기 context manager.

        전용 연결의 트랜잭션에서 살아 있는 regular 모임의 recruits 행을 FOR SHARE로 잠그고
        블록이 끝날 때까지 유지한다 (정상 종료 COMMIT, 오류 ROLLBACK). Backend의 short 변경은
        그동안 대기하고, 이미 short로 commit되었다면 GuardRejected로 Discord 호출이 시작되지 않는다.
        락 대기가 길어지면 RegularLockUnavailable.
        """
        return _PostgresRegularLock(self, recruit_id)

    def is_regular(self, recruit_id: int) -> bool:
        """모임이 지금도 regular인지 확인한다."""
        return self._execute(
            "SELECT 1 AS ok FROM recruits WHERE recruit_id = %s AND recruit_mode = 'regular'",
            (recruit_id,), fetch="one",
        ) is not None

    # -- 생성(provisioning): regular 모임 -> Discord 공간 ---------------------
    _CLAIMABLE_RECRUIT = """
        EXISTS (SELECT 1 FROM recruits r JOIN posts p ON p.post_id = r.post_id
                 WHERE r.recruit_id = %s AND r.recruit_mode = 'regular'
                   AND p.post_status IS DISTINCT FROM 'DELETED')
    """

    _RETRYABLE = """
        rc.sync_status = 'FAILED'
        AND rc.discord_category_id IS NULL
        AND COALESCE(rc.sync_error, '') NOT LIKE 'MANUAL:%%'
        AND COALESCE(rc.sync_error, '') NOT LIKE 'ABORTED:%%'
        AND rc.updated_at < now() - make_interval(secs => %s)
    """

    def list_provisionable_recruits(self) -> list[dict]:
        """공간을 새로 만들 regular 모임 (행이 없거나 재시도 가능한 FAILED). recruits.state는 보지 않는다."""
        return self._execute(
            f"""
            SELECT r.recruit_id, p.title
              FROM recruits r
              JOIN posts p ON p.post_id = r.post_id
              LEFT JOIN recruit_discord_channels rc ON rc.recruit_id = r.recruit_id
             WHERE r.recruit_mode = 'regular'
               AND p.post_status IS DISTINCT FROM 'DELETED'
               AND (rc.recruit_id IS NULL OR ({self._RETRYABLE}))
             ORDER BY r.recruit_id
            """,
            (SYNC_RETRY_AFTER_SECONDS,), fetch="all",
        )

    def claim_provisioning(self, recruit_id: int) -> bool:
        """생성 권한을 PENDING 행으로 선점한다 (선점한 한 곳만 True). 공간 중복 생성을 막는다.

        regular·미삭제 여부를 같은 SQL에서 다시 확인하므로, 조회 뒤 short로 바뀐 모임은 선점되지 않는다.
        """
        if self._execute(
            f"""
            INSERT INTO recruit_discord_channels
                   (recruit_id, sync_status, created_at, updated_at)
            SELECT %s, 'PENDING', now(), now()
             WHERE {self._CLAIMABLE_RECRUIT}
            ON CONFLICT (recruit_id) DO NOTHING
            """,
            (recruit_id, recruit_id),
        ):
            return True
        return bool(self._execute(
            f"""
            UPDATE recruit_discord_channels rc
               SET sync_status = 'PENDING', sync_error = NULL, updated_at = now()
             WHERE rc.recruit_id = %s AND {self._RETRYABLE}
               AND {self._CLAIMABLE_RECRUIT}
            """,
            (recruit_id, SYNC_RETRY_AFTER_SECONDS, recruit_id),
        ))

    def complete_provisioning(self, recruit_id: int, category_id: int,
                              text_channel_id: int, voice_channel_id: int | None,
                              now: datetime) -> None:
        """공간 ID를 저장하고 SUCCESS로 확정한다 (응답 유실을 견딘다).

        정상 반환: 저장됨. ProvisioningUnconfirmed: 결과 불명 (공간을 지우지 말고 MANUAL).
        그 밖의 예외: 확실히 저장 안 됨 (호출자가 공간 정리).
        last_activity_at을 생성 시각으로 두어, 아무도 채팅하지 않는 모임도 30일 정책 대상이 된다.
        """
        import psycopg

        ids = (str(category_id), str(text_channel_id),
               None if voice_channel_id is None else str(voice_channel_id))
        try:
            updated = self._complete_atomically(
                """
                UPDATE recruit_discord_channels
                   SET discord_category_id = %s, discord_text_channel_id = %s,
                       discord_voice_channel_id = %s, sync_status = 'SUCCESS',
                       sync_error = NULL, synced_at = %s, last_activity_at = %s,
                       updated_at = now()
                 WHERE recruit_id = %s AND sync_status = 'PENDING'
                """,
                (*ids, now, now, recruit_id),
                recruit_id,
            )
        except psycopg.OperationalError:
            updated = None  # may have committed with the response lost
        if not updated:
            self._verify_provisioned(recruit_id, ids)
        if self._known_categories is not None:
            self._known_categories.add(category_id)

    def _complete_atomically(self, sql: str, params: tuple, recruit_id: int) -> int:
        """recruits 행을 FOR SHARE로 잠그고 regular일 때만 SUCCESS를 확정한다 (한 트랜잭션).

        Backend의 short 변경이 진행 중이면 기다리고, 먼저 commit되었다면 0행으로 거부해서
        short 모임이 SUCCESS로 남지 않게 한다. 필요 권한: recruits SELECT ... FOR SHARE.
        """
        import psycopg

        with self._lock:
            try:
                conn = self._connection()
                with conn.transaction():
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT 1 FROM recruits WHERE recruit_id = %s"
                            " AND recruit_mode = 'regular' FOR SHARE",
                            (recruit_id,),
                        )
                        if cur.fetchone() is None:
                            return 0
                        cur.execute(sql, params)
                        updated = cur.rowcount
                self._last_used = time.monotonic()
                return updated
            except psycopg.OperationalError:
                self._reset_connection()
                raise

    def _verify_provisioned(self, recruit_id: int, ids: tuple) -> None:
        """결과가 불명확할 때 다시 읽어 SUCCESS + 같은 세 ID인지 확인한다. 아니면 ProvisioningUnconfirmed."""
        try:
            row = self._execute(
                """
                SELECT sync_status, discord_category_id, discord_text_channel_id,
                       discord_voice_channel_id
                  FROM recruit_discord_channels WHERE recruit_id = %s
                """,
                (recruit_id,), fetch="one",
            )
        except Exception as error:
            raise ProvisioningUnconfirmed(f"저장 결과 조회 실패: {error!r}") from error
        stored = None if row is None else (
            row["discord_category_id"], row["discord_text_channel_id"],
            row["discord_voice_channel_id"])
        if row is None or row["sync_status"] != "SUCCESS" or stored != ids:
            raise ProvisioningUnconfirmed(
                f"저장 상태 불일치: recruit_id={recruit_id} "
                f"status={None if row is None else row['sync_status']}")

    def fail_provisioning(self, recruit_id: int, error: str) -> None:
        """PENDING 행을 FAILED로 바꾼다. 'MANUAL:'/'ABORTED:' 사유는 자동 재시도하지 않는다."""
        self._execute(
            """
            UPDATE recruit_discord_channels
               SET sync_status = 'FAILED', sync_error = %s, updated_at = now()
             WHERE recruit_id = %s AND sync_status = 'PENDING'
            """,
            (error[:1000], recruit_id),
        )

    def fail_stale_pending(self) -> int:
        """오래된 PENDING을 'MANUAL:'로 바꾼다. 생성 중 중단되어 고아 공간이 있을 수 있어 사람이 확인한다."""
        return self._execute(
            """
            UPDATE recruit_discord_channels
               SET sync_status = 'FAILED', updated_at = now(),
                   sync_error = 'MANUAL: 생성 중 중단됨. Discord 고아 채널 확인 필요'
             WHERE sync_status = 'PENDING' AND discord_category_id IS NULL
               AND updated_at < now() - make_interval(secs => %s)
            """,
            (SYNC_STALE_PENDING_SECONDS,),
        )

    # -- 참여자 -------------------------------------------------------
    def list_participant_states(self) -> list[dict]:
        """살아 있는 regular 모임의 JOINED/CANCELED 참여자 상태.

        제외: member_id=-1(개발용), 쓸 수 없는 discord_id, role='HOST' (HOST 권한을 덮어쓰지 않도록).
        """
        rows = self._execute(
            f"""
            SELECT rc.recruit_id, rc.discord_category_id, rc.discord_text_channel_id,
                   rc.discord_voice_channel_id, rm.status, m.discord_id
              FROM recruit_discord_channels rc
              JOIN recruit_members rm ON rm.recruit_id = rc.recruit_id
              JOIN members m ON m.member_id = rm.member_id
             WHERE rc.sync_status = 'SUCCESS'
               AND rc.discord_deleted_at IS NULL
               AND rc.discord_category_id IS NOT NULL
               AND {_regular('rc')}
               AND m.member_id <> -1
               AND m.discord_id IS NOT NULL
               AND COALESCE(rm.role, '') <> 'HOST'
               AND rm.status IN ('JOINED', 'CANCELED')
            """,
            fetch="all",
        )
        states = []
        for row in rows:
            discord_id = _to_int(row["discord_id"])
            category_id = _to_int(row["discord_category_id"])
            if discord_id is not None and category_id is not None:
                states.append({**row, "discord_id": discord_id,
                               "discord_category_id": category_id,
                               "text_channel_id": _to_int(row["discord_text_channel_id"]),
                               "voice_channel_id": _to_int(row["discord_voice_channel_id"])})
        return states

    def list_joined_discord_ids(self, recruit_id: int) -> list[int]:
        """한 regular 모임의 JOINED 참여자 Discord ID (공간 생성 때 사용)."""
        rows = self._execute(
            """
            SELECT m.discord_id
              FROM recruit_members rm
              JOIN members m ON m.member_id = rm.member_id
              JOIN recruits r ON r.recruit_id = rm.recruit_id
             WHERE rm.recruit_id = %s AND rm.status = 'JOINED'
               AND r.recruit_mode = 'regular'
               AND m.member_id <> -1 AND m.discord_id IS NOT NULL
               AND COALESCE(rm.role, '') <> 'HOST'
            """,
            (recruit_id,), fetch="all",
        )
        return [i for i in (_to_int(r["discord_id"]) for r in rows) if i is not None]


class _PostgresRegularLock:
    """`PostgresMeetingRepository.regular_lock`의 구현. 사용 한 번마다 DB 연결 하나를 전용으로 쓴다.

    세션(연결 + 트랜잭션 + 행 락)의 소유권은 `_state` 락 아래에서 두 당사자 중 한쪽에만 넘어가므로
    세션은 정확히 한 번만 해제된다.

    - 정상 경로: worker가 락 획득을 끝내고 세션을 "소유됨"으로 표시하면, context manager의
      `__aexit__`가 해제한다.
    - 획득 중에 호출자가 취소된 경우: 호출자가 "포기(abandoned)" 표시를 한다. 나중에 락을 얻은
      worker는 표시를 보고 스스로 ROLLBACK/close 하며 세션을 아무에게도 넘기지 않는다.
      worker가 이미 끝났다면 호출자가 해제한다. (취소된 코루틴이 받지 못한 락이 남아
      Backend의 UPDATE를 막는 일을 없애기 위한 구조다.)

    mark_deleted는 이 세션의 같은 트랜잭션에서 실행되고, `async with` 블록이 오류 없이 끝날 때만
    COMMIT된다. timeout, 취소, 오류가 나면 진행 중인 SQL을 서버에서 취소(cancel_safe)하고,
    worker thread가 그 SQL을 실제로 끝낸 것을 확인한 뒤에야 ROLLBACK/close 한다.
    그래서 락을 기다리던 UPDATE가 나중에 살아나 뒤늦게 COMMIT되는 일이 없다.
    """

    def __init__(self, repository: PostgresMeetingRepository, recruit_id: int):
        self._repository, self._recruit_id = repository, recruit_id
        self._state = threading.Lock()
        self._release_lock = threading.Lock()
        self._abandoned = False
        self._owned = False
        self._released = False
        self._closing = False
        self._stmt_running = False
        self._stmt_idle = threading.Event()
        self._stmt_idle.set()
        self._conn = None
        self._tx = None

    async def __aenter__(self):
        """worker thread에서 락 획득을 시작하고 결과를 기다린다.

        기다리는 도중 취소되면 `_abandon()`으로 세션 정리 책임을 넘기고 취소를 그대로 전파한다.
        (asyncio.shield: 취소가 worker의 획득 자체를 중간에 끊지 않게 하고, 결과는 worker가 정리한다.)
        """
        acquiring = asyncio.get_running_loop().run_in_executor(None, self._acquire)
        # 호출자가 취소된 뒤 worker가 실패해도 "예외를 가져가지 않음" 경고가 뜨지 않게 한다.
        acquiring.add_done_callback(lambda f: f.cancelled() or f.exception())
        try:
            await asyncio.shield(acquiring)
        except asyncio.CancelledError:
            self._abandon()
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """블록이 끝났을 때 세션을 정리한다. 오류 없이 끝났으면 COMMIT, 아니면 ROLLBACK.

        shield로 감싸서, 이미 취소된 작업에서도 정리가 끝까지 실행되게 한다. 서버의
        idle_in_transaction 타임아웃은 정상 해제 경로가 아니라 마지막 안전망일 뿐이다.
        """
        await asyncio.shield(asyncio.to_thread(self._finalize, exc_type is None))
        return False

    async def mark_deleted(self, category_id: int, now: datetime, timeout_seconds=None) -> bool:
        """discord_deleted_at을 이 락의 트랜잭션 안에서 기록한다 (락과 함께 COMMIT됨). 기록했으면 True.

        timeout_seconds는 호출자의 남은 시간 예산이며, 서버 `SET LOCAL statement_timeout`으로 적용해
        이 SQL이 예산보다 오래 걸리지 않게 한다 (최소 1초). SQL은 worker thread에서 실행하며,
        호출자가 취소되면 진행 중인 SQL을 서버에서 취소한 뒤 취소를 전파한다.
        0행이면 모임이 regular가 아니거나 이미 기록된 것이다.
        """
        if self._conn is None:
            raise RuntimeError("lock session is not open")
        timeout_ms = None if timeout_seconds is None else max(1000, int(timeout_seconds * 1000))
        running = asyncio.get_running_loop().run_in_executor(
            None, self._run_write, _MARK_DELETED_SQL, (now, str(category_id)), timeout_ms)
        running.add_done_callback(lambda f: f.cancelled() or f.exception())
        try:
            return bool(await asyncio.shield(running))
        except asyncio.CancelledError:
            self._cancel_statement()
            raise

    def _run_write(self, sql: str, params: tuple, statement_timeout_ms) -> int:
        """worker thread에서 쓰기 SQL 한 개를 실행하고 영향 받은 행 수를 돌려준다.

        세션이 이미 정리 중이면 실행하지 않고 오류를 올린다. 실행 중임을 표시해 두어서
        `_finalize`가 이 SQL을 취소하고 끝나기를 기다릴 수 있게 한다.
        """
        with self._state:
            if self._closing or self._released:
                raise RuntimeError("lock session already closed")
            self._stmt_running = True
            self._stmt_idle.clear()
        try:
            with self._conn.cursor() as cur:
                if statement_timeout_ms:
                    cur.execute(f"SET LOCAL statement_timeout = {int(statement_timeout_ms)}")
                cur.execute(sql, params)
                return cur.rowcount
        finally:
            with self._state:
                self._stmt_running = False
                self._stmt_idle.set()

    def _cancel_statement(self) -> None:
        """세션에서 실행 중인 SQL이 있으면 서버에 취소를 요청한다 (best-effort).

        요청이 실패해도 서버 statement_timeout과 ROLLBACK이 뒤에서 막아 준다.
        """
        with self._state:
            running = self._stmt_running
            conn = self._conn
        if running and conn is not None:
            try:
                (getattr(conn, "cancel_safe", None) or conn.cancel)()
            except Exception:
                pass

    def _finalize(self, commit: bool) -> None:
        """세션을 종료한다. worker thread가 연결에서 SQL을 실행 중일 때는 연결을 건드리지 않는다.

        순서: 새 SQL 실행 금지 표시 -> (롤백이면) 실행 중 SQL 취소 요청 -> worker가 끝나기를 대기
        -> COMMIT 또는 ROLLBACK 후 연결 close. 같은 연결을 두 곳에서 동시에 쓰지 않는 것이 목적이다.
        """
        with self._state:
            self._closing = True  # a worker that has not started yet will refuse to run
        if not commit:
            self._cancel_statement()
        # worker thread가 SQL을 실제로 끝낼 때까지 연결의 소유권은 여기에 있다.
        self._stmt_idle.wait(timeout=30)
        self._finish(commit)

    def _abandon(self) -> None:
        """락을 얻는 중 호출자가 취소되었을 때 세션이 반드시 정리되게 한다.

        포기 표시를 남기고, worker가 이미 획득을 끝내 소유권을 넘긴 상태라면 여기서 ROLLBACK/close 한다.
        아직 획득 전이라면 worker가 나중에 표시를 보고 스스로 정리한다.
        """
        with self._state:
            self._abandoned = True
            owned = self._owned
        if owned:  # the worker already finished and handed the session over to us
            self._finish(False)

    def _acquire(self) -> None:
        """worker thread에서 전용 연결을 열고 recruits 행에 FOR SHARE 락을 잡는다.

        순서: 연결/트랜잭션 시작 -> lock_timeout, idle_in_transaction 타임아웃 설정 ->
        regular이고 Discord 공간이 살아 있는 모임의 행을 FOR SHARE로 잠금.
        모임이 조건에 맞지 않으면 GuardRejected, 락 대기 초과면 RegularLockUnavailable을 올린다.
        락을 얻은 직후 `_state` 아래에서 "호출자가 그 사이 포기했는가"를 확인해, 포기했다면 즉시
        ROLLBACK/close 하고 세션을 아무에게도 넘기지 않는다.
        """
        import psycopg

        with self._state:
            if self._abandoned:  # cancelled before the worker even started
                return
        conn = self._repository._connect()
        self._conn = conn
        try:
            self._tx = conn.transaction()
            self._tx.__enter__()
            with conn.cursor() as cur:
                cur.execute(f"SET LOCAL lock_timeout = {int(self._repository.lock_timeout_ms)}")
                cur.execute(
                    "SET LOCAL idle_in_transaction_session_timeout = "
                    f"{int(DB_LOCK_IDLE_IN_TRANSACTION_MS)}"
                )
                cur.execute(
                    """
                    SELECT 1 FROM recruits r
                     WHERE r.recruit_id = %s AND r.recruit_mode = 'regular'
                       AND EXISTS (SELECT 1 FROM recruit_discord_channels rc
                                    WHERE rc.recruit_id = r.recruit_id
                                      AND rc.sync_status = 'SUCCESS'
                                      AND rc.discord_deleted_at IS NULL)
                       FOR SHARE OF r
                    """,
                    (self._recruit_id,),
                )
                row = cur.fetchone()
            if row is None:
                raise GuardRejected()
        except psycopg.errors.LockNotAvailable as error:
            self._finish(False)
            raise RegularLockUnavailable() from error
        except BaseException:
            self._finish(False)
            raise
        # 락을 얻었다: 누가 해제할지(호출자 또는 worker 자신)를 원자적으로 정한다.
        with self._state:
            if self._abandoned:
                abandoned = True
            else:
                self._owned = True
                abandoned = False
        if abandoned:
            self._finish(False)  # nobody is waiting for this session any more

    def _finish(self, commit: bool) -> None:
        """트랜잭션을 끝내고 전용 연결을 닫는다 (여러 번 호출해도 한 번만 실행).

        COMMIT이 실패하면 그 예외를 호출자에게 올린다 (기록이 안 된 것을 모르고 지나가면 안 되므로).
        ROLLBACK이나 close 중 오류는 무시한다.
        """
        with self._release_lock:
            if self._released:
                return
            self._released = True
            commit_error = None
            try:
                if self._tx is not None:
                    if commit:
                        self._tx.__exit__(None, None, None)
                    else:
                        self._tx.__exit__(RuntimeError, RuntimeError("rollback"), None)
            except Exception as error:
                commit_error = error if commit else None
            finally:
                self._tx = None
                try:
                    if self._conn is not None:
                        self._conn.close()
                except Exception:
                    pass
                self._conn = None
            if commit_error is not None:
                raise commit_error  # the COMMIT did not complete: the caller must know
