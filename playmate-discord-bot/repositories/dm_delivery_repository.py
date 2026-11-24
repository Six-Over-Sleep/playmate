"""댓글·대댓글 DM 공동 선점 저장소 (Issue #171). Gateway Bot과 DM Lambda가 **같은 SQL**로 선점하고 결과를 기록한다.

config와 discord.py를 import하지 않는다 (DM DB Lambda가 그대로 쓴다). DB 연결은 repositories.db.Database를 쓴다.

테이블: notification_dm_deliveries (database/sql/053, 잠정 번호). notifications의 구조·CHECK는 바꾸지 않는다.
  - 최종 상태(SENT/SKIPPED/FAILED)와 실패 횟수(retry_count)는 계속 notifications가 가진다 (기존 Gateway 규칙과 같은 SQL 의미).
  - 이 표는 선점(누가 보내는 중인가)과 Lambda 결과 불명 확인 정보만 가진다.

선점 규칙 (claim)
  1. notifications를 `FOR UPDATE OF n SKIP LOCKED`로 잡는다: 다른 선점자와 겹치지 않고, 탈퇴 DELETE는 이 트랜잭션이 끝날 때까지 기다린다.
  2. 행마다 skip_reason(알림 OFF, 탈퇴(discord_id='w..'), 대상 삭제, 본인, 미지원 종류)을 **선점 시점의 최신 값**으로 다시 판단한다.
  3. INSERT ... ON CONFLICT (notification_id) DO UPDATE ... WHERE status='FAILED' AND next_retry_at <= now:
     행이 없거나 재시도 가능한 FAILED일 때만 성공한다 (RETURNING이 없으면 진 것). 재선점마다 claim_token이 바뀐다.
     PENDING(다른 쪽이 보내는 중) / SENT / UNKNOWN / 자동 재시도 없는 FAILED는 다시 선점되지 않는다.
  4. 행마다 savepoint: FK 위반(그 사이 notifications가 삭제됨)이면 그 알림만 빼고 배치는 계속한다.
결과는 claim_token이 같을 때만 반영한다. notifications 갱신은 모두 `status = 'PENDING'`일 때만 적용된다 (기존 규칙).
"""
import logging
from datetime import datetime, timedelta, timezone

from career_share import state
from career_share.contract import new_token
from services.notification_policy import skip_reason, to_discord_id

log = logging.getLogger("dm_share")
UTC = timezone.utc
SENDER_GATEWAY, SENDER_LAMBDA = "GATEWAY", "LAMBDA"
TABLE = "notification_dm_deliveries"
LAMBDA_CLAIM_LOCK = 610_171_001        # Lambda 선점(시험 발송 포함)을 직렬화한다
RECOVER_LOCK = 610_171_003
DB_NOW = "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC')"   # 교차 재선점·인증 차단 판정은 DB 시각으로 한다
# R4: Gateway가 Lambda의 FAILED 행을 이어받는 데 필요한 최소 경과 시간 (Lambda claimed_at 기준).
# 진행 중인 Lambda HTTP 요청은 Worker 실행이 끝나면 끝나고, AWS Lambda 실행 시간 상한은 15분이다.
GATEWAY_TAKEOVER_MINUTES = 16
# R5: Discord 401 인증 차단기. 상태는 notification_dm_deliveries.error_message 접두어와 updated_at(DB 시각)로 표시한다.
AUTH_MARK = "DISCORD_AUTH_401"          # 401로 실패/보류된 LAMBDA 행 (retry_count는 올리지 않는다)
AUTH_PROBE = "DISCORD_AUTH_PROBE"       # 차단 중 시험 발송으로 선점된 행 (최대 1건)
AUTH_HOLD_MINUTES = 10
AUTH_ALERT_HOURS = 24
ERROR_LIMIT = 500
DM_BLOCKED_CODE = 50007                 # Cannot send messages to this user
USER_GONE_CODES = (10013, 50033)        # Unknown user / Invalid recipient (공식 문서 코드. HTTP 상태는 실환경 미확인)
GATEWAY_UNCERTAIN = "Gateway 전송 결과 불명: 중복 방지를 위해 재발송하지 않음"
GATEWAY_EXPIRED = "Gateway 선점 후 결과 없음(만료): 중복 방지를 위해 재발송하지 않음"
LAMBDA_UNVERIFIABLE = "DM 전송 결과 불명(확인 한도 초과): 중복 방지를 위해 재발송하지 않음"


def _naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("naive datetime 금지")
    return value.astimezone(UTC).replace(tzinfo=None)


def _aware(value: datetime | None) -> datetime | None:
    return None if value is None else value.replace(tzinfo=UTC)


def dm_unit_id(notification_id: int) -> str:
    return f"dm-{int(notification_id)}"


def notification_id_of(unit_id) -> int | None:
    if isinstance(unit_id, str) and unit_id.startswith("dm-") and unit_id[3:].isdigit():
        return int(unit_id[3:])
    return None


# 기존 PostgresNotificationRepository.claim_pending과 같은 JOIN·조건 + 공동 선점 조건 + 행 잠금
CANDIDATES_SQL = f"""
    SELECT n.notification_id, n.notification_type, n.receiver_member_id,
           n.actor_member_id, n.post_id, n.comment_id, n.retry_count,
           m.discord_id AS receiver_discord_id,
           m.external_dm_opt_in AS receiver_dm_opt_in,
           p.title AS post_title,
           p.post_type, p.board_id AS post_board_id,
           r.recruit_id, cp.category_code AS career_category,
           ((n.post_id IS NOT NULL AND (p.post_id IS NULL OR p.deleted_at IS NOT NULL))
            OR (n.comment_id IS NOT NULL AND (c.comment_id IS NULL OR c.deleted_at IS NOT NULL))
           ) AS target_missing
      FROM notifications n
      JOIN members m ON m.member_id = n.receiver_member_id
      LEFT JOIN posts p ON p.post_id = n.post_id
      LEFT JOIN recruits r ON r.post_id = n.post_id
      -- The consolidated career table is used directly.
      LEFT JOIN career cp ON cp.post_id = n.post_id
      LEFT JOIN comments c ON c.comment_id = n.comment_id
      LEFT JOIN {TABLE} d ON d.notification_id = n.notification_id
     WHERE n.status = 'PENDING'
       AND (n.last_attempt_at IS NULL
            OR n.last_attempt_at <= CURRENT_TIMESTAMP - make_interval(secs => %(retry_seconds)s))
       AND (d.notification_id IS NULL
            OR (d.status = 'FAILED' AND d.next_retry_at IS NOT NULL AND d.next_retry_at <= %(now)s
                -- R4: Gateway는 Lambda의 FAILED 행을 Lambda 선점 후 {GATEWAY_TAKEOVER_MINUTES}분(기본)이 지나야 이어받는다 (DB 시각)
                AND (%(sender)s <> 'GATEWAY' OR d.sender <> 'LAMBDA'
                     OR d.claimed_at <= {DB_NOW} - make_interval(mins => %(takeover)s))))
     ORDER BY n.created_at, n.notification_id
     LIMIT %(limit)s
     FOR UPDATE OF n SKIP LOCKED
"""

UPSERT_SQL = f"""
    INSERT INTO {TABLE} AS d
           (notification_id, sender, status, claim_token, claimed_at, claim_expires_at, recipient_discord_id, updated_at)
    VALUES (%(nid)s, %(sender)s, 'PENDING', %(token)s, %(now)s, %(expires)s, %(recipient)s, %(now)s)
    ON CONFLICT (notification_id) DO UPDATE
       SET sender = EXCLUDED.sender, status = 'PENDING', claim_token = EXCLUDED.claim_token,
           claimed_at = EXCLUDED.claimed_at, claim_expires_at = EXCLUDED.claim_expires_at,
           recipient_discord_id = EXCLUDED.recipient_discord_id, next_retry_at = NULL,
           verify_count = 0, last_verified_at = NULL, absent_count = 0, last_absent_job_id = NULL,
           discord_message_id = NULL, error_message = NULL, updated_at = EXCLUDED.updated_at
     WHERE d.status = 'FAILED' AND d.next_retry_at IS NOT NULL AND d.next_retry_at <= %(now)s
       AND (EXCLUDED.sender <> 'GATEWAY' OR d.sender <> 'LAMBDA'
            OR d.claimed_at <= {DB_NOW} - make_interval(mins => %(takeover)s))
    RETURNING notification_id
"""


class DmDeliveryRepository:
    def __init__(self, database, *, retry_seconds: int = 60, max_attempts: int = 3,
                 gateway_takeover_minutes: int = GATEWAY_TAKEOVER_MINUTES):
        self._db = database
        self.retry_seconds = retry_seconds
        self.max_attempts = max_attempts
        self.gateway_takeover_minutes = gateway_takeover_minutes   # 테스트에서 수정 전 동작 재현용으로만 바꾼다
        self.last_breaker: dict = {}

    def available(self) -> bool:
        """053이 적용됐는가. 적용 뒤에는 Gateway도 반드시 이 저장소로 선점해야 한다."""
        return self._db.table_exists(TABLE)

    # -- notifications 갱신 (기존 PostgresNotificationRepository와 같은 의미, PENDING일 때만) ---------------------------
    @staticmethod
    def _notif_sent(cur, nid: int) -> bool:
        cur.execute("""UPDATE notifications SET status = 'SENT', sent_at = CURRENT_TIMESTAMP,
                              last_attempt_at = CURRENT_TIMESTAMP, error_message = NULL
                        WHERE notification_id = %s AND status = 'PENDING'""", (nid,))
        return cur.rowcount == 1

    @staticmethod
    def _notif_skipped(cur, nid: int, reason: str) -> bool:
        cur.execute("""UPDATE notifications SET status = 'SKIPPED', error_message = %s, last_attempt_at = CURRENT_TIMESTAMP
                        WHERE notification_id = %s AND status = 'PENDING'""", (reason[:ERROR_LIMIT], nid))
        return cur.rowcount == 1

    def _notif_failure(self, cur, nid: int, error: str, *, final: bool) -> str | None:
        """retry_count + 1. final이거나 한도에 이르면 FAILED, 아니면 PENDING. 대상이 PENDING이 아니면 None."""
        cur.execute("""UPDATE notifications
                          SET retry_count = retry_count + 1, last_attempt_at = CURRENT_TIMESTAMP, error_message = %(error)s,
                              status = CASE WHEN %(final)s OR retry_count + 1 >= %(max)s THEN 'FAILED' ELSE 'PENDING' END
                        WHERE notification_id = %(nid)s AND status = 'PENDING'
                    RETURNING status""", dict(error=error[:ERROR_LIMIT], final=final, max=self.max_attempts, nid=nid))
        row = cur.fetchone()
        return row["status"] if row else None

    @staticmethod
    def _report_missing(cur, nid: int, context: str, message_id=None) -> str:
        """결과를 반영할 선점 행이 없음. 원본 알림이 삭제(탈퇴 등)됐으면 경고를 남긴다 (조용히 성공 처리하지 않는다)."""
        cur.execute("SELECT 1 FROM notifications WHERE notification_id = %s", (nid,))
        if cur.fetchone() is None:
            log.warning("[DM] 결과 반영 대상 알림이 없음(탈퇴 등으로 삭제) notification_id=%s 결과=%s message_id=%s",
                        nid, context, message_id or "-")
            return "missing_notification"
        return "ignored"   # 소유권이 바뀜(재선점) 또는 다른 sender의 행: 이 결과는 반영하지 않는다

    def _set_delivery(self, cur, nid: int, now: datetime, **fields) -> None:
        sets = ", ".join(f"{key} = %({key})s" for key in fields)
        cur.execute(f"UPDATE {TABLE} SET {sets}, updated_at = %(now)s WHERE notification_id = %(nid)s",
                    dict(fields, now=_naive(now), nid=nid))

    # -- 선점 (Gateway·Lambda 공통) ----------------------------------------------------------------------------
    def _claim_row(self, cur, row: dict, sender: str, now: datetime, stale_seconds: int) -> str | None:
        """한 알림의 선점을 savepoint 안에서 시도한다. 성공하면 claim_token, 아니면 None."""
        import psycopg
        token = new_token()
        recipient = to_discord_id(row.get("receiver_discord_id")) if sender == SENDER_LAMBDA else None
        try:
            with cur.connection.transaction():   # 중첩 = savepoint
                cur.execute(UPSERT_SQL, dict(nid=row["notification_id"], sender=sender, token=token, now=_naive(now),
                                             expires=_naive(now + timedelta(seconds=stale_seconds)),
                                             recipient=str(recipient) if recipient else None,
                                             takeover=self.gateway_takeover_minutes))
                won = cur.fetchone() is not None
        except psycopg.errors.ForeignKeyViolation:
            log.warning("[DM] 선점 중 알림이 삭제됨(탈퇴 등) notification_id=%s: 이 알림만 제외합니다.", row["notification_id"])
            return None
        return token if won else None

    def claim(self, sender: str, now: datetime, *, limit: int, stale_seconds: int) -> list[dict]:
        """보낼 알림을 선점한다. 건너뛸 대상은 이 자리에서 SKIPPED로 기록한다.

        반환: [{"notification": 행, "claim_token": ..., "claimed_at": now, "recipient_id": "<discord id>"}]
        """
        if sender not in (SENDER_GATEWAY, SENDER_LAMBDA):
            raise ValueError("sender")

        def work(cur):
            take, probe = limit, False
            if sender == SENDER_LAMBDA:
                # 모든 Lambda 선점을 한 트랜잭션씩 직렬화한다: 차단기 판정과 시험 선점이 동시에 두 번 일어나지 않는다.
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (LAMBDA_CLAIM_LOCK,))
                breaker = self._breaker(cur)
                self.last_breaker = breaker
                if breaker["state"] == "BLOCKED":
                    return []
                if breaker["state"] == "PROBE":
                    take, probe = 1, True
            cur.execute(CANDIDATES_SQL, dict(retry_seconds=self.retry_seconds, now=_naive(now), limit=take,
                                             sender=sender, takeover=self.gateway_takeover_minutes))
            claims = []
            for row in cur.fetchall():
                reason = skip_reason(row)
                if reason is not None:
                    self._notif_skipped(cur, row["notification_id"], reason)
                    continue
                token = self._claim_row(cur, row, sender, now, stale_seconds)
                if token is not None:
                    if probe:
                        cur.execute(f"UPDATE {TABLE} SET error_message = %s, updated_at = {DB_NOW} WHERE notification_id = %s",
                                    (AUTH_PROBE, row["notification_id"]))
                        log.error("[DM] %s 시험 발송 1건 notification_id=%s", AUTH_MARK, row["notification_id"])
                    claims.append({"notification": row, "claim_token": token, "claimed_at": now,
                                   "recipient_id": str(to_discord_id(row["receiver_discord_id"]))})
            return claims
        return self._db.transaction(work)

    # -- R5: Discord 401 인증 차단기 ------------------------------------------------------------------------------
    def _breaker(self, cur) -> dict:
        """LAMBDA 행의 인증 표시로 차단기 상태를 판정한다 (DB 시각).

        OPEN 표시 = error_message가 DISCORD_AUTH_401… 또는 DISCORD_AUTH_PROBE인 LAMBDA 행이 있음 (시험 성공 시 모두 지운다).
          BLOCKED : 최근 AUTH_HOLD_MINUTES 안에 401이 기록됐거나, 시험 발송이 아직 진행 중(PENDING)이다 -> 선점 0건
          PROBE   : 표시는 있지만 마지막 401 이후 AUTH_HOLD_MINUTES가 지났고 진행 중 시험이 없다 -> 1건만 선점
          CLOSED  : 표시 없음 -> 정상
        호출자는 LAMBDA_CLAIM_LOCK을 잡은 상태여야 한다 (판정과 시험 선점이 원자적이다).
        """
        cur.execute(f"""SELECT COUNT(*) AS marks,
                               COUNT(*) FILTER (WHERE error_message = %(probe)s AND status = 'PENDING') AS probes,
                               MAX(updated_at) FILTER (WHERE error_message LIKE %(mark)s) AS last_auth,
                               MIN(updated_at) FILTER (WHERE error_message LIKE %(mark)s) AS first_auth,
                               {DB_NOW} AS db_now
                          FROM {TABLE}
                         WHERE sender = 'LAMBDA' AND (error_message LIKE %(mark)s OR error_message = %(probe)s)""",
                    dict(mark=AUTH_MARK + "%", probe=AUTH_PROBE))
        row = cur.fetchone()
        if not row["marks"]:
            return {"state": "CLOSED"}
        db_now, last, first = row["db_now"], row["last_auth"], row["first_auth"]
        recent = last is not None and last > db_now - timedelta(minutes=AUTH_HOLD_MINUTES)
        state = "BLOCKED" if recent or row["probes"] else "PROBE"
        if first is not None and first <= db_now - timedelta(hours=AUTH_ALERT_HOURS):
            log.error("[DM] %s 인증 장애가 %s시간 이상 지속 중 (최초 %s UTC): 토큰을 확인하세요. 알림은 FAILED로 마감하지 않고 보류합니다.",
                      AUTH_MARK, AUTH_ALERT_HOURS, first)
        elif state == "BLOCKED":
            log.error("[DM] %s 인증 장애로 DM 선점을 멈춤 (마지막 401 %s UTC, 시험 진행 중 %s건)", AUTH_MARK, last, row["probes"])
        return {"state": state, "last_auth": last, "first_auth": first, "probes": int(row["probes"])}

    def auth_open(self) -> bool:
        """인증 표시가 남아 있는가 (시험 성공 전). 이 동안 마커 확인·확인 한도 마감을 멈춘다."""
        row = self._db.execute(f"SELECT 1 FROM {TABLE} WHERE sender = 'LAMBDA' AND (error_message LIKE %s OR error_message = %s) "
                               "LIMIT 1", (AUTH_MARK + "%", AUTH_PROBE), fetch="one")
        return row is not None

    def _owned(self, cur, nid: int, token: str, sender: str):
        cur.execute(f"""SELECT notification_id, sender, status, verify_count, absent_count, last_absent_job_id, error_message
                          FROM {TABLE} WHERE notification_id = %s AND claim_token = %s AND sender = %s FOR UPDATE""",
                    (nid, token, sender))
        return cur.fetchone()

    # -- Gateway 결과 기록 (선점한 토큰으로만, PENDING 행만) --------------------------------------------------------
    def gateway_sent(self, nid: int, token: str, now: datetime) -> str:
        def work(cur):
            row = self._owned(cur, nid, token, SENDER_GATEWAY)
            if row is None or row["status"] != "PENDING":
                return self._report_missing(cur, nid, "SENT(Gateway)") if row is None else "duplicate"
            self._set_delivery(cur, nid, now, status="SENT", error_message=None)
            if not self._notif_sent(cur, nid):
                log.warning("[DM] Gateway 전송 후 notifications가 PENDING이 아님 notification_id=%s", nid)
            return "applied"
        return self._db.transaction(work)

    def gateway_skipped(self, nid: int, token: str, now: datetime, reason: str) -> str:
        def work(cur):
            row = self._owned(cur, nid, token, SENDER_GATEWAY)
            if row is None or row["status"] != "PENDING":
                return self._report_missing(cur, nid, "SKIPPED(Gateway)") if row is None else "duplicate"
            self._set_delivery(cur, nid, now, status="FAILED", next_retry_at=None, error_message=reason[:ERROR_LIMIT])
            self._notif_skipped(cur, nid, reason)
            return "applied"
        return self._db.transaction(work)

    def gateway_failure(self, nid: int, token: str, now: datetime, error: str, *, final: bool) -> str | None:
        """Gateway 실패. final=False(전송되지 않았음이 확실)는 기존 정책대로 retry_count + 1 후 60초 뒤 재시도(3회째 FAILED).
        final=True(결과 불명)는 재발송하지 않고 FAILED로 마감한다. 반환: notifications의 새 상태 (없으면 None)."""
        def work(cur):
            row = self._owned(cur, nid, token, SENDER_GATEWAY)
            if row is None or row["status"] != "PENDING":
                if row is None:
                    self._report_missing(cur, nid, "FAILED(Gateway)")
                return None
            status = self._notif_failure(cur, nid, error, final=final)
            retry = _naive(now + timedelta(seconds=self.retry_seconds)) if status == "PENDING" else None
            self._set_delivery(cur, nid, now, status="FAILED", next_retry_at=retry, error_message=error[:ERROR_LIMIT])
            if final:
                log.warning("[DM] %s notification_id=%s (%s)", GATEWAY_UNCERTAIN, nid, error[:200])
            return status
        return self._db.transaction(work)

    def expire_gateway_claims(self, now: datetime) -> list[int]:
        """Gateway가 선점하고 결과를 남기지 못한 채 만료된 행: 재발송하지 않고 FAILED로 마감하고 경고를 남긴다."""
        def work(cur):
            cur.execute(f"""SELECT notification_id FROM {TABLE}
                             WHERE sender = 'GATEWAY' AND status = 'PENDING' AND claim_expires_at < %s
                             ORDER BY notification_id FOR UPDATE SKIP LOCKED""", (_naive(now),))
            ids = [row["notification_id"] for row in cur.fetchall()]
            for nid in ids:
                self._notif_failure(cur, nid, GATEWAY_EXPIRED, final=True)
                self._set_delivery(cur, nid, now, status="FAILED", next_retry_at=None, error_message=GATEWAY_EXPIRED)
                log.warning("[DM] %s notification_id=%s (DM이 이미 전송됐을 수 있음, 누락 가능)", GATEWAY_EXPIRED, nid)
            return ids
        return self._db.transaction(work)

    # -- Lambda 결과 반영 (career_share/hot_share와 같은 상태 전이) -----------------------------------------------------
    def apply_result(self, result: dict, now: datetime, *, retry_base_minutes=None, absent_required: int = 2) -> str:
        """Worker 결과 반영. retry_base_minutes는 CareerShareService 호환용으로 받기만 한다 (재시도 간격은 retry_seconds)."""
        nid = notification_id_of(result.get("unit_id"))
        if nid is None:
            return "ignored"   # dm-<id>가 아닌 결과(취업·HOT)는 이 테이블의 것이 아니다
        token, outcome = result["claim_token"], result["outcome"]
        job_id = str(result.get("job_id") or "")

        def work(cur):
            row = self._owned(cur, nid, token, SENDER_LAMBDA)
            if row is None:
                return self._report_missing(cur, nid, outcome, result.get("message_id"))
            if result.get("auth_error"):
                return self._apply_auth(cur, row, nid, outcome, job_id, now)
            if row["error_message"] == AUTH_PROBE:
                # 시험 발송이 401이 아닌 응답을 받았다 = 토큰은 정상이다. 인증 표시를 모두 지워 정상 처리를 재개한다.
                cur.execute(f"UPDATE {TABLE} SET error_message = NULL, updated_at = {DB_NOW} "
                            "WHERE sender = 'LAMBDA' AND (error_message LIKE %s OR error_message = %s)", (AUTH_MARK + "%", AUTH_PROBE))
                log.error("[DM] %s 시험 발송 결과 %s: 인증 복구 확인, 정상 처리 재개 (표시 %s건 해제)", AUTH_MARK, outcome, cur.rowcount)
            new = state.next_state(row["status"], outcome)
            if new is None:
                return "duplicate"
            if row["status"] == state.UNKNOWN and outcome == "ABSENT_PROVEN":
                if row["last_absent_job_id"] == job_id:
                    return "duplicate"   # 같은 확인 작업의 결과가 중복 도착: 두 번 세지 않는다
                if row["absent_count"] + 1 < absent_required:
                    self._set_delivery(cur, nid, now, absent_count=row["absent_count"] + 1, last_absent_job_id=job_id)
                    return "applied"
            if new == row["status"]:
                if outcome == "INCONCLUSIVE":
                    self._set_delivery(cur, nid, now, absent_count=0, last_absent_job_id=None)
                    return "applied"
                return "duplicate"
            error = str(result.get("error") or outcome)[:ERROR_LIMIT]
            if new == state.SENT:
                self._set_delivery(cur, nid, now, status="SENT", discord_message_id=result.get("message_id"), error_message=None)
                if not self._notif_sent(cur, nid):
                    log.warning("[DM] 전송 확인됐지만 notifications가 PENDING이 아님 notification_id=%s message_id=%s",
                                nid, result.get("message_id"))
                return "applied"
            if new == state.UNKNOWN:
                self._set_delivery(cur, nid, now, status="UNKNOWN", error_message=error, last_verified_at=_naive(now),
                                   verify_count=0, absent_count=0, last_absent_job_id=None)
                return "applied"
            # new == FAILED
            code = result.get("error_code")
            if outcome == "FAILED_PERMANENT" and code in USER_GONE_CODES:
                self._set_delivery(cur, nid, now, status="FAILED", next_retry_at=None, error_message=error)
                self._notif_skipped(cur, nid, "Discord 사용자 없음")
                return "applied"
            final = outcome == "FAILED_PERMANENT"   # 50007(DM 차단) 즉시 FAILED, 메시지 생성 불가 등
            reason = "DM 수신 차단 (403)" if code == DM_BLOCKED_CODE else error
            status = self._notif_failure(cur, nid, reason, final=final)
            retry = _naive(now + timedelta(seconds=self.retry_seconds)) if status == "PENDING" else None
            self._set_delivery(cur, nid, now, status="FAILED", next_retry_at=retry, error_message=reason[:ERROR_LIMIT])
            return "applied"
        return self._db.transaction(work)

    def _apply_auth(self, cur, row, nid: int, outcome: str, job_id: str, now: datetime) -> str:
        """401 결과. retry_count를 올리지 않고, 전송되지 않은 실패와 전송 여부 불명을 구분해 기록한다 (DB 시각으로 표시)."""
        if row["status"] == state.UNKNOWN and outcome == "INCONCLUSIVE":
            # UNKNOWN 확인 작업의 401: 판단 보류. 상태·absent_count 유지, 발행 때 올린 verify_count는 되돌린다 (같은 작업은 한 번만).
            hold = f"{AUTH_MARK} 확인 보류 job={job_id}"[:ERROR_LIMIT]
            if row["error_message"] == hold:
                return "duplicate"
            cur.execute(f"UPDATE {TABLE} SET verify_count = GREATEST(verify_count - 1, 0), error_message = %s, updated_at = {DB_NOW} "
                        "WHERE notification_id = %s", (hold, nid))
            log.error("[DM] %s 확인 작업 인증 실패 notification_id=%s: UNKNOWN 유지(확인 보류)", AUTH_MARK, nid)
            return "auth_hold"
        if row["status"] == state.PENDING and outcome == "UNKNOWN":
            # 재전달 작업의 사전 조회가 401: 앞선 전달이 보냈는지 알 수 없다 -> UNKNOWN (재발송 금지, 인증 복구 후 마커 확인)
            cur.execute(f"""UPDATE {TABLE} SET status = 'UNKNOWN', error_message = %s, last_verified_at = %s, verify_count = 0,
                                   absent_count = 0, last_absent_job_id = NULL, updated_at = {DB_NOW} WHERE notification_id = %s""",
                        (f"{AUTH_MARK} 전송 여부 불명(재전달 작업, 확인 불가)", _naive(now), nid))
            log.error("[DM] %s 재전달 작업 확인 불가 notification_id=%s: UNKNOWN", AUTH_MARK, nid)
            return "auth_unknown"
        if row["status"] == state.PENDING and outcome == "FAILED_RETRY":
            # 401로 거절됨 = 전송되지 않았다. 실패 횟수로 세지 않고, 차단기가 풀린 뒤 다시 선점된다.
            cur.execute(f"UPDATE {TABLE} SET status = 'FAILED', next_retry_at = %s, error_message = %s, updated_at = {DB_NOW} "
                        "WHERE notification_id = %s",
                        (_naive(now + timedelta(seconds=self.retry_seconds)), f"{AUTH_MARK} 인증 실패: 전송되지 않음", nid))
            log.error("[DM] %s 인증 실패 notification_id=%s: 재시도 횟수 미소모, DM 선점 차단", AUTH_MARK, nid)
            return "auth_failed"
        return "duplicate"

    # -- Lambda 복구 ----------------------------------------------------------------------------------------------
    def _expire_lambda_pending(self, cur, now: datetime) -> None:
        """선점 후 결과 없이 만료된 LAMBDA PENDING -> UNKNOWN. 시험 발송 행이면 인증 표시를 유지한다 (차단기가 풀리지 않게)."""
        cur.execute(f"""UPDATE {TABLE}
                           SET status = 'UNKNOWN', last_verified_at = %(now)s, verify_count = 0, absent_count = 0,
                               last_absent_job_id = NULL,
                               error_message = CASE WHEN error_message = %(probe)s THEN %(probe_lost)s
                                                    ELSE '선점 후 결과 없음(만료)' END,
                               updated_at = CASE WHEN error_message = %(probe)s THEN {DB_NOW} ELSE %(now)s END
                         WHERE sender = 'LAMBDA' AND status = 'PENDING' AND claim_expires_at < %(now)s""",
                    dict(now=_naive(now), probe=AUTH_PROBE, probe_lost=f"{AUTH_MARK} 시험 결과 없음(만료)"))

    def expire_lambda_claims(self, now: datetime) -> None:
        """인증 차단 중에도 실행: 만료 처리만 한다 (Discord 호출 없음)."""
        def work(cur):
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (RECOVER_LOCK,))
            self._expire_lambda_pending(cur, now)
        self._db.transaction(work)

    def claim_verifications(self, now: datetime, *, max_verifies: int, interval_minutes: int, settle_minutes: int) -> list[dict]:
        """만료된 LAMBDA PENDING을 UNKNOWN으로 바꾸고, 정착 대기가 지난 UNKNOWN을 마커 확인 대상으로 고른다 (재발송 아님)."""
        def work(cur):
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (RECOVER_LOCK,))
            self._expire_lambda_pending(cur, now)
            cur.execute(f"""SELECT notification_id, claim_token, claimed_at, recipient_discord_id FROM {TABLE}
                             WHERE sender = 'LAMBDA' AND status = 'UNKNOWN' AND verify_count < %(max)s
                               AND COALESCE(last_verified_at, updated_at)
                                   <= %(now)s - make_interval(mins => CASE WHEN verify_count = 0 THEN %(settle)s ELSE %(interval)s END)
                             ORDER BY notification_id""",
                        dict(max=max_verifies, now=_naive(now), settle=settle_minutes, interval=interval_minutes))
            tasks = [{"unit_id": dm_unit_id(r["notification_id"]), "claim_token": r["claim_token"],
                      "claimed_at": _aware(r["claimed_at"]), "recipient_id": r["recipient_discord_id"],
                      "notification_id": r["notification_id"]} for r in cur.fetchall()]
            if tasks:
                cur.execute(f"UPDATE {TABLE} SET verify_count = verify_count + 1, last_verified_at = %s "
                            "WHERE notification_id = ANY(%s) AND status = 'UNKNOWN'",
                            (_naive(now), [t["notification_id"] for t in tasks]))
            return tasks
        return self._db.transaction(work)

    def finalize_unverifiable(self, now: datetime, *, max_verifies: int, interval_minutes: int) -> list[int]:
        """확인 한도를 다 쓰고도 UNKNOWN인 알림: notifications를 FAILED로 마감한다 (자동 재발송 금지). 마지막 확인 결과를 기다린 뒤에만."""
        def work(cur):
            cur.execute(f"""SELECT d.notification_id FROM {TABLE} d
                              JOIN notifications n ON n.notification_id = d.notification_id AND n.status = 'PENDING'
                             WHERE d.sender = 'LAMBDA' AND d.status = 'UNKNOWN' AND d.verify_count >= %(max)s
                               AND d.last_verified_at <= %(now)s - make_interval(mins => %(interval)s)
                             ORDER BY d.notification_id FOR UPDATE OF d SKIP LOCKED""",
                        dict(max=max_verifies, now=_naive(now), interval=interval_minutes))
            ids = [row["notification_id"] for row in cur.fetchall()]
            for nid in ids:
                self._notif_failure(cur, nid, LAMBDA_UNVERIFIABLE, final=True)
                self._set_delivery(cur, nid, now, error_message=LAMBDA_UNVERIFIABLE)
                log.warning("[DM] %s notification_id=%s (운영자 확인 필요)", LAMBDA_UNVERIFIABLE, nid)
            return ids
        return self._db.transaction(work)

    def summary(self) -> dict:
        rows = self._db.execute(f"SELECT sender, status, COUNT(*) AS n FROM {TABLE} GROUP BY sender, status", fetch="all")
        counts = {f"{r['sender']}:{r['status']}": int(r["n"]) for r in rows}
        pending = self._db.execute("SELECT COUNT(*) AS n FROM notifications WHERE status = 'PENDING'", fetch="one")
        counts["notifications_pending"] = int(pending["n"])
        counts["auth_blocked"] = self.auth_open()
        return counts
