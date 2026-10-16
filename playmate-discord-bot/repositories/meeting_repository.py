"""Storage boundary for meeting lifecycle state.

InMemoryMeetingRepository keeps the original in-memory fixtures (state is lost
when the process stops). PostgresMeetingRepository (below) is the persistent
implementation backed by the shared table recruit_discord_channels.
Keys are Discord category IDs; recruit_id remains the backend meeting identity.
Message content is never accepted here.

Lifecycle/activity state changes are purpose-specific *conditional* operations
(record_activity, record_warning, cancel_schedule, mark_deleted),
and the read-only is_delete_due. A stale snapshot can therefore never overwrite newer state:
each operation only applies if the stored state still matches its precondition.

Repository methods are synchronous; async callers go through `call()` so the
blocking DB work runs in a worker thread, not on the Discord event loop.
"""
import asyncio
import threading
import time
from datetime import datetime
from typing import Any, Callable, Protocol

from config import (
    DB_LOCK_IDLE_IN_TRANSACTION_MS,
    DB_LOCK_TIMEOUT_MS,
    DB_STATEMENT_TIMEOUT_MS,
    KST,
    SYNC_RETRY_AFTER_SECONDS,
    SYNC_STALE_PENDING_SECONDS,
)

Meeting = dict[str, Any]


async def call(method: Callable, *args):
    """Run a (blocking) repository method outside the event loop."""
    return await asyncio.to_thread(method, *args)


class GuardRejected(Exception):
    """The recruit is no longer an eligible regular meeting with a live Discord
    space (e.g. it became short); the Discord side effect must not run."""


class RegularLockUnavailable(Exception):
    """The recruits row lock could not be taken in time (a concurrent change is
    in progress); skip now and try again next cycle."""


class ProvisioningUnconfirmed(RuntimeError):
    """The DB outcome of saving a created Discord space could not be confirmed.

    The Discord space must NOT be deleted or re-created automatically.
    """


class MeetingRepository(Protocol):
    def list_regular_meetings(self) -> list[tuple[int, Meeting]]: ...

    def get_regular_meeting(self, category_id: int) -> Meeting | None: ...

    def save_regular_meeting(
        self, category_id: int, meeting: Meeting
    ) -> None: ...

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

    def save_regular_meeting(
        self, category_id: int, meeting: Meeting
    ) -> None:
        self._regular_meetings[category_id] = meeting

    # -- conditional lifecycle operations (same semantics as PostgreSQL) -------
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
        """No row lock exists in memory; only the eligibility check remains."""
        return _InMemoryRegularLock(self, recruit_id)

    def is_regular(self, recruit_id: int) -> bool:
        return self._manageable(recruit_id)

    def _manageable(self, recruit_id: int) -> bool:
        return any(m.get("recruit_id") == recruit_id and m.get("discord_deleted_at") is None
                   for m in self._regular_meetings.values())


class _InMemoryRegularLock:
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
# PostgreSQL implementation (shared PlayMate DB, table recruit_discord_channels)
# ---------------------------------------------------------------------------

# Optional hook: recruit_id -> HOST's Discord user id (or None).
# TODO: the backend does not store the creator as recruit_members.role='HOST'
# yet, so no resolver is wired. Agree on the contract with the backend owner.
HostResolver = Callable[[int], "int | None"]

PING_AFTER_IDLE_SECONDS = 30


def _to_int(value: Any) -> int | None:
    """DB varchar Discord id -> int for discord.py; None for NULL/invalid."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=KST)
    return value


def _regular(alias: str) -> str:
    """Policy guard: only recruit_mode='regular' is ever managed by the Bot."""
    return (f"EXISTS (SELECT 1 FROM recruits r WHERE r.recruit_id = {alias}.recruit_id"
            " AND r.recruit_mode = 'regular')")


# discord_deleted_at is only ever written for a live, regular meeting.
_MARK_DELETED_SQL = f"""
    UPDATE recruit_discord_channels rc
       SET discord_deleted_at = %s, updated_at = now()
     WHERE rc.discord_category_id = %s AND rc.sync_status = 'SUCCESS'
       AND rc.discord_deleted_at IS NULL AND {_regular('rc')}
"""


class PostgresMeetingRepository:
    """Implements MeetingRepository plus the provisioning/participant queries.

    NOTE: recruits.discord_channel_id / recruits.discord_channel_status look like
    legacy Discord columns. The Bot neither reads nor writes them;
    recruit_discord_channels is the single source of truth for Discord state.
    TODO: confirm whether anything uses them and tidy up via team discussion.

    DB contract: recruit_discord_channels stores Discord IDs as varchar(32).
    IDs are written and compared as str(...) and converted with int() only
    when read back for discord.py; NULL/non-numeric IDs are skipped, never fatal.

    Retry policy: reads are retried once after a connection loss. Writes are
    never blindly retried (a lost response can hide a committed change); an
    idle connection is pinged first so a stale socket does not fail a write.
    """

    _LIFECYCLE_SELECT = f"""
        SELECT rc.recruit_id, rc.discord_category_id, rc.discord_text_channel_id,
               rc.discord_voice_channel_id, rc.last_activity_at,
               rc.inactivity_warned_at, rc.scheduled_delete_at,
               rc.discord_deleted_at
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
        # Category ids of live Discord meetings; lets the message handler skip
        # the DB for chat in unrelated categories. None = not loaded yet.
        self._known_categories: set[int] | None = None

    @classmethod
    def from_env(cls, host_resolver: HostResolver | None = None):
        import psycopg
        import config

        def connect():
            return psycopg.connect(
                host=config.DB_HOST, port=int(config.DB_PORT), user=config.DB_USER,
                password=config.DB_PASSWORD, dbname=config.DB_NAME,
                sslmode=config.DB_SSLMODE, connect_timeout=10, autocommit=True,
                options=f"-c TimeZone=Asia/Seoul -c statement_timeout={config.DB_STATEMENT_TIMEOUT_MS}",
            )

        return cls(connect, host_resolver)

    # -- connection ---------------------------------------------------------
    def _connection(self):
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
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        self._conn = None

    def _execute(self, sql: str, params: tuple = (), *, fetch: str | None = None):
        """fetch None -> write (rowcount, never retried); "one"/"all" -> read (retried once)."""
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

    # -- MeetingRepository (lifecycle / activity) --------------------------
    def get_host_discord_id(self, recruit_id: int) -> int | None:
        if self._host_resolver is None:
            return None
        return self._host_resolver(recruit_id)

    def refresh_known_categories(self) -> None:
        self._known_categories = {c for c, _ in self.list_regular_meetings()}

    def _to_meeting(self, row: dict) -> Meeting:
        return {
            "recruit_id": row["recruit_id"],
            "host_id": self.get_host_discord_id(row["recruit_id"]),
            "text_channel_id": _to_int(row["discord_text_channel_id"]),
            "voice_channel_id": _to_int(row["discord_voice_channel_id"]),
            "last_activity_at": _aware(row["last_activity_at"]),
            "inactivity_warned_at": _aware(row["inactivity_warned_at"]),
            "scheduled_delete_at": _aware(row["scheduled_delete_at"]),
            "discord_deleted_at": _aware(row["discord_deleted_at"]),
        }

    def list_regular_meetings(self) -> list[tuple[int, Meeting]]:
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
        if self._known_categories is not None and category_id not in self._known_categories:
            return None
        row = self._execute(
            self._LIFECYCLE_SELECT + " AND rc.discord_category_id = %s",
            (str(category_id),), fetch="one",
        )
        return self._to_meeting(row) if row else None

    def save_regular_meeting(self, category_id: int, meeting: Meeting) -> None:
        """Whole-record save kept for the MeetingRepository protocol.

        Lifecycle and activity code does NOT use it (use the conditional
        operations below). last_activity_at still only moves forward.
        """
        self._execute(
            f"""
            UPDATE recruit_discord_channels rc
               SET last_activity_at = GREATEST(rc.last_activity_at, %s),
                   inactivity_warned_at = %s, scheduled_delete_at = %s,
                   discord_deleted_at = %s, updated_at = now()
             WHERE rc.discord_category_id = %s AND {_regular('rc')}
            """,
            (meeting.get("last_activity_at"), meeting.get("inactivity_warned_at"),
             meeting.get("scheduled_delete_at"), meeting.get("discord_deleted_at"),
             str(category_id)),
        )

    # -- conditional lifecycle operations ---------------------------------------
    _LIVE = ("rc.discord_category_id = %s AND rc.sync_status = 'SUCCESS' "
             "AND rc.discord_deleted_at IS NULL")

    def record_activity(self, category_id: int, now: datetime) -> bool:
        """Activity wins: stamp it and cancel any warning/deletion schedule."""
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
        """Store warning + schedule only if nothing changed since the snapshot."""
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
        """Read-only last check right before the Discord deletion: the schedule
        is due and no activity happened after the warning.

        Nothing is written here. discord_deleted_at is stored only by
        mark_deleted AFTER Discord confirmed the deletion, so a failed or
        unclear deletion never leaves a "deleted" state behind and activity
        recorded during the attempt is never rejected.
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
        """Record that the Discord space no longer exists (idempotent).

        The SQL itself only succeeds for a regular recruit; 0 rows means the
        meeting is not (or no longer) a live regular one, or was already marked.

        This commits on the shared autocommit connection immediately. The
        lifecycle DELETE path must NOT use it: there the record is written with
        `regular_lock(...).mark_deleted`, inside the lock's own transaction.
        """
        return bool(self._execute(_MARK_DELETED_SQL, (now, str(category_id))))

    lock_timeout_ms = DB_LOCK_TIMEOUT_MS

    def regular_lock(self, recruit_id: int):
        """Async context manager serializing a Discord side effect with mode changes.

        Opens a DEDICATED connection and a transaction, takes
        `SELECT ... FROM recruits ... FOR SHARE` after verifying the recruit is
        regular and its Discord space is live (SUCCESS, not deleted), and keeps
        that lock until the block ends (COMMIT on success, ROLLBACK on error).
        A backend `UPDATE recruits SET recruit_mode='short'` therefore waits
        for the Discord work, and a short change that committed first makes
        entering the block raise GuardRejected before any Discord call.
        """
        return _PostgresRegularLock(self, recruit_id)

    def is_regular(self, recruit_id: int) -> bool:
        """Current recruit_mode check used right before Discord side effects."""
        return self._execute(
            "SELECT 1 AS ok FROM recruits WHERE recruit_id = %s AND recruit_mode = 'regular'",
            (recruit_id,), fetch="one",
        ) is not None

    # -- provisioning: regular recruit -> Discord space ---------------------
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
        """Regular, non-deleted recruits that still need a Discord space.

        No recruit_discord_channels row yet, or a FAILED row that never got
        Discord IDs, is not flagged MANUAL and is past the retry delay.
        recruits.state is intentionally ignored (it is recruiting status).
        """
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
        """Atomically take the creation slot; True only for a single winner.

        The recruit is re-validated (regular, not deleted) inside the same
        statement, so a candidate that changed after listing is never claimed.
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
        """Save the created IDs, tolerating a lost response.

        Returns normally when the IDs are (now) stored. Raises
        ProvisioningUnconfirmed when the outcome cannot be established; any
        other exception means the UPDATE definitely did not apply.
        """
        import psycopg

        ids = (str(category_id), str(text_channel_id),
               None if voice_channel_id is None else str(voice_channel_id))
        try:
            # The first activity baseline is the creation time, so a meeting
            # nobody ever talks in still enters the 30-day inactivity policy.
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
        """SUCCESS confirmation consistent with recruit_mode, in ONE transaction.

        The recruits row is locked FOR SHARE and re-read first: a concurrent
        regular->short UPDATE (made by the backend through another connection)
        either committed before we look (we see 'short' and refuse) or blocks
        until our transaction ends. An uncommitted mode change can therefore
        never cross with the SUCCESS UPDATE. Needs a DB role that may
        SELECT ... FOR SHARE on recruits (UPDATE privilege), like the backend's.
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
        self._execute(
            """
            UPDATE recruit_discord_channels
               SET sync_status = 'FAILED', sync_error = %s, updated_at = now()
             WHERE recruit_id = %s AND sync_status = 'PENDING'
            """,
            (error[:1000], recruit_id),
        )

    def fail_stale_pending(self) -> int:
        """A claim that never finished may have left an orphan Discord space."""
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

    # -- participants -------------------------------------------------------
    def list_participant_states(self) -> list[dict]:
        """JOINED/CANCELED members of live regular Discord meetings.

        Skipped: member_id=-1 (dev flow), members without a numeric discord_id,
        and role='HOST' rows (HOST overwrites are managed separately and must
        not be replaced by participant overwrites).
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
        """JOINED participants' Discord ids for one regular meeting."""
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
    """See PostgresMeetingRepository.regular_lock. Holds one connection per use.

    Ownership of the DB session (connection + transaction + row lock) is decided
    under `_state` between exactly two parties, so it is always released once:

    - normal path: the worker finishes acquiring and marks the session owned; the
      context manager's __aexit__ releases it.
    - caller cancelled while the worker was still acquiring: the caller marks the
      lock ABANDONED. A worker that acquires the lock later sees the flag under
      `_state`, releases (rollback + close) itself and never hands the session
      to anybody. A worker that had already finished is released by the caller.

    `mark_deleted` is executed on THIS session, inside this transaction, and only
    COMMITs when the whole `async with` block ended without error. On timeout,
    cancellation or any failure the in-flight statement is cancelled on the server
    (cancel_safe), the session waits until the worker thread has really finished
    that statement, and only then rolls back and closes. A statement that is still
    waiting for a lock can therefore never commit later.
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
        acquiring = asyncio.get_running_loop().run_in_executor(None, self._acquire)
        # A worker failing after the caller was cancelled must not log "never retrieved".
        acquiring.add_done_callback(lambda f: f.cancelled() or f.exception())
        try:
            await asyncio.shield(acquiring)
        except asyncio.CancelledError:
            self._abandon()
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb):
        # Shielded so a cancelled Discord call still ends the session; the
        # server-side idle_in_transaction timeout is only the last safety net.
        await asyncio.shield(asyncio.to_thread(self._finalize, exc_type is None))
        return False

    async def mark_deleted(self, category_id: int, now: datetime, timeout_seconds=None) -> bool:
        """discord_deleted_at UPDATE inside this lock's transaction (committed with it).

        timeout_seconds is the time left in the caller's budget; it is applied as a
        server-side `SET LOCAL statement_timeout` so the SQL cannot outlive it.
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
        """Ask the server to abort the statement currently running on this session."""
        with self._state:
            running = self._stmt_running
            conn = self._conn
        if running and conn is not None:
            try:
                (getattr(conn, "cancel_safe", None) or conn.cancel)()
            except Exception:
                pass

    def _finalize(self, commit: bool) -> None:
        """End the session. Never touches the connection while a statement runs on it."""
        with self._state:
            self._closing = True  # a worker that has not started yet will refuse to run
        if not commit:
            self._cancel_statement()
        # Ownership stays here until the worker thread has really finished.
        self._stmt_idle.wait(timeout=30)
        self._finish(commit)

    def _abandon(self) -> None:
        """Caller cancelled during acquisition: make sure the session gets released."""
        with self._state:
            self._abandoned = True
            owned = self._owned
        if owned:  # the worker already finished and handed the session over to us
            self._finish(False)

    def _acquire(self) -> None:
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
                cur.execute(f"SET LOCAL idle_in_transaction_session_timeout = {int(DB_LOCK_IDLE_IN_TRANSACTION_MS)}")
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
        # The lock is held now: decide, atomically, who releases it.
        with self._state:
            if self._abandoned:
                abandoned = True
            else:
                self._owned = True
                abandoned = False
        if abandoned:
            self._finish(False)  # nobody is waiting for this session any more

    def _finish(self, commit: bool) -> None:
        """End the transaction and close the dedicated connection (idempotent)."""
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
