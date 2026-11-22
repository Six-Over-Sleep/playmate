"""HOT 공유 이력 저장소 (PostgreSQL). hot_discord_shares / hot_discord_share_state만 쓴다 (career_discord_announcements 미접근).

시각 인자는 모두 시간대가 있는 datetime이다. 이력 테이블의 시각은 UTC naive이므로 이 모듈 안에서만 변환한다.
HOT 판정의 7일 경계는 policy.LIKES_CTE가 웹 DB 세션 시간대(db_tz)로 계산한다 (Lambda 세션 시간대와 무관).

선점 원칙 (#163과 같은 장치)
  1. pg_advisory_xact_lock(HOT_LOCK)으로 baseline과 relay 선점 트랜잭션을 직렬화한다 (Scheduler 중복 실행, Lambda 동시 실행).
  2. relay는 같은 트랜잭션 안에서 baseline 완료 행(hot_discord_share_state)을 확인한다. 없으면 아무것도 선점하지 않는다.
  3. INSERT ... ON CONFLICT (post_id)는 '행이 없을 때' 또는 '재시도 가능한 FAILED일 때'만 성공한다 (RETURNING이 없으면 진 것).
     BASELINE/PENDING/SENT/UNKNOWN/SKIPPED 행은 다시 선점되지 않는다 -> HOT 재진입 재공유 금지.
  4. 후보 조건(HOT·공개 게시판·미삭제·미게시 제외)은 최초 선점과 FAILED 재선점 모두에 같은 SQL로 다시 적용된다.
결과 반영/복구 규칙은 career_share.state와 career_share.repository의 apply_result/claim_verifications와 같다
(share_kind·batch·announce_date가 없는 단건 공유 전용으로 옮겼다).
"""
import logging
from datetime import datetime, timedelta, timezone

from career_share import state
from career_share.contract import new_token
from hot_share import policy
from hot_share.messages import hot_unit_id, post_id_of

log = logging.getLogger("hot_share")
HOT_LOCK, RECOVER_LOCK = 610_165_001, 610_165_003   # #163(610_163_00x)과 겹치지 않는다
ERROR_LIMIT = 500
UTC = timezone.utc
BASELINE_REQUIRED = "baseline_required"


def _naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("naive datetime 금지")
    return value.astimezone(UTC).replace(tzinfo=None)


def _aware(value: datetime | None) -> datetime | None:
    return None if value is None else value.replace(tzinfo=UTC)


_BOARD_COLUMNS = "b.board_name, b.scope_type, b.course_code, b.cohort, b.institution_id, b.program_id, b.cohort_id"

# 웹 HOT 조건 전체 (게시판 공개 범위와 무관). baseline과 웹 일치 테스트가 쓴다.
WEB_HOT_SQL = f"""
    WITH {policy.LIKES_CTE}
    SELECT p.post_id, p.board_id, p.title, likes.recent_likes, {_BOARD_COLUMNS}
      FROM public.posts AS p
      JOIN public.boards AS b ON b.board_id = p.board_id
      JOIN likes ON likes.post_id = p.post_id
     WHERE {policy.WEB_HOT_POST_WHERE}
"""

# Discord 후보: 웹 HOT 조건 + 공유 허용 게시판 + (이력 없음 또는 재시도 가능한 FAILED). LIMIT은 한 번에 선점할 개수다.
CANDIDATES_SQL = f"""
    WITH {policy.LIKES_CTE}
    SELECT p.post_id, p.board_id, p.title, likes.recent_likes, {_BOARD_COLUMNS}
      FROM public.posts AS p
      JOIN public.boards AS b ON b.board_id = p.board_id
      JOIN likes ON likes.post_id = p.post_id
      LEFT JOIN public.hot_discord_shares AS h ON h.post_id = p.post_id
     WHERE {policy.WEB_HOT_POST_WHERE}
       {policy.SHAREABLE_BOARD_WHERE}
       AND (h.post_id IS NULL
            OR (h.status = 'FAILED' AND h.next_retry_at IS NOT NULL AND h.next_retry_at <= %(now_naive)s
                AND h.attempt_count < %(max_attempts)s))
     ORDER BY likes.recent_likes DESC, p.post_id ASC
     LIMIT %(limit)s
"""

_UPSERT = """
    INSERT INTO public.hot_discord_shares AS h
           (post_id, status, attempt_count, claim_token, claimed_at, claim_expires_at, created_at, updated_at)
    VALUES (%(post_id)s, 'PENDING', 1, %(token)s, %(now)s, %(expires)s, %(now)s, %(now)s)
    ON CONFLICT (post_id) DO UPDATE
       SET status = 'PENDING', attempt_count = h.attempt_count + 1, claim_token = EXCLUDED.claim_token,
           claimed_at = EXCLUDED.claimed_at, claim_expires_at = EXCLUDED.claim_expires_at,
           next_retry_at = NULL, error_message = NULL, discord_message_id = NULL, discord_channel_id = NULL, sent_at = NULL,
           verify_count = 0, last_verified_at = NULL, absent_count = 0, last_absent_job_id = NULL,
           updated_at = EXCLUDED.updated_at
     WHERE h.status = 'FAILED' AND h.next_retry_at IS NOT NULL AND h.next_retry_at <= %(now)s
       AND h.attempt_count < %(max_attempts)s
    RETURNING post_id
"""

# 지금도 공유해도 되는 글인가 (SENT 결과 반영 후 확인, summary). HOT 여부는 보지 않는다 (삭제·비공개·범위만).
_STILL_SHAREABLE_SQL = f"""
    SELECT p.post_id
      FROM public.posts AS p
      JOIN public.boards AS b ON b.board_id = p.board_id
     WHERE p.post_id = ANY(%(ids)s)
       AND p.post_type = 'BOARD' AND p.post_status = 'PUBLISHED' AND p.deleted_at IS NULL
       AND b.board_name <> %(notice)s
       AND NOT EXISTS (SELECT 1 FROM public.recruits AS r WHERE r.post_id = p.post_id)
       {policy.SHAREABLE_BOARD_WHERE}
"""


class PostgresHotShareRepository:
    def __init__(self, database, db_timezone: str):
        self._db = database
        self._tz = db_timezone

    # -- 조회 -------------------------------------------------------------------------------------------------
    def web_hot_posts(self, now: datetime) -> list[dict]:
        """웹 HOT 조건을 만족하는 전체 글 (게시판 공개 범위·이력 무관, LIMIT 없음). 테스트·운영 점검용."""
        return self._db.execute(WEB_HOT_SQL + " ORDER BY likes.recent_likes DESC, p.post_id",
                                policy.sql_params(now, self._tz), fetch="all")

    def baseline_completed_at(self) -> datetime | None:
        row = self._db.execute("SELECT baseline_completed_at FROM public.hot_discord_share_state WHERE singleton", fetch="one")
        return _aware(row["baseline_completed_at"]) if row else None

    # -- baseline ----------------------------------------------------------------------------------------------
    def baseline(self, now: datetime) -> dict:
        """최초 1회: 지금 웹 HOT 조건을 만족하는 글을 모두 BASELINE으로 기록하고 완료 표시를 남긴다 (한 트랜잭션).

        공개 게시판 여부와 무관하게 기록한다: 나중에 게시판 범위가 바뀌어도 그 게시판의 과거 HOT 글이 '신규'로 나가지 않게.
        relay와 같은 advisory lock을 잡으므로 baseline 도중 relay는 기다렸다가 완료 표시를 본 뒤에만 선점한다.
        baseline의 INSERT ... SELECT 스냅샷 이후에 HOT이 된 글은 BASELINE이 아니고, 다음 relay가 신규 HOT으로 공유한다
        (누락도 중복도 없다). 이미 완료됐으면 아무것도 바꾸지 않는다 (재실행 안전).
        """
        def work(cur):
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (HOT_LOCK,))
            cur.execute("SELECT baseline_completed_at FROM public.hot_discord_share_state WHERE singleton")
            done = cur.fetchone()
            if done is not None:
                return {"already_completed": True, "baseline_completed_at": _aware(done["baseline_completed_at"]).isoformat(),
                        "baseline_rows": 0}
            params = policy.sql_params(now, self._tz) | {"now_naive": _naive(now)}
            cur.execute(f"""
                WITH {policy.LIKES_CTE}
                INSERT INTO public.hot_discord_shares (post_id, status, created_at, updated_at)
                SELECT p.post_id, 'BASELINE', %(now_naive)s, %(now_naive)s
                  FROM public.posts AS p
                  JOIN public.boards AS b ON b.board_id = p.board_id
                  JOIN likes ON likes.post_id = p.post_id
                 WHERE {policy.WEB_HOT_POST_WHERE}
                ON CONFLICT (post_id) DO NOTHING
            """, params)
            rows = cur.rowcount
            cur.execute("INSERT INTO public.hot_discord_share_state (singleton, baseline_completed_at) VALUES (TRUE, %s)",
                        (_naive(now),))
            return {"already_completed": False, "baseline_completed_at": now.astimezone(UTC).isoformat(), "baseline_rows": rows}
        return self._db.transaction(work)

    # -- 선점 --------------------------------------------------------------------------------------------------
    def claim_hot(self, now: datetime, *, limit: int, max_attempts: int, stale_minutes: int) -> list[dict] | str:
        """신규 HOT 글(과 재시도 가능한 FAILED)을 선점한다. baseline 전이면 BASELINE_REQUIRED."""
        def work(cur):
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (HOT_LOCK,))
            cur.execute("SELECT 1 FROM public.hot_discord_share_state WHERE singleton")
            if cur.fetchone() is None:
                return BASELINE_REQUIRED
            params = policy.sql_params(now, self._tz) | {"now_naive": _naive(now), "max_attempts": max_attempts, "limit": limit}
            cur.execute(CANDIDATES_SQL, params)
            claims = []
            for row in cur.fetchall():
                if not policy.is_shareable_board(row) or row["recent_likes"] < policy.HOT_MIN_LIKES:
                    log.error("SQL 조건과 정책 함수가 어긋남 post_id=%s: 공유하지 않습니다.", row["post_id"])
                    continue
                token = new_token()
                cur.execute(_UPSERT, dict(post_id=row["post_id"], token=token, now=_naive(now),
                                          expires=_naive(now + timedelta(minutes=stale_minutes)), max_attempts=max_attempts))
                if cur.fetchone() is None:
                    continue
                post = {"post_id": int(row["post_id"]), "board_id": int(row["board_id"]), "title": row["title"]}
                claims.append({"unit_id": hot_unit_id(post["post_id"]), "kind": policy.KIND_HOT, "claim_token": token,
                               "claimed_at": now, "claim_expires_at": now + timedelta(minutes=stale_minutes), "posts": [post]})
            return claims
        return self._db.transaction(work)

    # -- 결과 반영 (career_share.repository.apply_result와 같은 규칙) ----------------------------------------------
    def apply_result(self, result: dict, now: datetime, *, retry_base_minutes: int, absent_required: int = 2) -> str:
        post_id = post_id_of(result.get("unit_id"))
        if post_id is None:
            return "ignored"   # hot-<id>가 아닌 결과(취업 공유 결과 등)는 이 테이블의 것이 아니다
        token, outcome = result["claim_token"], result["outcome"]
        job_id = str(result.get("job_id") or "")

        def work(cur):
            cur.execute("SELECT post_id, status, attempt_count, absent_count, last_absent_job_id "
                        "FROM public.hot_discord_shares WHERE post_id = %s AND claim_token = %s FOR UPDATE", (post_id, token))
            row = cur.fetchone()
            if row is None:
                return "ignored"
            new = state.next_state(row["status"], outcome)
            if new is None:
                return "duplicate"
            if row["status"] == state.UNKNOWN and outcome == "ABSENT_PROVEN":
                if row["last_absent_job_id"] == job_id:
                    return "duplicate"   # 같은 확인 작업의 결과가 중복 도착: 두 번 세지 않는다
                if row["absent_count"] + 1 < absent_required:
                    cur.execute("UPDATE public.hot_discord_shares SET absent_count = absent_count + 1, "
                                "last_absent_job_id = %s, updated_at = %s WHERE post_id = %s", (job_id, _naive(now), post_id))
                    return "applied"
            if new == row["status"]:
                if outcome == "INCONCLUSIVE":
                    cur.execute("UPDATE public.hot_discord_shares SET absent_count = 0, last_absent_job_id = NULL, "
                                "updated_at = %s WHERE post_id = %s", (_naive(now), post_id))
                    return "applied"
                return "duplicate"
            retry = state.retry_at(outcome, now, row["attempt_count"], retry_base_minutes) if new == state.FAILED else None
            cur.execute(
                """UPDATE public.hot_discord_shares
                      SET status = %(new)s, next_retry_at = %(retry)s, error_message = %(error)s, updated_at = %(now)s,
                          discord_channel_id = COALESCE(%(channel)s, discord_channel_id),
                          discord_message_id = COALESCE(%(message)s, discord_message_id),
                          sent_at = CASE WHEN %(is_sent)s THEN %(now)s ELSE sent_at END,
                          last_verified_at = CASE WHEN %(is_unknown)s THEN %(now)s ELSE last_verified_at END,
                          verify_count = CASE WHEN %(is_unknown)s THEN 0 ELSE verify_count END,
                          absent_count = CASE WHEN %(is_unknown)s THEN 0 ELSE absent_count END,
                          last_absent_job_id = CASE WHEN %(is_unknown)s THEN NULL ELSE last_absent_job_id END
                    WHERE post_id = %(post_id)s""",
                dict(new=new, is_sent=new == state.SENT, is_unknown=new == state.UNKNOWN,
                     retry=_naive(retry) if retry else None,
                     error=None if new == state.SENT else str(result.get("error") or outcome)[:ERROR_LIMIT],
                     now=_naive(now), channel=result.get("channel_id") if new == state.SENT else None,
                     message=result.get("message_id") if new == state.SENT else None, post_id=post_id))
            if new == state.SENT:
                cur.execute(_STILL_SHAREABLE_SQL, {"ids": [post_id], "notice": policy.NOTICE_BOARD_NAME})
                if cur.fetchone() is None:
                    # 선점 뒤 삭제·비공개·범위 변경된 글이 게시됐다. 정상 처리로 넘기지 않는다: 사람이 Discord 메시지를 지워야 한다.
                    log.error("삭제/비공개/비공개 게시판 글이 Discord에 게시됨 post_id=%s message_id=%s: 수동 삭제 필요",
                              post_id, result.get("message_id"))
                    return "applied_post_not_shareable"
            return "applied"
        return self._db.transaction(work)

    # -- 복구 (career_share.repository.claim_verifications와 같은 규칙) ----------------------------------------------
    def claim_verifications(self, now: datetime, *, max_verifies: int, interval_minutes: int, settle_minutes: int) -> list[dict]:
        """만료된 PENDING은 UNKNOWN으로 바꾸고, 정착 대기가 지난 UNKNOWN을 마커 확인 대상으로 고른다. 재발송이 아니다."""
        def work(cur):
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (RECOVER_LOCK,))
            cur.execute("UPDATE public.hot_discord_shares SET status = 'UNKNOWN', updated_at = %(now)s, "
                        "error_message = '선점 후 결과 없음(만료)', last_verified_at = %(now)s, verify_count = 0, "
                        "absent_count = 0, last_absent_job_id = NULL "
                        "WHERE status = 'PENDING' AND claim_expires_at < %(now)s", dict(now=_naive(now)))
            cur.execute(
                """SELECT post_id, claim_token, claimed_at
                     FROM public.hot_discord_shares
                    WHERE status = 'UNKNOWN' AND verify_count < %(max)s
                      AND COALESCE(last_verified_at, updated_at)
                          <= %(now)s - make_interval(mins => CASE WHEN verify_count = 0 THEN %(settle)s ELSE %(interval)s END)
                    ORDER BY post_id""",
                dict(max=max_verifies, now=_naive(now), settle=settle_minutes, interval=interval_minutes))
            tasks = [{"unit_id": hot_unit_id(row["post_id"]), "kind": policy.KIND_HOT, "claim_token": row["claim_token"],
                      "claimed_at": _aware(row["claimed_at"]), "post_ids": [row["post_id"]]} for row in cur.fetchall()]
            if tasks:
                cur.execute("UPDATE public.hot_discord_shares SET verify_count = verify_count + 1, last_verified_at = %s "
                            "WHERE post_id = ANY(%s) AND status = 'UNKNOWN'", (_naive(now), [t["post_ids"][0] for t in tasks]))
            return tasks
        return self._db.transaction(work)

    # -- 운영 확인 ---------------------------------------------------------------------------------------------
    def summary(self, now: datetime, *, max_attempts: int) -> dict:
        rows = self._db.execute("SELECT status, COUNT(*) AS n FROM public.hot_discord_shares GROUP BY status", fetch="all")
        counts: dict = {row["status"]: int(row["n"]) for row in rows}
        exhausted = self._db.execute(
            "SELECT COUNT(*) AS n FROM public.hot_discord_shares WHERE status = 'FAILED' "
            "AND (next_retry_at IS NULL OR attempt_count >= %s)", (max_attempts,), fetch="one")
        counts["FAILED_NO_AUTO_RETRY"] = int(exhausted["n"])
        sent = self._db.execute("SELECT post_id, discord_message_id FROM public.hot_discord_shares WHERE status = 'SENT'",
                                fetch="all")
        live = {row["post_id"] for row in self._db.execute(
            _STILL_SHAREABLE_SQL, {"ids": [r["post_id"] for r in sent], "notice": policy.NOTICE_BOARD_NAME}, fetch="all")}
        # 게시 후 삭제·비공개된 글: 이번 Issue는 자동 삭제하지 않는다 (후속 Issue). 사람이 확인해 Discord에서 지운다.
        gone = [{"post_id": r["post_id"], "discord_message_id": r["discord_message_id"]} for r in sent if r["post_id"] not in live]
        counts["SENT_POST_NOT_SHAREABLE"] = gone[:50]
        done = self.baseline_completed_at()
        counts["baseline_completed_at"] = done.isoformat() if done else None
        return counts


def connect_for_lambda(application_name: str = "playmate_hot_share"):
    """career_share와 같은 연결 설정. 세션 TimeZone은 HOT 판정에 영향을 주지 않는다 (db_tz를 명시해 계산)."""
    from career_share.repository import connect_for_lambda as base
    return base(application_name)
