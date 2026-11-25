"""Meeting outbox. Result changes and outbox resolution share a transaction."""
import json
import logging
from uuid import uuid4

from datetime import datetime
from zoneinfo import ZoneInfo

from meeting_share.contract import CREATE_MANUAL_REASONS

KST = ZoneInfo("Asia/Seoul")
log = logging.getLogger(__name__)
ELIGIBLE = """EXISTS (SELECT 1 FROM public.recruits r JOIN public.posts p ON p.post_id=r.post_id
    WHERE r.recruit_id=%s AND r.recruit_mode IN ('regular','short') AND p.post_status IS DISTINCT FROM 'DELETED'
    AND COALESCE(r.deadline_at, CASE r.recruit_mode WHEN 'regular' THEN r.regular_start_date::timestamp
        WHEN 'short' THEN date_trunc('day',r.meeting_start) END) BETWEEN %s::timestamp AND %s)"""
RETRYABLE = """rc.sync_status='FAILED' AND rc.discord_text_channel_id IS NULL
    AND COALESCE(rc.sync_error,'') NOT LIKE 'MANUAL:%%'
    AND COALESCE(rc.sync_error,'') NOT LIKE 'ABORTED:%%'
    AND (rc.sync_error='RETRYABLE: approval window elapsed without a permit'
         OR rc.updated_at < now()-interval '300 seconds')"""


class MeetingJobs:
    def __init__(self, db):
        self.db = db

    def heartbeat(self):
        self.db.execute("UPDATE public.discord_meeting_control SET result_seen_at=clock_timestamp() WHERE singleton")

    def reset_heartbeat(self):
        self.db.execute("UPDATE public.discord_meeting_control SET result_seen_at=NULL WHERE singleton")

    def schedule(self, target):
        def work(cur):
            cur.execute("""
                SELECT *, result_seen_at > clock_timestamp() - interval '90 seconds' AS ready
                FROM public.discord_meeting_control WHERE singleton FOR SHARE
            """)
            control = cur.fetchone()
            if not control or not control["ready"]:
                return
            if target["create"] and control["create_owner"] == "lambda":
                now = datetime.now(KST).replace(tzinfo=None)
                candidate = ELIGIBLE.replace("r.recruit_id=%s", "r.recruit_id=outer_r.recruit_id")
                cur.execute(f"""
                    SELECT outer_r.recruit_id FROM public.recruits outer_r
                    LEFT JOIN public.recruit_discord_channels rc USING(recruit_id)
                    WHERE {candidate}
                      AND (rc.recruit_id IS NULL OR ({RETRYABLE}))
                    ORDER BY outer_r.deadline_at NULLS LAST,outer_r.recruit_id LIMIT 5
                """, (target["cutover"], now))
                for row in cur.fetchall():
                    rid = row["recruit_id"]
                    cur.execute(f"""
                        INSERT INTO public.recruit_discord_channels AS rc(recruit_id,sync_status)
                        SELECT %s,'PENDING' WHERE {ELIGIBLE}
                        ON CONFLICT(recruit_id) DO UPDATE SET sync_status='PENDING',sync_error=NULL,updated_at=now()
                        WHERE {RETRYABLE} AND {ELIGIBLE}
                        RETURNING recruit_id
                    """, (rid, rid, target["cutover"], now, rid, target["cutover"], now))
                    if cur.fetchone():
                        self._insert(cur, rid, "create", target)
            if target["permissions"] and control["permission_owner"] == "lambda":
                # A queued but unapproved write must not delay a newer cancellation.
                cur.execute("""
                    UPDATE public.discord_meeting_jobs j
                    SET finished_at=clock_timestamp(),outcome='superseded'
                    WHERE kind='permissions' AND finished_at IS NULL AND approved_at IS NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM public.discord_meeting_permission_snapshot(j.recruit_id,j.member_id) s
                          WHERE s.fingerprint=j.fingerprint AND s.discord_id=j.target->>'user_id'
                            AND j.target->>'visibility'=%s
                      )
                """, (target["visibility"],))
                cur.execute("""
                    WITH candidates AS (
                       SELECT rm.recruit_id,rm.member_id FROM public.recruit_members rm
                       WHERE rm.status IN ('JOINED','CANCELED')
                       UNION
                       SELECT DISTINCT j.recruit_id,j.member_id FROM public.discord_meeting_jobs j
                       WHERE j.approved_action='grant'
                    )
                    SELECT c.*, s.*, rc.discord_text_channel_id
                      FROM candidates c
                      JOIN public.recruit_discord_channels rc USING (recruit_id)
                      CROSS JOIN LATERAL public.discord_meeting_permission_snapshot(c.recruit_id,c.member_id) s
                      LEFT JOIN LATERAL (
                         SELECT j.finished_at,j.fingerprint,j.outcome,j.target->>'visibility' AS visibility
                         FROM public.discord_meeting_jobs j
                         WHERE j.kind='permissions' AND j.recruit_id=c.recruit_id AND j.member_id=c.member_id
                         ORDER BY j.created_at DESC LIMIT 1
                      ) last ON TRUE
                     WHERE s.discord_id IS NOT NULL
                       AND ((s.desired='revoke' AND s.managed) OR (s.desired='grant' AND %s))
                       AND (last.fingerprint IS NULL OR (last.finished_at IS NOT NULL AND
                            (last.fingerprint<>s.fingerprint OR last.visibility IS DISTINCT FROM %s
                             OR last.finished_at < now()-CASE
                                 WHEN last.outcome='member_absent' THEN interval '1 hour'
                                 WHEN last.outcome='applied' AND NOT (
                                     s.desired='revoke' AND EXISTS (
                                         SELECT 1 FROM public.discord_meeting_jobs recent
                                         WHERE recent.kind='permissions' AND recent.recruit_id=c.recruit_id
                                           AND recent.member_id=c.member_id AND recent.approved_action='grant'
                                           AND recent.approved_at > now()-interval '10 minutes'
                                     )
                                 ) THEN interval '24 hours'
                                 ELSE interval '60 seconds' END)))
                     ORDER BY (s.desired='revoke') DESC,last.finished_at NULLS FIRST,c.recruit_id,c.member_id
                     LIMIT 20
                """, (target["grant"], target["visibility"]))
                for row in cur.fetchall():
                    self._insert(cur, row["recruit_id"], "permissions",
                                 {**target, "user_id": row["discord_id"], "channel_id": row["discord_text_channel_id"]},
                                 row["member_id"], row["fingerprint"])
        self.db.transaction(work)

    @staticmethod
    def _insert(cur, rid, kind, target, member_id=None, fingerprint=None):
        public_target = {key: value for key, value in target.items()
                         if key in ("guild_id", "category_id", "visibility", "channel_id", "user_id")}
        cur.execute("""
            INSERT INTO public.discord_meeting_jobs(job_id,recruit_id,kind,target,member_id,fingerprint)
            VALUES (%s,%s,%s,%s::jsonb,%s,%s) ON CONFLICT DO NOTHING
        """, (uuid4(), rid, kind, json.dumps(public_target), member_id, fingerprint))

    def pending(self):
        return self.db.execute("""
            SELECT j.*, approved_at IS NOT NULL AS verify,
                   extract(epoch FROM j.created_at)::float8 + 300 AS approve_before
            FROM public.discord_meeting_jobs j CROSS JOIN public.discord_meeting_control c
            WHERE c.singleton AND j.finished_at IS NULL
              AND c.result_seen_at > clock_timestamp()-interval '90 seconds'
              AND ((kind='create' AND (create_owner='lambda' OR (create_owner='paused' AND approved_at IS NOT NULL))) OR
                   (kind='permissions' AND permission_owner='lambda'))
              AND (sent_at IS NULL OR (approved_at IS NOT NULL AND sent_at < clock_timestamp()-interval '60 seconds'))
              AND (approved_at IS NULL OR (kind='create' AND approved_at < clock_timestamp()-interval '90 seconds'))
            ORDER BY created_at LIMIT 30
        """, fetch="all")

    def sent(self, job_id):
        self.db.execute("UPDATE public.discord_meeting_jobs SET sent_at=clock_timestamp() WHERE job_id=%s", (job_id,))

    def expire(self):
        def work(cur):
            cur.execute("""
                UPDATE public.discord_meeting_jobs SET finished_at=clock_timestamp(),outcome='expired'
                WHERE finished_at IS NULL AND (
                    (kind='create' AND approved_at IS NULL AND approval_id IS NULL
                     AND created_at <= clock_timestamp()-interval '5 minutes')
                    OR created_at <= clock_timestamp()-interval '10 minutes'
                )
                RETURNING job_id,recruit_id,kind,approved_at,approval_id
            """)
            rows = cur.fetchall()
            for row in rows:
                if row["kind"] == "create":
                    if row["approved_at"] is None and row["approval_id"] is None:
                        cur.execute("""
                            UPDATE public.recruit_discord_channels
                            SET sync_status='FAILED',sync_error='RETRYABLE: approval window elapsed without a permit',
                                updated_at=now()
                            WHERE recruit_id=%s AND sync_status='PENDING' AND discord_text_channel_id IS NULL
                        """, (row["recruit_id"],))
                    else:
                        self._hold(cur, row["recruit_id"], f"unconfirmed generation {row['job_id']}")
            return len(rows)
        expired = self.db.transaction(work)
        if expired:
            log.warning("meeting jobs expired count=%s", expired)

    @staticmethod
    def _hold(cur, rid, reason):
        cur.execute("""
            UPDATE public.recruit_discord_channels SET sync_status='FAILED',sync_error=%s,updated_at=now()
            WHERE recruit_id=%s AND sync_status='PENDING' AND discord_text_channel_id IS NULL
        """, (f"MANUAL: {reason}", rid))

    def apply(self, result):
        def work(cur):
            cur.execute("SELECT * FROM public.discord_meeting_jobs WHERE job_id=%s FOR UPDATE", (result["job_id"],))
            job = cur.fetchone()
            if not job or job["kind"] != result["kind"]:
                return "ignored"
            outcome = result["outcome"]
            late_create = (job["kind"] == "create" and job["outcome"] in ("expired", "skipped")
                           and job["approved_at"] is not None and job["approval_id"] is not None
                           and outcome in ("applied", "found"))
            if job["finished_at"] and not late_create:
                return "ignored"
            if outcome in ("applied", "unknown", "rejected") and (
                    not job["approval_id"] or str(job["approval_id"]) != result.get("approval_id")):
                return "ignored"
            manual_reason = (result.get("reason") if job["kind"] == "create" and outcome == "skipped" else None)
            if (outcome in ("skipped", "member_absent") and manual_reason not in CREATE_MANUAL_REASONS
                    and (job["approved_at"] or job["kind"] == "create")):
                return "ignored"
            if job["kind"] == "create":
                if outcome == "unknown":
                    return "verify_pending"
                if outcome in ("applied", "found"):
                    if late_create:
                        cur.execute("""
                            UPDATE public.discord_meeting_jobs SET result_channel_id=%s
                            WHERE job_id=%s AND result_channel_id IS NULL
                        """, (result["channel_id"], result["job_id"]))
                        if not cur.rowcount:
                            return "ignored"
                        if job["outcome"] == "skipped":
                            return "manual"  # conflict evidence must not supersede the manual hold
                    cur.execute("""
                        SELECT 1 FROM public.recruits r JOIN public.posts p ON p.post_id=r.post_id
                        WHERE r.recruit_id=%s AND r.recruit_mode IN ('regular','short')
                          AND p.post_status IS DISTINCT FROM 'DELETED'
                          AND COALESCE(r.deadline_at,CASE r.recruit_mode WHEN 'regular' THEN r.regular_start_date::timestamp
                                WHEN 'short' THEN date_trunc('day',r.meeting_start) END)
                              <= clock_timestamp() AT TIME ZONE 'Asia/Seoul'
                        FOR SHARE OF r,p
                    """, (job["recruit_id"],))
                    if cur.fetchone():
                        cur.execute("""
                            UPDATE public.recruit_discord_channels rc
                            SET sync_status='SUCCESS', discord_text_channel_id=%s, sync_error=NULL,
                                synced_at=now(), last_activity_at=now(), updated_at=now()
                            WHERE rc.recruit_id=%s AND rc.discord_text_channel_id IS NULL
                              AND rc.discord_deleted_at IS NULL
                              AND ((NOT %s AND rc.sync_status='PENDING')
                                OR (%s AND rc.sync_status='FAILED' AND rc.sync_error=%s AND NOT EXISTS (
                                    SELECT 1 FROM public.discord_meeting_jobs newer
                                    WHERE newer.kind='create' AND newer.recruit_id=rc.recruit_id
                                      AND newer.job_id<>%s AND newer.created_at>=%s
                                )))
                              AND NOT EXISTS (SELECT 1 FROM public.recruit_discord_channels x
                                              WHERE x.discord_text_channel_id=%s)
                        """, (result["channel_id"], job["recruit_id"], late_create, late_create,
                              f"MANUAL: unconfirmed generation {job['job_id']}", job["job_id"],
                              job["created_at"], result["channel_id"]))
                        if not cur.rowcount:
                            if late_create:
                                return "manual"
                            self._hold(cur, job["recruit_id"], "channel binding could not be confirmed")
                    else:
                        if late_create:
                            return "manual"
                        self._hold(cur, job["recruit_id"], "recruit changed after dispatch")
                else:
                    reason = (f"{manual_reason} - {CREATE_MANUAL_REASONS[manual_reason]}"
                              if manual_reason in CREATE_MANUAL_REASONS
                              else "Discord write rejected; inspect before retry")
                    self._hold(cur, job["recruit_id"], reason)
            cur.execute("""
                UPDATE public.discord_meeting_jobs
                SET outcome=%s,finished_at=clock_timestamp(),result_channel_id=%s WHERE job_id=%s
            """, (outcome, result.get("channel_id") if job["kind"] == "create" else None, result["job_id"]))
            return "applied"
        return self.db.transaction(work)
