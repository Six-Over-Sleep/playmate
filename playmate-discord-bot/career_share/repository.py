"""공유 이력 저장소: PostgreSQL 구현(운영)과 메모리 구현(테스트용, 같은 규칙).

시각 인자는 모두 시간대가 있는 datetime이다. DB(posts, career_discord_announcements)의 시각은 UTC naive이므로
이 모듈 안에서만 변환한다. DB 연결은 기존 repositories.db.Database(연결 재사용, 트랜잭션)를 쓰되 연결 함수는 이 모듈이 만든다
(기존 connect_from_env는 config를 import하므로 DISCORD 환경변수가 필요하다).

선점 원칙 (한 글을 두 곳이 선점하지 못하게 하는 장치)
  1. pg_advisory_xact_lock으로 같은 종류의 선점 트랜잭션을 직렬화한다.
  2. INSERT ... ON CONFLICT (post_id)는 '행이 없을 때' 또는 '재시도 가능한 FAILED일 때'만 성공한다 (RETURNING이 없으면 진 것).
  3. 즉시 공유 후보는 컷오버 이후에 만든 글만, 묶음은 날짜당 1건(batch_date UNIQUE)만 만든다.
"""
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

from career_share import state
from career_share.contract import new_token
from career_share.messages import digest_unit_id, post_unit_id
from career_share.policy import (DIGEST_CATEGORY, DIGEST_SUBCATEGORIES, IMMEDIATE_CATEGORY, IMMEDIATE_SUBCATEGORIES,
                                 KIND_DIGEST, KIND_IMMEDIATE, classify)

LOCK_KEY = {KIND_IMMEDIATE: 610_163_001, KIND_DIGEST: 610_163_002, "RECOVER": 610_163_003}
ERROR_LIMIT = 500
UTC = timezone.utc


def _naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("naive datetime 금지")
    return value.astimezone(UTC).replace(tzinfo=None)


def _aware(value: datetime | None) -> datetime | None:
    return None if value is None else value.replace(tzinfo=UTC)


class CareerShareRepository(Protocol):
    def baseline(self, cutover: datetime) -> int: ...
    def claim_immediate(self, now: datetime, *, cutover: datetime, limit: int, max_attempts: int,
                        stale_minutes: int) -> list[dict]: ...
    def claim_digest(self, now: datetime, batch_date: date, *, cutover: datetime, limit: int, max_attempts: int,
                     stale_minutes: int) -> dict | None: ...
    def apply_result(self, result: dict, now: datetime, *, retry_base_minutes: int, absent_required: int = 2) -> str: ...
    def claim_verifications(self, now: datetime, *, max_verifies: int, interval_minutes: int,
                            settle_minutes: int) -> list[dict]: ...
    def summary(self, now: datetime, *, max_attempts: int) -> dict: ...


def _post(row: dict) -> dict:
    return {"post_id": int(row["post_id"]), "title": row["title"], "category_code": row["category_code"],
            "subcategory_code": row["subcategory_code"], "process_result": row.get("process_result")}


def _is_target(row: dict, kind: str) -> bool:
    target = classify(row["category_code"], row["subcategory_code"], row.get("process_result"))
    return target is not None and target.kind == kind


# ====================================================================================
class PostgresCareerShareRepository:
    def __init__(self, database):
        self._db = database

    # -- 후보 조회 SQL (즉시/묶음 공통): 허용된 분류 + 공개 + 미삭제 + 컷오버 이후 + 이력 없음/재시도 가능 ----------------
    _CANDIDATES = """
        SELECT p.post_id, p.title, c.category_code, c.subcategory_code,
               c.details ->> 'process_result' AS process_result
          FROM public.posts p
          JOIN public.career c ON c.post_id = p.post_id
          LEFT JOIN public.career_discord_announcements a ON a.post_id = p.post_id
         WHERE p.post_type = 'CAREER' AND p.post_status = 'PUBLISHED' AND p.deleted_at IS NULL
           AND p.created_at >= %(cutover)s
           AND c.category_code = %(category)s AND c.subcategory_code = ANY(%(subs)s)
           AND (a.post_id IS NULL
                OR (a.status = 'FAILED' AND a.share_kind = %(kind)s AND a.next_retry_at IS NOT NULL
                    AND a.next_retry_at <= %(now)s AND a.attempt_count < %(max_attempts)s
                    AND a.announce_date IS NULL))
         ORDER BY p.created_at ASC, p.post_id ASC
         LIMIT %(limit)s
    """
    _UPSERT = """
        INSERT INTO public.career_discord_announcements AS a
               (post_id, category_code, share_kind, status, attempt_count, batch_id,
                claim_token, claimed_at, claim_expires_at, updated_at)
        VALUES (%(post_id)s, %(category)s, %(kind)s, 'PENDING', 1, %(batch_id)s,
                %(token)s, %(now)s, %(expires)s, %(now)s)
        ON CONFLICT (post_id) DO UPDATE
           SET status = 'PENDING', batch_id = EXCLUDED.batch_id,
               attempt_count = a.attempt_count + 1, claim_token = EXCLUDED.claim_token,
               claimed_at = EXCLUDED.claimed_at, claim_expires_at = EXCLUDED.claim_expires_at,
               next_retry_at = NULL, error_message = NULL, discord_message_id = NULL, sent_at = NULL,
               verify_count = 0, last_verified_at = NULL, absent_count = 0, last_absent_job_id = NULL,
               updated_at = EXCLUDED.updated_at
         WHERE a.status = 'FAILED' AND a.share_kind = EXCLUDED.share_kind AND a.next_retry_at IS NOT NULL
           AND a.next_retry_at <= %(now)s AND a.attempt_count < %(max_attempts)s
           AND a.announce_date IS NULL
        RETURNING post_id
    """

    def baseline(self, cutover: datetime) -> int:
        """컷오버 이전 대상 글을 BASELINE으로 기록한다 (이력이 없는 글만). 컷오버 필터와 함께 쓰는 이중 안전장치다."""
        return self._db.execute(
            """
            INSERT INTO public.career_discord_announcements (post_id, category_code, status, share_kind)
            SELECT p.post_id, c.category_code, 'BASELINE', 'LEGACY'
              FROM public.posts p JOIN public.career c ON c.post_id = p.post_id
             WHERE p.post_type = 'CAREER' AND p.created_at < %s
               AND ((c.category_code = %s AND c.subcategory_code = ANY(%s))
                    OR (c.category_code = %s AND c.subcategory_code = ANY(%s)))
            ON CONFLICT (post_id) DO NOTHING
            """,
            (_naive(cutover), IMMEDIATE_CATEGORY, list(IMMEDIATE_SUBCATEGORIES), DIGEST_CATEGORY, list(DIGEST_SUBCATEGORIES)),
        )

    def _claim(self, cur, kind, category, subs, now, cutover, limit, max_attempts, stale_minutes, batch_id=None):
        cur.execute(self._CANDIDATES, dict(cutover=_naive(cutover), category=category, subs=list(subs), kind=kind,
                                           now=_naive(now), max_attempts=max_attempts, limit=limit))
        claimed = []
        for row in cur.fetchall():
            if not _is_target(row, kind):
                continue  # SQL 조건과 정책 함수가 어긋나면 공유하지 않는다
            token = new_token()
            cur.execute(self._UPSERT, dict(post_id=row["post_id"], category=row["category_code"],
                                           kind=kind, batch_id=batch_id, token=token,
                                           now=_naive(now), expires=_naive(now + timedelta(minutes=stale_minutes)),
                                           max_attempts=max_attempts))
            if cur.fetchone() is not None:
                claimed.append((_post(row), token))
        return claimed

    def claim_immediate(self, now, *, cutover, limit, max_attempts, stale_minutes):
        def work(cur):
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY[KIND_IMMEDIATE],))
            claims = self._claim(cur, KIND_IMMEDIATE, IMMEDIATE_CATEGORY, IMMEDIATE_SUBCATEGORIES, now, cutover, limit,
                                 max_attempts, stale_minutes)
            return [{"unit_id": post_unit_id(post["post_id"]), "kind": KIND_IMMEDIATE, "claim_token": token,
                     "claimed_at": now, "claim_expires_at": now + timedelta(minutes=stale_minutes), "posts": [post]}
                    for post, token in claims]
        return self._db.transaction(work)

    def claim_digest(self, now, batch_date, *, cutover, limit, max_attempts, stale_minutes):
        batch_id = digest_unit_id(batch_date)

        def work(cur):
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY[KIND_DIGEST],))
            cur.execute("SELECT 1 FROM public.career_discord_share_batches WHERE batch_date = %s", (batch_date,))
            if cur.fetchone() is not None:
                return None  # 이 날짜의 묶음은 이미 만들어졌다 (같은 이벤트의 중복 실행)
            claimed = self._claim(cur, KIND_DIGEST, DIGEST_CATEGORY, DIGEST_SUBCATEGORIES, now, cutover, limit,
                                  max_attempts, stale_minutes, batch_id=batch_id)
            if not claimed:
                return None
            token = new_token()
            # 글 행의 토큰을 배치 토큰 하나로 맞춘다 (결과는 배치 단위로 오므로 같은 토큰이어야 한다)
            cur.execute("UPDATE public.career_discord_announcements SET claim_token = %s WHERE batch_id = %s "
                        "AND claim_token = ANY(%s)", (token, batch_id, [t for _, t in claimed]))
            cur.execute("INSERT INTO public.career_discord_share_batches (batch_date, created_at) VALUES (%s, %s)",
                        (batch_date, _naive(now)))
            return {"unit_id": batch_id, "kind": KIND_DIGEST, "claim_token": token, "claimed_at": now,
                    "claim_expires_at": now + timedelta(minutes=stale_minutes), "posts": [post for post, _ in claimed],
                    "batch_date": batch_date}
        return self._db.transaction(work)

    def _unit_where(self, unit_id: str):
        if unit_id.startswith("post-"):
            return "post_id = %s", (int(unit_id[5:]),)
        return "batch_id = %s", (unit_id,)

    def apply_result(self, result, now, *, retry_base_minutes, absent_required=2):
        unit_id, token, outcome = result["unit_id"], result["claim_token"], result["outcome"]
        job_id = str(result.get("job_id") or "")
        where, params = self._unit_where(unit_id)

        def work(cur):
            # announce_date IS NULL: 기존 18:00 공지가 선점한 행은 이 기능의 행이 아니므로 결과를 반영하지 않는다.
            cur.execute(f"SELECT post_id, status, attempt_count, absent_count, last_absent_job_id "
                        f"FROM public.career_discord_announcements WHERE {where} AND claim_token = %s "
                        f"AND share_kind <> 'LEGACY' AND announce_date IS NULL ORDER BY post_id FOR UPDATE",
                        params + (token,))
            rows = cur.fetchall()
            if not rows:
                return "ignored"
            changed = False
            for row in rows:
                new = state.next_state(row["status"], outcome)
                if new is None:
                    continue
                if row["status"] == state.UNKNOWN and outcome == "ABSENT_PROVEN":
                    if row["last_absent_job_id"] == job_id:
                        continue  # 같은 확인 작업의 결과가 중복 도착: 두 번 세지 않는다
                    if row["absent_count"] + 1 < absent_required:
                        cur.execute("UPDATE public.career_discord_announcements SET absent_count = absent_count + 1, "
                                    "last_absent_job_id = %s, updated_at = %s WHERE post_id = %s",
                                    (job_id, _naive(now), row["post_id"]))
                        changed = True
                        continue
                if new == row["status"]:
                    if outcome == "INCONCLUSIVE":
                        cur.execute("UPDATE public.career_discord_announcements SET absent_count = 0, "
                                    "last_absent_job_id = NULL, updated_at = %s WHERE post_id = %s",
                                    (_naive(now), row["post_id"]))
                        changed = True
                    continue
                retry = state.retry_at(outcome, now, row["attempt_count"], retry_base_minutes) if new == state.FAILED else None
                cur.execute(
                    """UPDATE public.career_discord_announcements
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
                         message=result.get("message_id") if new == state.SENT else None, post_id=row["post_id"]))
                changed = True
            return "applied" if changed else "duplicate"
        return self._db.transaction(work)

    def claim_verifications(self, now, *, max_verifies, interval_minutes, settle_minutes):
        """확인 대상(마커 확인 작업)을 고른다. 재발송이 아니다.

        - 선점 후 claim_expires_at이 지나도 결과가 없는 PENDING은 UNKNOWN으로 바꾸고 그 시각을 정착 기준점(last_verified_at)으로 한다.
        - UNKNOWN은 기준점 + (첫 확인은 settle_minutes, 이후는 interval_minutes)가 지난 뒤에만 확인한다.
          UNKNOWN 직후에는 확인하지 않는다: 클라이언트 타임아웃 뒤에 Discord가 뒤늦게 메시지를 저장할 수 있다.
        - announce_date가 있는 행(기존 18:00 공지가 선점)은 건드리지 않는다.
        """
        def work(cur):
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY["RECOVER"],))
            cur.execute("UPDATE public.career_discord_announcements SET status = 'UNKNOWN', updated_at = %(now)s, "
                        "error_message = '선점 후 결과 없음(만료)', last_verified_at = %(now)s, verify_count = 0, "
                        "absent_count = 0, last_absent_job_id = NULL "
                        "WHERE status = 'PENDING' AND share_kind <> 'LEGACY' AND announce_date IS NULL "
                        "AND claim_expires_at < %(now)s", dict(now=_naive(now)))
            cur.execute(
                """SELECT post_id, share_kind, batch_id, claim_token, claimed_at
                     FROM public.career_discord_announcements
                    WHERE status = 'UNKNOWN' AND share_kind <> 'LEGACY' AND announce_date IS NULL
                      AND verify_count < %(max)s
                      AND COALESCE(last_verified_at, updated_at)
                          <= %(now)s - make_interval(mins => CASE WHEN verify_count = 0 THEN %(settle)s ELSE %(interval)s END)
                    ORDER BY post_id""",
                dict(max=max_verifies, now=_naive(now), settle=settle_minutes, interval=interval_minutes))
            units: dict[str, dict] = {}
            for row in cur.fetchall():
                unit_id = row["batch_id"] or post_unit_id(row["post_id"])
                unit = units.setdefault(unit_id, {"unit_id": unit_id, "kind": row["share_kind"],
                                                  "claim_token": row["claim_token"], "claimed_at": _aware(row["claimed_at"]),
                                                  "post_ids": []})
                unit["post_ids"].append(row["post_id"])
            for unit in units.values():
                cur.execute("UPDATE public.career_discord_announcements SET verify_count = verify_count + 1, "
                            "last_verified_at = %s WHERE post_id = ANY(%s) AND status = 'UNKNOWN'",
                            (_naive(now), unit["post_ids"]))
            return list(units.values())
        return self._db.transaction(work)

    def summary(self, now, *, max_attempts):
        rows = self._db.execute(
            "SELECT status, COUNT(*) AS n FROM public.career_discord_announcements WHERE share_kind <> 'LEGACY' GROUP BY status",
            fetch="all")
        counts = {row["status"]: int(row["n"]) for row in rows}
        exhausted = self._db.execute(
            "SELECT COUNT(*) AS n FROM public.career_discord_announcements WHERE share_kind <> 'LEGACY' "
            "AND status = 'FAILED' AND (next_retry_at IS NULL OR attempt_count >= %s)", (max_attempts,), fetch="one")
        counts["FAILED_NO_AUTO_RETRY"] = int(exhausted["n"])
        foreign = self._db.execute(
            "SELECT COUNT(*) AS n FROM public.career_discord_announcements WHERE share_kind <> 'LEGACY' AND announce_date IS NOT NULL",
            fetch="one")
        counts["CLAIMED_BY_LEGACY_NOTICE"] = int(foreign["n"])   # 0이 아니면 18:00 공지가 켜져 있다는 신호 (컷오버 위반)
        return counts


def connect_for_lambda(application_name: str = "playmate_career_share"):
    """환경변수(DB_*)로 연결한다. 기존 repositories.db.connect_from_env와 같은 설정이지만 config를 import하지 않는다."""
    import os

    import psycopg
    return psycopg.connect(
        host=os.environ["DB_HOST"], port=int(os.environ.get("DB_PORT") or 5432), user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"], dbname=os.environ["DB_NAME"], sslmode=os.environ.get("DB_SSLMODE") or "require",
        connect_timeout=10, autocommit=True, application_name=application_name,
        options="-c TimeZone=Asia/Seoul -c statement_timeout=15000")


# ====================================================================================
class InMemoryCareerShareRepository:
    """같은 규칙의 메모리 구현. 테스트에서 posts를 add_post로 넣고 선점/결과 흐름을 확인한다."""

    def __init__(self):
        self._lock = threading.RLock()
        self.posts: dict[int, dict] = {}
        self.rows: dict[int, dict] = {}
        self.batches: dict[date, dict] = {}

    def add_post(self, post_id, *, title="제목", category="reviews", sub="INTERVIEW", created_at=None, process_result=None,
                 post_type="CAREER", post_status="PUBLISHED", deleted=False):
        self.posts[post_id] = dict(post_id=post_id, title=title, category_code=category, subcategory_code=sub,
                                   process_result=process_result, post_type=post_type, post_status=post_status,
                                   deleted_at=datetime.now(UTC) if deleted else None,
                                   created_at=created_at or datetime.now(UTC))

    def baseline(self, cutover):
        with self._lock:
            added = 0
            for post in self.posts.values():
                if post["post_type"] == "CAREER" and post["created_at"] < cutover and post["post_id"] not in self.rows \
                        and (_is_target(post, KIND_IMMEDIATE) or _is_target(post, KIND_DIGEST)):
                    self.rows[post["post_id"]] = self._row(post, "LEGACY", "BASELINE")
                    added += 1
            return added

    @staticmethod
    def _row(post, kind, status):
        return dict(post_id=post["post_id"], category_code=post["category_code"],
                    share_kind=kind, status=status, attempt_count=0, batch_id=None, claim_token=None, claimed_at=None,
                    claim_expires_at=None, next_retry_at=None, verify_count=0, last_verified_at=None, absent_count=0,
                    last_absent_job_id=None, announce_date=None, discord_message_id=None, discord_channel_id=None, error_message=None, sent_at=None)

    def _candidates(self, kind, now, cutover, limit, max_attempts):
        found = []
        for post in sorted(self.posts.values(), key=lambda p: (p["created_at"], p["post_id"])):
            if not (post["post_type"] == "CAREER" and post["post_status"] == "PUBLISHED" and post["deleted_at"] is None
                    and post["created_at"] >= cutover and _is_target(post, kind)):
                continue
            row = self.rows.get(post["post_id"])
            if row is None or (row["status"] == "FAILED" and row["share_kind"] == kind and row["next_retry_at"] is not None
                               and row["next_retry_at"] <= now and row["attempt_count"] < max_attempts
                               and row["announce_date"] is None):
                found.append(post)
            if len(found) >= limit:
                break
        return found

    def _claim(self, kind, now, cutover, limit, max_attempts, stale_minutes, batch_id=None):
        claimed = []
        for post in self._candidates(kind, now, cutover, limit, max_attempts):
            row = self.rows.get(post["post_id"]) or self._row(post, kind, "PENDING")
            token = new_token()
            row.update(status="PENDING", share_kind=kind, attempt_count=row["attempt_count"] + 1, batch_id=batch_id,
                       claim_token=token, claimed_at=now, claim_expires_at=now + timedelta(minutes=stale_minutes),
                       next_retry_at=None, error_message=None, discord_message_id=None, sent_at=None, verify_count=0,
                       last_verified_at=None, absent_count=0, last_absent_job_id=None)
            self.rows[post["post_id"]] = row
            claimed.append((_post(post), token))
        return claimed

    def claim_immediate(self, now, *, cutover, limit, max_attempts, stale_minutes):
        with self._lock:
            return [{"unit_id": post_unit_id(p["post_id"]), "kind": KIND_IMMEDIATE, "claim_token": t, "claimed_at": now,
                     "claim_expires_at": now + timedelta(minutes=stale_minutes), "posts": [p]}
                    for p, t in self._claim(KIND_IMMEDIATE, now, cutover, limit, max_attempts, stale_minutes)]

    def claim_digest(self, now, batch_date, *, cutover, limit, max_attempts, stale_minutes):
        with self._lock:
            if batch_date in self.batches:
                return None
            batch_id = digest_unit_id(batch_date)
            claimed = self._claim(KIND_DIGEST, now, cutover, limit, max_attempts, stale_minutes, batch_id)
            if not claimed:
                return None
            token = new_token()
            for post, _ in claimed:
                self.rows[post["post_id"]]["claim_token"] = token
            self.batches[batch_date] = dict(created_at=now)
            return {"unit_id": batch_id, "kind": KIND_DIGEST, "claim_token": token, "claimed_at": now,
                    "claim_expires_at": now + timedelta(minutes=stale_minutes), "posts": [p for p, _ in claimed],
                    "batch_date": batch_date}

    def _unit_rows(self, unit_id, token):
        if unit_id.startswith("post-"):
            rows = [r for r in self.rows.values() if r["post_id"] == int(unit_id[5:])]
        else:
            rows = [r for r in self.rows.values() if r["batch_id"] == unit_id]
        return [r for r in rows if r["claim_token"] == token and r["share_kind"] != "LEGACY" and r["announce_date"] is None]

    def apply_result(self, result, now, *, retry_base_minutes, absent_required=2):
        with self._lock:
            unit_id, token, outcome = result["unit_id"], result["claim_token"], result["outcome"]
            job_id = str(result.get("job_id") or "")
            rows = self._unit_rows(unit_id, token)
            if not rows:
                return "ignored"
            changed = False
            for row in rows:
                new = state.next_state(row["status"], outcome)
                if new is None:
                    continue
                if row["status"] == state.UNKNOWN and outcome == "ABSENT_PROVEN":
                    if row["last_absent_job_id"] == job_id:
                        continue
                    if row["absent_count"] + 1 < absent_required:
                        row["absent_count"] += 1
                        row["last_absent_job_id"] = job_id
                        changed = True
                        continue
                if new == row["status"]:
                    if outcome == "INCONCLUSIVE":
                        row["absent_count"], row["last_absent_job_id"] = 0, None
                        changed = True
                    continue
                row["status"] = new
                row["next_retry_at"] = state.retry_at(outcome, now, row["attempt_count"], retry_base_minutes) \
                    if new == state.FAILED else None
                row["error_message"] = None if new == state.SENT else str(result.get("error") or outcome)[:ERROR_LIMIT]
                if new == state.SENT:
                    row.update(discord_message_id=result.get("message_id"), discord_channel_id=result.get("channel_id"),
                               sent_at=now)
                if new == state.UNKNOWN:
                    row.update(last_verified_at=now, verify_count=0, absent_count=0, last_absent_job_id=None)
                changed = True
            return "applied" if changed else "duplicate"

    def claim_verifications(self, now, *, max_verifies, interval_minutes, settle_minutes):
        with self._lock:
            for row in self.rows.values():
                if row["status"] == "PENDING" and row["share_kind"] != "LEGACY" and row["announce_date"] is None \
                        and row["claim_expires_at"] < now:
                    row.update(status="UNKNOWN", error_message="선점 후 결과 없음(만료)", last_verified_at=now,
                               verify_count=0, absent_count=0, last_absent_job_id=None)
            units: dict[str, dict] = {}
            for row in sorted(self.rows.values(), key=lambda r: r["post_id"]):
                if row["status"] != "UNKNOWN" or row["share_kind"] == "LEGACY" or row["announce_date"] is not None \
                        or row["verify_count"] >= max_verifies:
                    continue
                wait = settle_minutes if row["verify_count"] == 0 else interval_minutes
                if (row["last_verified_at"] or now) > now - timedelta(minutes=wait):
                    continue
                unit_id = row["batch_id"] or post_unit_id(row["post_id"])
                unit = units.setdefault(unit_id, {"unit_id": unit_id, "kind": row["share_kind"],
                                                  "claim_token": row["claim_token"], "claimed_at": row["claimed_at"],
                                                  "post_ids": []})
                unit["post_ids"].append(row["post_id"])
                row["verify_count"] += 1
                row["last_verified_at"] = now
            return list(units.values())

    def summary(self, now, *, max_attempts):
        with self._lock:
            counts: dict[str, int] = {}
            for row in self.rows.values():
                if row["share_kind"] != "LEGACY":
                    counts[row["status"]] = counts.get(row["status"], 0) + 1
            counts["FAILED_NO_AUTO_RETRY"] = sum(
                1 for r in self.rows.values() if r["share_kind"] != "LEGACY" and r["status"] == "FAILED"
                and (r["next_retry_at"] is None or r["attempt_count"] >= max_attempts))
            counts["CLAIMED_BY_LEGACY_NOTICE"] = sum(
                1 for r in self.rows.values() if r["share_kind"] != "LEGACY" and r["announce_date"] is not None)
            return counts
