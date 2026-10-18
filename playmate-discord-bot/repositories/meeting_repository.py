"""모임 상태 저장소 경계.

- InMemoryMeetingRepository: DB 설정이 없을 때 쓰는 메모리 구현. 프로세스가 끝나면 상태가 사라진다.
- PostgresMeetingRepository: 공용 테이블 recruit_discord_channels를 쓰는 영속 구현.
키는 Discord 카테고리 ID이고, 모임의 식별자는 항상 Backend의 recruit_id다.
메시지 본문은 이 계층에 전달되지 않는다.

상태 변경 원칙:
    lifecycle/활동 상태는 목적별 조건부 연산(record_activity, record_warning,
    cancel_schedule, mark_deleted)으로만 바꾸고, 읽기 전용 is_delete_due로 확인한다.
    각 연산은 저장된 상태가 전제 조건과 같을 때만 적용되므로, 오래된 snapshot이
    더 새로운 상태를 덮어쓸 수 없다.

동기/비동기:
    저장소 메서드는 동기 함수다. 비동기 코드는 `call()`로 호출해서, 막히는 DB 작업이
    Discord 이벤트 루프(heartbeat 포함)를 멈추지 않고 worker thread에서 실행되게 한다.
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

Meeting = dict[str, Any]


async def call(method: Callable, *args):
    """동기 저장소 메서드를 이벤트 루프 밖의 worker thread에서 실행하고 결과를 기다린다.

    DB 호출이 오래 걸려도 Discord 이벤트 루프가 멈추지 않게 하기 위한 래퍼다.
    """
    return await asyncio.to_thread(method, *args)


class GuardRejected(Exception):
    """모임이 더 이상 "Discord 공간이 살아 있는 regular 모임"이 아니어서 작업을 시작할 수 없다.

    예: 모임이 short로 바뀌었거나 이미 삭제 처리됨. 이때 Discord 작업은 실행하지 않는다.
    """


class RegularLockUnavailable(Exception):
    """recruits 행 락을 제한 시간 안에 얻지 못했다 (Backend가 같은 행을 수정 중).

    이번 주기는 건너뛰고 다음 주기에 다시 시도한다.
    """


class ProvisioningUnconfirmed(RuntimeError):
    """만들어 둔 Discord 공간의 ID를 DB에 저장한 결과를 확인할 수 없다.

    저장이 실제로 성공했을 수도 있으므로, 이 경우 Discord 공간을 자동으로 삭제하거나
    다시 만들면 안 된다 (호출자가 MANUAL로 남기고 사람이 확인한다).
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
    """DB 설정이 없을 때 쓰는 메모리 저장소 (테스트와 DB 없는 실행용).

    조건부 연산(record_activity 등)은 PostgreSQL 구현과 같은 의미로 동작해서,
    같은 lifecycle 코드를 두 구현으로 모두 검증할 수 있다.
    """
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
        """No row lock exists in memory; only the eligibility check remains."""
        return _InMemoryRegularLock(self, recruit_id)

    def is_regular(self, recruit_id: int) -> bool:
        return self._manageable(recruit_id)

    def _manageable(self, recruit_id: int) -> bool:
        return any(m.get("recruit_id") == recruit_id and m.get("discord_deleted_at") is None
                   for m in self._regular_meetings.values())


class _InMemoryRegularLock:
    """메모리 저장소용 락. 실제 row lock은 없고 "삭제되지 않은 모임인가"만 확인한다."""
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

# 선택 훅: recruit_id -> HOST의 Discord 사용자 ID (모르면 None).
# TODO: Backend가 모임 생성자를 recruit_members.role='HOST'로 저장하지 않아
#       아직 resolver를 연결하지 않았다. Backend 담당자와 계약을 정한 뒤 연결한다.
HostResolver = Callable[[int], "int | None"]

PING_AFTER_IDLE_SECONDS = 30


def _to_int(value: Any) -> int | None:
    """DB의 varchar Discord ID를 discord.py가 쓰는 정수로 바꾼다.

    NULL, 숫자가 아닌 값, 0 이하의 값은 None으로 돌려준다. 잘못된 ID 하나 때문에
    Bot 전체가 멈추지 않도록 호출자가 해당 행만 건너뛰게 하기 위해서다.
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _aware(value: datetime | None) -> datetime | None:
    """시간대 없는 시각(naive)이면 KST를 붙이고, 이미 시간대가 있으면 그대로 돌려준다."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=KST)
    return value


def _regular(alias: str) -> str:
    """"recruit_mode='regular'인 모임만 Bot이 관리한다"는 정책을 SQL 조건으로 만든다.

    alias는 recruit_id를 가진 테이블의 별칭이다. short 모임이 어떤 경로로도
    Discord 생성/권한/활동/삭제 대상이 되지 않게 하는 공통 방어선이다.
    """
    return (f"EXISTS (SELECT 1 FROM recruits r WHERE r.recruit_id = {alias}.recruit_id"
            " AND r.recruit_mode = 'regular')")


# discord_deleted_at은 살아 있는 regular 모임에만 기록한다. 일반 저장소 메서드와
# 락 트랜잭션 안의 기록이 같은 SQL을 쓰도록 한 곳에 둔다.
_MARK_DELETED_SQL = f"""
    UPDATE recruit_discord_channels rc
       SET discord_deleted_at = %s, updated_at = now()
     WHERE rc.discord_category_id = %s AND rc.sync_status = 'SUCCESS'
       AND rc.discord_deleted_at IS NULL AND {_regular('rc')}
"""


class PostgresMeetingRepository:
    """MeetingRepository 구현 + 생성(provisioning)/참여자 조회 쿼리 (공용 PostgreSQL).

    참고: recruits.discord_channel_id / discord_channel_status는 예전 Discord 컬럼으로 보이며
    Bot은 읽지도 쓰지도 않는다. Discord 상태의 기준은 recruit_discord_channels 하나다.
    TODO: 실제 사용처를 확인한 뒤 팀 협의로 정리한다.

    DB 계약: recruit_discord_channels의 Discord ID는 varchar(32)다.
    쓰고 비교할 때는 str(...)을 쓰고, discord.py에 넘길 때만 int()로 바꾼다.
    NULL이나 숫자가 아닌 ID는 해당 행만 건너뛰며 Bot을 멈추지 않는다.

    재시도 정책: 읽기는 연결이 끊기면 한 번 재시도한다. 쓰기는 자동 재시도하지 않는다
    (응답만 유실되고 실제로는 commit되었을 수 있기 때문). 대신 오래 쉰 연결은 먼저 ping해서,
    끊어진 소켓 때문에 첫 쓰기가 실패하는 일을 줄인다.
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
        # 관리 중인 카테고리 ID 집합. 메시지 핸들러가 관리 대상이 아닌 카테고리의 메시지마다
        # DB를 조회하지 않게 한다. None이면 아직 읽지 않은 상태(필터 없음).
        self._known_categories: set[int] | None = None

    @classmethod
    def from_env(cls, host_resolver: HostResolver | None = None):
        """환경변수(DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, DB_SSLMODE)로 저장소를 만든다.

        연결은 autocommit, 서울 시간대, 서버 statement_timeout(DB_STATEMENT_TIMEOUT_MS)을
        설정해서 연다. 실제 연결은 처음 쿼리를 실행할 때 만든다 (lazy).
        """
        import psycopg
        import config

        def connect():
            return psycopg.connect(
                host=config.DB_HOST, port=int(config.DB_PORT), user=config.DB_USER,
                password=config.DB_PASSWORD, dbname=config.DB_NAME,
                sslmode=config.DB_SSLMODE, connect_timeout=10, autocommit=True,
                options=(
                    "-c TimeZone=Asia/Seoul "
                    f"-c statement_timeout={config.DB_STATEMENT_TIMEOUT_MS}"
                ),
            )

        return cls(connect, host_resolver)

    # -- 연결 ---------------------------------------------------------
    def _connection(self):
        """공유 연결을 돌려준다. 필요하면 새로 연결한다.

        닫힌 연결은 버리고, PING_AFTER_IDLE_SECONDS 넘게 쓰지 않은 연결은 `SELECT 1`로
        확인해서 끊어졌으면 다시 연결한다.
        """
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
        """공유 연결을 닫고 버린다 (다음 사용 때 새로 연결). 닫는 중 오류는 무시한다."""
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        self._conn = None

    def _execute(self, sql: str, params: tuple = (), *, fetch: str | None = None):
        """SQL 한 개를 실행한다 (스레드 안전, 한 번에 하나만 실행).

        fetch=None: 쓰기. 영향 받은 행 수를 돌려주며 자동 재시도하지 않는다.
        fetch="one"/"all": 읽기. 한 행(dict 또는 None) / 모든 행(list[dict])을 돌려주며,
            연결이 끊기면 연결을 다시 열고 한 번 재시도한다.
        쓰기를 재시도하지 않는 이유: 응답이 유실되었어도 이미 commit된 변경일 수 있어서,
        재시도하면 결과를 잘못 판단하게 된다.
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
        """모임의 HOST Discord ID를 돌려준다. host_resolver가 연결되지 않았으면 None.

        TODO: Backend가 생성자를 recruit_members.role='HOST'로 저장하지 않아 아직 연결하지 않았다.
        """
        if self._host_resolver is None:
            return None
        return self._host_resolver(recruit_id)

    def refresh_known_categories(self) -> None:
        """관리 중인 카테고리 ID 집합을 다시 읽는다.

        메시지 핸들러가 관리 대상이 아닌 카테고리의 메시지마다 DB를 조회하지 않게 하는 용도다.
        """
        self._known_categories = {c for c, _ in self.list_regular_meetings()}

    def _to_meeting(self, row: dict) -> Meeting:
        """조회한 DB 행을 lifecycle이 쓰는 dict로 바꾼다 (ID는 int, 시각은 KST, host_id는 resolver 결과)."""
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
        """관리 중인 모든 regular 모임을 (카테고리 ID, 상태 dict) 목록으로 돌려준다.

        조건: SUCCESS, discord_deleted_at 없음, 카테고리 ID 있음, recruit_mode='regular'.
        카테고리 ID가 잘못된 행은 로그만 남기고 건너뛴다.
        """
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
        """카테고리 ID로 관리 중인 regular 모임 하나를 읽는다. 없으면 None.

        관리 대상으로 알려진 카테고리가 아니면 DB를 조회하지 않고 바로 None을 돌려준다.
        """
        if self._known_categories is not None and category_id not in self._known_categories:
            return None
        row = self._execute(
            self._LIFECYCLE_SELECT + " AND rc.discord_category_id = %s",
            (str(category_id),), fetch="one",
        )
        return self._to_meeting(row) if row else None

    def save_regular_meeting(self, category_id: int, meeting: Meeting) -> None:
        """모임 상태 전체를 저장한다 (MeetingRepository 인터페이스 호환용).

        lifecycle과 활동 기록 코드는 이 메서드를 쓰지 않고 아래의 조건부 연산을 쓴다.
        그래도 last_activity_at은 앞으로만 움직인다 (GREATEST).
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

    # -- 조건부 lifecycle 연산 ---------------------------------------
    _LIVE = ("rc.discord_category_id = %s AND rc.sync_status = 'SUCCESS' "
             "AND rc.discord_deleted_at IS NULL")

    def record_activity(self, category_id: int, now: datetime) -> bool:
        """활동을 기록하고, 진행 중인 비활성 경고와 삭제 예약을 취소한다. 반영되었으면 True.

        활동이 항상 우선한다. last_activity_at은 GREATEST로 갱신해서 더 오래된 값으로
        되돌아가지 않으며, 삭제 완료된 모임과 regular가 아닌 모임에는 적용되지 않는다.
        """
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
        """경고 시각과 삭제 예약 시각을 저장한다. 저장되었으면 True.

        읽어 둔 상태(경고/예약 없음, last_activity_at이 expected와 같음)가 그대로일 때만 저장한다.
        DM을 보내는 동안 새 활동이 있었다면 저장하지 않으므로 오래된 경고가 활동을 덮어쓰지 못한다.
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
        """지금 삭제해도 되는 모임인지 읽기 전용으로 확인한다.

        조건: 삭제 예약 시각이 지났고, 경고 이후 활동이 없다.
        아무것도 쓰지 않는다. discord_deleted_at은 Discord에서 삭제가 확인된 뒤에
        mark_deleted로만 기록하므로, 삭제가 실패하거나 불명확해도 "삭제됨" 상태가 남지 않고
        삭제 시도 중 들어온 활동도 거부되지 않는다.
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
        """Discord 부수효과와 모임 모드 변경을 직렬화하는 비동기 context manager를 돌려준다.

        전용 DB 연결과 트랜잭션을 열고, 모임이 regular이고 Discord 공간이 살아 있는지(SUCCESS,
        미삭제) 확인한 뒤 `recruits` 행에 `SELECT ... FOR SHARE` 락을 잡고, 블록이 끝날 때까지
        유지한다 (정상 종료면 COMMIT, 오류면 ROLLBACK).
        Backend의 `UPDATE recruits SET recruit_mode='short'`는 이 작업이 끝날 때까지 대기한다.
        short 변경이 먼저 commit되었다면 블록에 들어갈 때 GuardRejected가 발생해
        Discord 호출이 한 번도 실행되지 않는다. 락 대기가 길어지면 RegularLockUnavailable.
        """
        return _PostgresRegularLock(self, recruit_id)

    def is_regular(self, recruit_id: int) -> bool:
        """모임이 현재도 recruit_mode='regular'인지 확인한다."""
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
        """Discord 공간을 새로 만들어야 하는 regular 모임 목록(recruit_id, title)을 돌려준다.

        대상: 삭제되지 않은 regular 모임 중, recruit_discord_channels 행이 아직 없거나
        재시도 가능한 FAILED 행(Discord ID 없음, MANUAL/ABORTED 아님, 재시도 대기 시간 경과)인 것.
        recruits.state(모집 상태)는 일부러 보지 않는다.
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
        """모임의 생성 권한을 선점한다. 선점에 성공한 단 한 곳에서만 True.

        행이 없으면 PENDING 행을 INSERT하고(recruit_id PK 충돌은 무시), 재시도 가능한 FAILED 행은
        PENDING으로 되돌린다. 모임이 아직 regular이고 삭제되지 않았는지도 같은 SQL 안에서
        다시 확인하므로, 후보 조회 뒤에 short로 바뀐 모임은 선점되지 않는다.
        이 선점이 Bot 재시작/중복 실행에서 Discord 공간이 중복 생성되는 것을 막는다.
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
        """생성한 Discord 공간의 ID를 저장하고 SUCCESS로 확정한다 (응답 유실을 견딘다).

        정상 반환: ID가 저장되었다 (이미 같은 ID로 SUCCESS인 경우 포함).
        ProvisioningUnconfirmed: 저장 결과를 확인할 수 없다. 호출자는 공간을 지우지 말고 MANUAL로 남긴다.
        그 밖의 예외: UPDATE가 적용되지 않은 것이 확실하다. 호출자가 공간을 정리한다.
        처음 활동 기준 시각을 생성 시각으로 저장해서, 아무도 채팅하지 않는 모임도 30일 정책 대상이 된다.
        """
        import psycopg

        ids = (str(category_id), str(text_channel_id),
               None if voice_channel_id is None else str(voice_channel_id))
        try:
            # 처음 활동 기준 시각을 생성 시각으로 둔다. 아무도 채팅하지 않는 모임도
            # 30일 비활성 정책의 대상이 되게 하기 위해서다.
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
        """모임 모드와 일관되게 SUCCESS를 확정한다 (한 트랜잭션).

        recruits 행을 FOR SHARE로 잠그고 regular인지 다시 읽은 뒤 SUCCESS UPDATE를 실행한다.
        다른 연결(Backend)의 regular→short 변경이 아직 commit 전이면 그 변경이 끝날 때까지 기다리고,
        먼저 commit되었다면 short를 보고 SUCCESS를 거부(0행)한다. 그래서 short 모임이 SUCCESS로
        남지 않는다. 필요한 DB 권한: recruits에 대한 SELECT ... FOR SHARE (UPDATE 권한).
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
        """저장 결과가 불명확할 때 DB를 다시 읽어, SUCCESS이고 세 ID가 방금 만든 것과 모두 같은지 확인한다.

        같지 않거나 읽을 수 없으면 ProvisioningUnconfirmed를 올린다. 이때 공간을 자동 삭제하지 않는다.
        """
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
        """PENDING 행을 FAILED로 바꾸고 사유(sync_error)를 기록한다.

        'MANUAL:' 또는 'ABORTED:'로 시작하는 사유는 자동 재시도하지 않는다. 사유는 1000자까지만 저장한다.
        """
        self._execute(
            """
            UPDATE recruit_discord_channels
               SET sync_status = 'FAILED', sync_error = %s, updated_at = now()
             WHERE recruit_id = %s AND sync_status = 'PENDING'
            """,
            (error[:1000], recruit_id),
        )

    def fail_stale_pending(self) -> int:
        """오래 PENDING으로 남은 행을 'MANUAL:' FAILED로 바꾸고 바꾼 행 수를 돌려준다.

        생성 도중 Bot이 중단되면 Discord에 추적되지 않는 공간이 남았을 수 있으므로 자동 재시도하지 않고
        사람이 확인하게 한다.
        """
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
        """라이브 regular 모임의 JOINED/CANCELED 참여자 상태를 돌려준다.

        제외: member_id=-1(개발용), discord_id가 없거나 숫자가 아닌 회원, role='HOST' 행
        (HOST 권한은 따로 관리하며 참여자 권한으로 덮어쓰면 안 된다).
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
        """한 regular 모임에서 JOINED 상태인 참여자의 Discord ID 목록을 돌려준다 (공간 생성 때 사용)."""
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
        # shield: 이미 취소된 작업에서도 세션 정리가 끝까지 실행되게 한다.
        # 서버의 idle_in_transaction 타임아웃은 정상 경로가 아니라 마지막 안전망이다.
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
