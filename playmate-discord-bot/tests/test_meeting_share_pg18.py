"""Issue #188 integration. Only a verified, dedicated test cluster is accepted."""
import hashlib
import hmac
import json
import os
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import psycopg
import psycopg2
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg2.extras import RealDictCursor

from app.routers import discord_meeting_internal as api
from discord_rest.errors import DiscordForbidden, DiscordRequestError
from discord_rest.permissions import PARTICIPANT_ALLOW
from meeting_share.repository import MeetingJobs
from meeting_share.runner import Consumer, MeetingResults, tick
from meeting_share.worker_lambda import MeetingWorker
from repositories.db import Database
from test_meeting_share import CAT, CHANNEL, CREATED, GUILD, TARGET, USER

ROOT = Path(__file__).resolve().parents[2]
DSN = os.environ.get("PLAYMATE_TEST_PG_DSN")
CLUSTER = os.environ.get("ISSUE188_TEST_CLUSTER_ID")
SCOPE = {**TARGET, "create": True, "permissions": True, "grant": True, "cutover": "2000-01-01"}
SCHEMA = """
CREATE TABLE public.posts (post_id bigint PRIMARY KEY, title text, post_status text);
CREATE TABLE public.recruits (recruit_id bigint PRIMARY KEY, post_id bigint NOT NULL REFERENCES public.posts,
  recruit_mode text, deadline_at timestamp, regular_start_date date, meeting_start timestamp);
CREATE TABLE public.members (member_id bigint PRIMARY KEY, discord_id varchar(30) UNIQUE, member_status text);
CREATE TABLE public.recruit_members (recruit_id bigint REFERENCES public.recruits, member_id bigint REFERENCES public.members,
  status text, joined_at timestamp, canceled_at timestamp, PRIMARY KEY(recruit_id,member_id));
CREATE TABLE public.recruit_discord_channels (
  recruit_id bigint PRIMARY KEY REFERENCES public.recruits, discord_text_channel_id varchar(32) UNIQUE,
  discord_category_id varchar(32) UNIQUE, sync_status text NOT NULL CHECK(sync_status IN ('PENDING','SUCCESS','FAILED')),
  sync_error text, created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now(),
  synced_at timestamptz, last_activity_at timestamptz, discord_deleted_at timestamptz);
"""


def connect(**kwargs):
    return psycopg.connect(DSN, autocommit=True, **kwargs)


@unittest.skipUnless(DSN and CLUSTER, "requires an independently identified Issue #188 PostgreSQL 18 cluster")
class MeetingPg18(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        params = psycopg.conninfo.conninfo_to_dict(DSN)
        if (tuple(params.get(k) for k in ("host", "dbname", "user"))
                != ("127.0.0.1", "playmate_issue188_test", "issue188_test")
                or set(params) - {"host", "port", "dbname", "user", "password", "sslmode", "connect_timeout"}
                or not params.get("port")):
            raise RuntimeError("refusing non-Issue #188 DSN")
        with connect() as conn:
            row = conn.execute("""
                SELECT current_database(), current_user, current_setting('server_version_num'),
                       system_identifier::text FROM pg_control_system()
            """).fetchone()
            if row != ("playmate_issue188_test", "issue188_test", "180007", CLUSTER):
                raise RuntimeError("PostgreSQL 18.7 isolated cluster identity mismatch")
            if conn.execute("""
                SELECT EXISTS (
                    SELECT FROM pg_class WHERE relnamespace='public'::regnamespace
                ) OR EXISTS (
                    SELECT FROM pg_proc WHERE pronamespace='public'::regnamespace
                )
            """).fetchone()[0]:
                raise RuntimeError("refusing to install fixtures into a non-empty public schema")
            conn.execute(SCHEMA)
            cls.addClassCleanup(cls.clean_fixture)
            conn.execute("INSERT INTO posts VALUES (99,'pre-existing sentinel','PUBLISHED')")
            migration = (ROOT / "database/sql/069_discord_meeting_jobs.sql").read_text(encoding="utf-8")
            before_commit, _, _ = migration.rpartition("COMMIT;")
            try:
                conn.execute(before_commit)
                conn.execute("SELECT 1/0")
            except psycopg.errors.DivisionByZero:
                conn.execute("ROLLBACK")
            else:
                raise AssertionError("DDL rollback injection failed")
            if conn.execute("""
                SELECT to_regclass('public.discord_meeting_jobs'),
                       to_regclass('public.discord_meeting_control'),
                       to_regprocedure('public.discord_meeting_guard_handoff()'),
                       to_regprocedure('public.discord_meeting_permission_snapshot(bigint,bigint)')
            """).fetchone() != (None, None, None, None):
                raise AssertionError("DDL did not roll back")
            conn.execute(migration)
            cls.original_data = conn.execute("SELECT title FROM posts WHERE post_id=99").fetchone()

    @staticmethod
    def clean_fixture():
        with connect() as conn:
            conn.execute("""
                DROP FUNCTION IF EXISTS public.discord_meeting_permission_snapshot(bigint,bigint);
                DROP TABLE IF EXISTS public.discord_meeting_control,public.discord_meeting_jobs,
                    public.recruit_members,public.recruit_discord_channels,public.recruits,public.posts,public.members;
                DROP FUNCTION IF EXISTS public.discord_meeting_guard_handoff();
            """)

    def setUp(self):
        self.admin = connect()
        self.addCleanup(self.admin.close)
        self.admin.execute("""
            TRUNCATE discord_meeting_jobs,recruit_discord_channels,recruit_members,recruits,posts,members;
            UPDATE discord_meeting_control SET create_owner='lambda',permission_owner='gateway',result_seen_at=now();
            INSERT INTO posts VALUES (1,'Test','PUBLISHED');
            INSERT INTO recruits VALUES (1,1,'regular',(now() AT TIME ZONE 'Asia/Seoul')-interval '1 hour',NULL,NULL);
        """)
        db = Database(connect)
        self.addCleanup(db.close)
        self.jobs = MeetingJobs(db)
        self.patch_api = patch.object(api, "db_cursor", self.api_cursor)
        self.patch_api.start()
        self.addCleanup(self.patch_api.stop)

    @contextmanager
    def api_cursor(self, *, commit):
        self.assertTrue(commit)
        conn = psycopg2.connect(DSN)
        try:
            with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
                yield cur
        finally:
            conn.close()

    def create(self):
        self.jobs.schedule(SCOPE)
        return self.job("create")

    def job(self, kind):
        key, target = self.admin.execute(
            "SELECT job_id,target FROM discord_meeting_jobs WHERE kind=%s AND finished_at IS NULL", (kind,)
        ).fetchone()
        return {"v": 1, "job_id": str(key), "kind": kind, "target": target, "recruit_id": 1, "verify": False}

    def allow(self, key, mode="disabled"):
        return api.issue_approval(key, str(uuid4()), mode)

    def status(self):
        return self.admin.execute("SELECT sync_status,discord_text_channel_id FROM recruit_discord_channels").fetchone()

    def test_migration_preserves_existing_data_and_constraints(self):
        self.assertEqual(self.original_data, ("pre-existing sentinel",))
        self.assertEqual(self.admin.execute("""
            SELECT count(*) FROM pg_index WHERE indrelid='public.discord_meeting_jobs'::regclass
            AND indisunique AND indpred IS NOT NULL
        """).fetchone(), (2,))
        self.assertFalse(self.admin.execute("""
            SELECT prosecdef FROM pg_proc WHERE oid='public.discord_meeting_permission_snapshot(bigint,bigint)'::regprocedure
        """).fetchone()[0])
        self.assertEqual(self.admin.execute("""
            SELECT count(*) FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a
            WHERE p.oid IN ('public.discord_meeting_permission_snapshot(bigint,bigint)'::regprocedure,
                            'public.discord_meeting_guard_handoff()'::regprocedure)
              AND a.grantee=0 AND a.privilege_type='EXECUTE'
        """).fetchone(), (0,))

    def test_concurrent_scheduler_and_approval_use_one_generation(self):
        barrier = threading.Barrier(2, timeout=5)

        def schedule(_):
            db = Database(connect)
            try:
                barrier.wait()
                MeetingJobs(db).schedule(SCOPE)
            finally:
                db.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(schedule, range(2)))
        self.assertEqual(self.admin.execute("SELECT count(*) FROM discord_meeting_jobs").fetchone(), (1,))
        item = self.job("create")
        nonce = str(uuid4())

        def approve(_):
            barrier.wait()
            return api.issue_approval(item["job_id"], nonce, "disabled")
        with ThreadPoolExecutor(max_workers=2) as pool:
            approvals = list(pool.map(approve, range(2)))
        self.assertEqual(sum(a is not None for a in approvals), 1)
        self.assertIsNone(self.allow(item["job_id"]))

    def test_permission_snapshot_uses_callers_table_privileges(self):
        self.members()
        with self.admin.transaction(force_rollback=True):
            self.admin.execute("CREATE ROLE issue188_fixture_reader NOLOGIN")
            self.admin.execute("GRANT USAGE ON SCHEMA public TO issue188_fixture_reader")
            self.admin.execute("SET LOCAL ROLE issue188_fixture_reader")
            query = "SELECT desired FROM public.discord_meeting_permission_snapshot(1,1)"
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with self.admin.transaction():
                    self.admin.execute(query)
            self.admin.execute("RESET ROLE")
            self.admin.execute("""
                GRANT EXECUTE ON FUNCTION public.discord_meeting_permission_snapshot(bigint,bigint)
                    TO issue188_fixture_reader
            """)
            self.admin.execute("SET LOCAL ROLE issue188_fixture_reader")
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                with self.admin.transaction():
                    self.admin.execute(query)
            self.admin.execute("RESET ROLE")
            self.admin.execute("""
                GRANT SELECT ON public.recruits,public.posts,public.members,public.recruit_members,
                    public.recruit_discord_channels,public.discord_meeting_jobs TO issue188_fixture_reader
            """)
            self.admin.execute("SET LOCAL ROLE issue188_fixture_reader")
            self.assertEqual(self.admin.execute(query).fetchone(), ("grant",))

    def test_expired_heartbeat_and_handoff_lock(self):
        item = self.create()
        self.admin.execute("UPDATE discord_meeting_control SET result_seen_at=now()-interval '91 seconds'")
        self.assertIsNone(self.allow(item["job_id"]))
        with connect() as gateway:
            gateway.execute("SELECT pg_advisory_lock(18801)")
            with self.assertRaises(psycopg.errors.RaiseException):
                self.admin.execute("UPDATE discord_meeting_control SET create_owner='paused'")
        self.admin.execute("UPDATE discord_meeting_control SET create_owner='paused',result_seen_at=now()")
        self.assertIsNone(self.allow(item["job_id"]))
        with self.assertRaises(psycopg.errors.RaiseException):
            self.admin.execute("UPDATE discord_meeting_control SET create_owner='gateway'")

    def test_unapproved_stale_generation_reissues_once_even_during_concurrent_ticks(self):
        item = self.create()
        self.admin.execute("UPDATE discord_meeting_jobs SET created_at=now()-interval '4 minutes 55 seconds'")
        publisher = Mock()
        settings = SimpleNamespace(target=SCOPE, work_url="fake")
        tick(self.jobs, publisher, settings)
        old_delivery = publisher.send.call_args
        self.assertEqual(old_delivery.kwargs["dedup_id"], item["job_id"])
        self.assertGreater(json.loads(old_delivery.args[1])["approve_before"], time.time())
        self.assertEqual(self.status(), ("PENDING", None))
        self.admin.execute("UPDATE discord_meeting_jobs SET created_at=now()-interval '5 minutes'")
        self.assertIsNone(self.allow(item["job_id"]))
        barrier = threading.Barrier(2, timeout=5)

        def retry(_):
            db = Database(connect)
            try:
                jobs = MeetingJobs(db)
                barrier.wait()
                jobs.expire()
                jobs.schedule(SCOPE)
            finally:
                db.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(retry, range(2)))
        replacement = self.job("create")
        self.assertNotEqual(replacement["job_id"], item["job_id"])
        self.assertEqual(self.admin.execute("SELECT count(*) FROM discord_meeting_jobs").fetchone(), (2,))
        self.assertIsNone(self.allow(item["job_id"]))
        tick(self.jobs, publisher, settings)
        new_delivery = publisher.send.call_args
        self.assertEqual(new_delivery.kwargs["group_id"], old_delivery.kwargs["group_id"])
        self.assertEqual(new_delivery.kwargs["dedup_id"], replacement["job_id"])
        self.assertIsNotNone(self.allow(replacement["job_id"]))
        self.assertEqual(self.status(), ("PENDING", None))

    def test_expiry_waits_for_approval_commit_and_preserves_approved_generation(self):
        item = self.create()
        self.admin.execute("UPDATE discord_meeting_jobs SET created_at=now()-interval '4 minutes 57 seconds'")
        prepared, release = threading.Event(), threading.Event()

        @contextmanager
        def held_approval(*, commit):
            with self.api_cursor(commit=commit) as cur:
                yield cur
                prepared.set()
                if not release.wait(10):
                    raise RuntimeError("fixture approval timed out")

        def expire():
            db = Database(connect)
            try:
                MeetingJobs(db).expire()
            finally:
                db.close()

        with ThreadPoolExecutor(max_workers=2) as pool, patch.object(api, "db_cursor", held_approval):
            approval = pool.submit(self.allow, item["job_id"])
            try:
                self.assertTrue(prepared.wait(5))
                until = time.monotonic() + 6
                while time.monotonic() < until:
                    if self.admin.execute("""
                        SELECT created_at <= clock_timestamp()-interval '5 minutes' FROM discord_meeting_jobs
                    """).fetchone()[0]:
                        break
                    time.sleep(0.02)
                else:
                    self.fail("fixture did not reach the five-minute boundary")
                expiry = pool.submit(expire)
                while time.monotonic() < until:
                    if self.admin.execute("""
                        SELECT 1 FROM pg_stat_activity WHERE datname=current_database()
                        AND backend_type='client backend' AND wait_event_type='Lock'
                        AND query LIKE '%%UPDATE public.discord_meeting_jobs SET finished_at%%'
                    """).fetchone():
                        break
                    time.sleep(0.02)
                else:
                    self.fail("expiry did not wait on the approval transaction")
            finally:
                release.set()
            self.assertIsNotNone(approval.result(timeout=5))
            expiry.result(timeout=5)
        self.jobs.schedule(SCOPE)
        self.assertEqual(self.job("create")["job_id"], item["job_id"])
        self.assertEqual(self.status(), ("PENDING", None))

    def test_late_approved_create_binds_only_matching_manual_generation(self):
        item = self.create()
        permit = self.allow(item["job_id"])
        self.admin.execute("UPDATE discord_meeting_jobs SET created_at=now()-interval '11 minutes'")
        self.jobs.expire()
        self.assertEqual(self.status(), ("FAILED", None))
        result = {**item, "outcome": "applied", "approval_id": permit["approval_id"], "channel_id": CHANNEL}
        self.assertEqual(self.jobs.apply({**result, "approval_id": str(uuid4())}), "ignored")
        self.assertEqual(self.jobs.apply(result), "applied")
        self.assertEqual(self.status(), ("SUCCESS", CHANNEL))
        self.assertEqual(self.jobs.apply(result), "ignored")

    def test_permanent_creation_skip_prevents_a_new_generation_past_five_minutes(self):
        item = self.create()
        discord = Mock()
        discord.list_guild_channels.return_value = [CREATED, {**CREATED, "id": "9"*18}]
        worker = MeetingWorker(discord, self.allow, GUILD, CAT)
        sqs = Mock()
        consumer = Consumer("meeting", MeetingResults(self.jobs), sqs,
            SimpleNamespace(queues={"meeting": "fake"}, read_timeout=30,
                            visibility_seconds=360, heartbeat_seconds=60))
        sqs.delete_message.side_effect = lambda **_: self.assertEqual(self.status(), ("FAILED", None))
        self.assertEqual(consumer.process({"Body": json.dumps(worker.process(item)), "ReceiptHandle": "fake"}),
                         "acked")
        sqs.delete_message.assert_called_once()
        self.assertEqual(self.status(), ("FAILED", None))
        self.assertIn("duplicate_marker", self.admin.execute(
            "SELECT sync_error FROM recruit_discord_channels").fetchone()[0])
        self.admin.execute("""
            UPDATE discord_meeting_jobs SET created_at=now()-interval '11 minutes';
            UPDATE recruit_discord_channels SET updated_at=now()-interval '11 minutes';
        """)
        self.jobs.expire()
        self.jobs.schedule(SCOPE)
        self.assertEqual(self.admin.execute("SELECT count(*) FROM discord_meeting_jobs").fetchone(), (1,))
        self.assertIsNone(self.allow(item["job_id"]))
        discord.create_guild_channel.assert_not_called()

    def test_conflict_hold_retains_approved_late_evidence_without_binding(self):
        item = self.create()
        permit = self.allow(item["job_id"])
        discord = Mock()
        discord.list_guild_channels.return_value = [CREATED, {**CREATED, "id": "9"*18}]
        worker = MeetingWorker(discord, self.allow, GUILD, CAT)
        self.assertEqual(self.jobs.apply(worker.process({**item, "verify": True})), "applied")
        result = {**item, "outcome": "applied", "approval_id": permit["approval_id"], "channel_id": CHANNEL}
        self.assertEqual(self.jobs.apply(result), "manual")
        self.assertEqual(self.status(), ("FAILED", None))
        self.assertEqual(self.admin.execute("SELECT result_channel_id FROM discord_meeting_jobs").fetchone(),
                         (CHANNEL,))
        discord.create_guild_channel.assert_not_called()

    def test_preapproval_outage_recovers_on_fresh_generation(self):
        item = self.create()
        discord = Mock()
        discord.list_guild_channels.return_value = []
        discord.get_channel.return_value = {"id": CAT, "guild_id": GUILD, "type": 4}
        discord.create_guild_channel.return_value = CREATED
        approval = Mock(side_effect=TimeoutError("fixture"))
        worker = MeetingWorker(discord, approval, GUILD, CAT)
        with self.assertRaises(TimeoutError):
            worker.process(item)
        self.assertEqual(self.admin.execute("SELECT approval_id FROM discord_meeting_jobs").fetchone(), (None,))
        self.admin.execute("UPDATE discord_meeting_jobs SET created_at=now()-interval '5 minutes'")
        self.jobs.expire()
        self.jobs.schedule(SCOPE)
        retry = self.job("create")
        self.assertNotEqual(retry["job_id"], item["job_id"])
        approval.side_effect = self.allow
        self.assertEqual(self.jobs.apply(worker.process(retry)), "applied")
        self.assertEqual(self.status(), ("SUCCESS", CHANNEL))
        discord.create_guild_channel.assert_called_once()

    def test_unclassified_400_is_held_after_approval_without_reissuing(self):
        item = self.create()
        discord = Mock()
        discord.list_guild_channels.return_value = []
        discord.get_channel.return_value = {"id": CAT, "guild_id": GUILD, "type": 4}
        discord.create_guild_channel.side_effect = DiscordRequestError("fixture", status=400, code=50035)
        worker = MeetingWorker(discord, self.allow, GUILD, CAT)
        result = worker.process(item)
        self.assertEqual(result["outcome"], "rejected")
        self.assertEqual(self.jobs.apply(result), "applied")
        self.assertEqual(self.status(), ("FAILED", None))
        self.assertTrue(self.admin.execute("SELECT sync_error FROM recruit_discord_channels").fetchone()[0]
                        .startswith("MANUAL:"))
        self.admin.execute("""
            UPDATE discord_meeting_jobs SET created_at=now()-interval '11 minutes';
            UPDATE recruit_discord_channels SET updated_at=now()-interval '11 minutes';
        """)
        self.jobs.expire()
        self.jobs.schedule(SCOPE)
        self.assertEqual(self.admin.execute("SELECT count(*) FROM discord_meeting_jobs").fetchone(), (1,))
        discord.create_guild_channel.assert_called_once()

    def test_permission_owner_check_rejects_paused_and_lambda_without_active_gateway(self):
        for owner in ("paused", "lambda"):
            with self.subTest(owner=owner), self.assertRaises(psycopg.errors.CheckViolation):
                self.admin.execute("UPDATE discord_meeting_control SET permission_owner=%s", (owner,))
        self.assertEqual(self.admin.execute(
            "SELECT create_owner,permission_owner FROM discord_meeting_control").fetchone(), ("lambda", "gateway"))

    def test_late_found_evidence_cannot_overwrite_newer_generation_or_other_binding(self):
        item = self.create()
        self.assertIsNotNone(self.allow(item["job_id"]))
        self.admin.execute("UPDATE discord_meeting_jobs SET created_at=now()-interval '11 minutes'")
        self.jobs.expire()
        self.admin.execute("INSERT INTO posts VALUES (2,'Other','PUBLISHED')")
        self.admin.execute("INSERT INTO recruits VALUES (2,2,'regular',now(),NULL,NULL)")
        self.admin.execute("""
            INSERT INTO recruit_discord_channels(recruit_id,sync_status,discord_text_channel_id)
            VALUES (2,'SUCCESS',%s)
        """, (CHANNEL,))
        other_job = uuid4()
        self.admin.execute("""
            INSERT INTO discord_meeting_jobs(job_id,recruit_id,kind,target,finished_at,outcome)
            VALUES (%s,1,'create','{}',now(),'rejected')
        """, (other_job,))
        self.assertEqual(self.jobs.apply({**item, "outcome": "found", "channel_id": CHANNEL}), "manual")
        self.assertEqual(self.status_for(1), ("FAILED", None))
        self.assertEqual(self.status_for(2), ("SUCCESS", CHANNEL))
        self.assertEqual(self.admin.execute(
            "SELECT result_channel_id FROM discord_meeting_jobs WHERE job_id=%s", (item["job_id"],)
        ).fetchone(), (CHANNEL,))

    def status_for(self, recruit_id):
        return self.admin.execute("""
            SELECT sync_status,discord_text_channel_id FROM recruit_discord_channels WHERE recruit_id=%s
        """, (recruit_id,)).fetchone()

    def test_permission_owner_cannot_transfer_and_gateway_session_recycles_after_disconnect(self):
        from repositories.meeting_repository import PostgresMeetingRepository

        opened = []

        def open_session():
            conn = connect()
            opened.append(conn)
            return conn

        repo = PostgresMeetingRepository(connect, open_session)
        self.addCleanup(repo._discard_gateway_writer)
        allowed, lease = repo.acquire_gateway_writer("permissions")
        self.assertTrue(allowed)
        with self.assertRaises(psycopg.errors.RaiseException):
            self.admin.execute("UPDATE discord_meeting_control SET permission_owner='paused'")
        self.assertEqual(repo.acquire_gateway_writer("permissions"), (False, None))
        lease.close()
        for owner in ("paused", "lambda"):
            with self.subTest(owner=owner), self.assertRaises(psycopg.errors.CheckViolation):
                self.admin.execute("UPDATE discord_meeting_control SET permission_owner=%s", (owner,))
        self.admin.execute("UPDATE discord_meeting_control SET create_owner='paused'")
        allowed, lease = repo.acquire_gateway_writer("permissions")
        self.assertTrue(allowed)
        self.assertEqual(len(opened), 1)
        self.admin.execute("SELECT pg_terminate_backend(%s,5000)", (opened[0].info.backend_pid,))
        with self.assertRaises(psycopg.OperationalError):
            lease.close()
        allowed, lease = repo.acquire_gateway_writer("permissions")
        self.assertTrue(allowed)
        lease.close()
        self.assertEqual(len(opened), 2)
        self.assertIsNone(self.admin.execute("""
            SELECT 1 FROM pg_locks WHERE locktype='advisory' AND objid=18802
        """).fetchone())

    def test_http_authentication_replay_and_consumer_heartbeat(self):
        item = self.create()
        secret = "issue188-local-fixture-only-key-000"
        app = FastAPI()
        app.include_router(api.router)
        body = json.dumps({"job_id": item["job_id"], "nonce": str(uuid4()), "grant_from": "disabled"}).encode()

        def headers(offset=0):
            stamp = str(int(time.time()) + offset)
            signed = b"POST " + api.APPROVAL_PATH.encode() + b"\n" + stamp.encode() + b"\n" + body
            signature = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
            return {"X-Meeting-Time": stamp, "X-Meeting-Signature": signature}

        with TestClient(app) as client, patch.dict(os.environ, {
            "DISCORD_MEETING_APPROVAL_ENABLED": "true", "DISCORD_MEETING_APPROVAL_SECRET": secret,
        }):
            self.assertEqual(client.post(api.APPROVAL_PATH, content=body).status_code, 403)
            self.assertEqual(client.post(api.APPROVAL_PATH, content=body, headers=headers(-16)).status_code, 403)
            self.assertEqual(client.post(api.APPROVAL_PATH, content=body + b" ", headers=headers()).status_code, 403)
            self.admin.execute("UPDATE discord_meeting_control SET result_seen_at=NULL")
            self.assertEqual(client.post(api.APPROVAL_PATH, content=body, headers=headers()).status_code, 409)
            self.assertEqual(self.admin.execute("SELECT approved_at FROM discord_meeting_jobs").fetchone(), (None,))
            self.jobs.heartbeat()
            signed = headers()
            self.assertEqual(client.post(api.APPROVAL_PATH, content=body, headers=signed).status_code, 200)
            self.assertEqual(client.post(api.APPROVAL_PATH, content=body, headers=signed).status_code, 409)

    def test_consumed_approval_and_restart_cannot_create_after_missing_result(self):
        item = self.create()
        self.assertIsNotNone(self.allow(item["job_id"]))  # Worker disappears after approval
        self.admin.execute("UPDATE discord_meeting_jobs SET approved_at=now()-interval '100 seconds'")
        worker = Mock()
        worker.list_guild_channels.return_value = []
        publisher = Mock()
        settings = SimpleNamespace(target=None, work_url="fake")
        tick(self.jobs, publisher, settings)
        body = json.loads(publisher.send.call_args.args[1])
        self.assertTrue(body["verify"])
        adapter = MeetingWorker(worker, self.allow, GUILD, CAT)
        self.assertEqual(adapter.process(body)["outcome"], "skipped")
        worker.create_guild_channel.assert_not_called()
        self.admin.execute("UPDATE discord_meeting_jobs SET created_at=now()-interval '11 minutes'")
        self.jobs.expire()
        self.jobs.schedule(SCOPE)
        self.assertEqual(self.status(), ("FAILED", None))
        self.assertEqual(self.admin.execute("SELECT count(*) FROM discord_meeting_jobs").fetchone(), (1,))

    def test_create_result_lost_redelivery_lookup_and_old_generation(self):
        item = self.create()
        discord = Mock()
        discord.list_guild_channels.side_effect = [[], [CREATED]]
        discord.get_channel.return_value = {"id": CAT, "guild_id": GUILD, "type": 4}
        discord.create_guild_channel.return_value = CREATED
        worker = MeetingWorker(discord, self.allow, GUILD, CAT)
        first = worker.process(item)  # deliberately lose the successful result
        self.assertEqual(first["outcome"], "applied")
        self.assertEqual(self.jobs.apply({**first, "job_id": str(uuid4())}), "ignored")
        self.assertEqual(self.jobs.apply({**first, "approval_id": str(uuid4())}), "ignored")
        self.assertEqual(self.status(), ("PENDING", None))
        recovered = worker.process(item)
        self.assertEqual(recovered["outcome"], "found")
        self.assertEqual(self.jobs.apply(recovered), "applied")
        self.assertEqual(self.status(), ("SUCCESS", CHANNEL))
        self.assertEqual(self.jobs.apply(first), "ignored")
        discord.create_guild_channel.assert_called_once()

    def test_result_rollback_commit_reply_loss_and_ack(self):
        item = self.create()
        result = {**item, "outcome": "applied", "channel_id": CHANNEL, "approval_id": self.allow(item["job_id"])["approval_id"]}
        sqs = Mock()
        message = {"Body": json.dumps(result), "ReceiptHandle": "fake"}
        consumer = Consumer("meeting", MeetingResults(self.jobs), sqs,
            SimpleNamespace(queues={"meeting": "fake"}, wait_seconds=20, read_timeout=30,
                            visibility_seconds=360, heartbeat_seconds=60))
        real_transaction = self.jobs.db.transaction

        def rollback(work):
            def fail(cur):
                work(cur)
                cur.execute("SELECT 1/0")
            return real_transaction(fail)

        with patch.object(self.jobs.db, "transaction", side_effect=rollback):
            self.assertEqual(consumer.process(message), "db_failed")
        self.assertEqual(self.status(), ("PENDING", None))
        sqs.delete_message.assert_not_called()

        def lose_reply(work):
            real_transaction(work)
            raise psycopg.OperationalError("synthetic commit response loss")

        with patch.object(self.jobs.db, "transaction", side_effect=lose_reply):
            self.assertEqual(consumer.process(message), "db_failed")
        sqs.delete_message.assert_not_called()
        self.assertEqual(self.status(), ("SUCCESS", CHANNEL))
        sqs.delete_message.side_effect = lambda **kwargs: self.assertEqual(self.status(), ("SUCCESS", CHANNEL))
        self.assertEqual(consumer.process(message), "acked")
        sqs.delete_message.assert_called_once()

    def test_disconnected_db_retains_result_and_recovers(self):
        item = self.create()
        result = {**item, "outcome": "found", "channel_id": CHANNEL}
        sqs = Mock()
        consumer = Consumer("meeting", MeetingResults(self.jobs), sqs,
            SimpleNamespace(queues={"meeting": "fake"}, read_timeout=30, visibility_seconds=360, heartbeat_seconds=60))
        self.jobs.db.close()
        msg = {"Body": json.dumps(result), "ReceiptHandle": "fake"}
        with patch.object(self.jobs.db, "_connect", side_effect=lambda: connect(options="-c statement_timeout=invalid")):
            self.assertEqual(consumer.process(msg), "db_failed")
        sqs.delete_message.assert_not_called()
        transaction = self.jobs.db.transaction

        def disconnect(work):
            def fail(cur):
                work(cur)
                cur.execute("SELECT pg_backend_pid() AS pid")
                pid = cur.fetchone()["pid"]
                self.assertEqual(self.admin.execute("SELECT pg_terminate_backend(%s,5000)", (pid,)).fetchone(),
                                 (True,))
                cur.execute("SELECT 1")
            return transaction(fail)

        with patch.object(self.jobs.db, "transaction", side_effect=disconnect):
            self.assertEqual(consumer.process(msg), "db_failed")
        sqs.delete_message.assert_not_called()
        self.assertEqual(self.status(), ("PENDING", None))
        self.assertEqual(consumer.process(msg), "acked")
        self.assertEqual(self.status(), ("SUCCESS", CHANNEL))

    def members(self, *, future_permission_pipeline=False):
        self.admin.execute("INSERT INTO recruit_discord_channels(recruit_id,sync_status,discord_text_channel_id) VALUES (1,'SUCCESS',%s)", (CHANNEL,))
        self.admin.execute("INSERT INTO members VALUES (1,%s,'ACTIVE')", (USER,))
        self.admin.execute("INSERT INTO recruit_members VALUES (1,1,'JOINED',now(),NULL)")
        if future_permission_pipeline:
            # Exercise dormant reconciliation on the disposable fixture only.
            self.admin.execute("""
                ALTER TABLE discord_meeting_control DROP CONSTRAINT discord_meeting_control_permission_owner_check;
                UPDATE discord_meeting_control SET permission_owner='lambda';
            """)
            self.addCleanup(self.restore_permission_gate)

    def restore_permission_gate(self):
        self.admin.execute("""
            TRUNCATE discord_meeting_jobs;
            UPDATE discord_meeting_control SET permission_owner='gateway';
            ALTER TABLE discord_meeting_control ADD CHECK (permission_owner='gateway');
        """)

    def test_cancel_commit_denies_old_permit_and_late_grant_is_reconciled(self):
        self.members(future_permission_pipeline=True)
        self.jobs.schedule(SCOPE)
        item = self.job("permissions")
        discord = Mock()
        overwrites = []
        discord.get_channel.return_value = {**CREATED, "permission_overwrites": overwrites}
        discord.get_guild.return_value = {"id": GUILD, "owner_id": "8"*18}
        discord.get_guild_member.return_value = {"user": {"id": USER}, "roles": []}
        discord.list_guild_roles.return_value = [{"id": GUILD, "permissions": "0"}]

        def write(_channel, _user, *, allow, deny):
            self.assertEqual(self.admin.execute("SELECT status FROM recruit_members").fetchone(), ("CANCELED",))
            overwrites[:] = [{"id": USER, "type": 1, "allow": str(allow), "deny": str(deny)}]
        discord.set_member_permissions.side_effect = write

        def approve_then_cancel(key, mode):
            permit = self.allow(key, mode)
            self.assertEqual(permit["action"], "grant")
            self.admin.execute("UPDATE recruit_members SET status='CANCELED',canceled_at=now()")
            self.assertIsNone(self.allow(key, "absent"))
            return permit
        with patch.dict(os.environ, {"DISCORD_MEETING_ALLOW_GRANT": "true"}):
            late = MeetingWorker(discord, approve_then_cancel, GUILD, CAT, grant=True).process(item)
            self.jobs.apply(late)
            self.assertEqual(int(overwrites[0]["deny"]), 0)
            self.jobs.schedule(SCOPE)
            revoke = self.job("permissions")
            self.assertNotEqual(revoke["job_id"], item["job_id"])
            repaired = MeetingWorker(discord, self.allow, GUILD, CAT).process(revoke)
            self.jobs.apply(repaired)
            self.assertEqual(int(overwrites[0]["deny"]), 1 << 11)

            # A later unconsumed JOINED job is refused against the next cancel commit.
            self.admin.execute("UPDATE recruit_members SET status='JOINED',joined_at=now()")
            self.jobs.schedule(SCOPE)
            stale = self.job("permissions")
            self.admin.execute("UPDATE recruit_members SET status='CANCELED',canceled_at=now()")
            self.assertIsNone(self.allow(stale["job_id"], "absent"))

    def test_private_revoke_retries_after_forbidden_and_preserves_protected_overwrites(self):
        self.members(future_permission_pipeline=True)
        scope = {**SCOPE,"visibility": "PRIVATE"}
        self.jobs.schedule(scope)
        item = self.job("permissions")
        with patch.dict(os.environ, {"DISCORD_MEETING_ALLOW_GRANT": "true"}):
            approval = self.allow(item["job_id"], "absent")
        self.jobs.apply({**item, "outcome": "applied", "approval_id": approval["approval_id"]})
        self.admin.execute("UPDATE recruit_members SET status='CANCELED',canceled_at=now()")
        self.jobs.schedule(scope)
        revoke = self.job("permissions")
        discord = Mock()
        discord.get_guild.return_value = {"id": GUILD, "owner_id": "8"*18}
        discord.get_guild_member.return_value = {"user": {"id": USER}, "roles": []}
        discord.list_guild_roles.return_value = [{"id": GUILD, "permissions": "0"}]
        channel = {**CREATED,"topic": "PlayMate 모임 #1 (PRIVATE)"}
        discord.get_channel.return_value = {**channel, "permission_overwrites": [
            {"id": USER, "type": 1, "allow": "1", "deny": "0"}
        ]}
        worker = MeetingWorker(discord, self.allow, GUILD, CAT)
        self.assertEqual(worker.process(revoke)["outcome"], "skipped")
        self.assertEqual(self.admin.execute("SELECT approved_at FROM discord_meeting_jobs WHERE job_id=%s",
                                            (revoke["job_id"],)).fetchone(), (None,))
        discord.get_channel.return_value["permission_overwrites"][0]["allow"] = str(PARTICIPANT_ALLOW)
        discord.get_guild_member.return_value["roles"] = ["9"*18]
        self.assertEqual(MeetingWorker(discord, self.allow, GUILD, CAT, staff_roles=["9"*18])
                         .process(revoke)["outcome"], "skipped")
        discord.get_guild_member.return_value["roles"] = []
        discord.clear_member_permissions.side_effect = [DiscordForbidden("fixture", status=403), None]
        rejected = worker.process(revoke)
        self.assertEqual(rejected["outcome"], "rejected")
        self.jobs.apply(rejected)
        self.admin.execute("UPDATE discord_meeting_jobs SET finished_at=now()-interval '61 seconds' WHERE job_id=%s",
                           (revoke["job_id"],))
        self.jobs.schedule(scope)
        retry = self.job("permissions")
        self.assertNotEqual(retry["job_id"], revoke["job_id"])
        repaired = worker.process(retry)
        self.assertEqual(repaired["outcome"], "applied")
        self.assertEqual(self.jobs.apply(repaired), "applied")
        self.assertEqual(discord.clear_member_permissions.call_count, 2)
        discord.set_member_permissions.assert_not_called()

    def test_withdrawal_targets_only_previously_managed_discord_id(self):
        self.members(future_permission_pipeline=True)
        self.jobs.schedule(SCOPE)
        item = self.job("permissions")
        with patch.dict(os.environ, {"DISCORD_MEETING_ALLOW_GRANT": "true"}):
            approval = self.allow(item["job_id"], "absent")
        self.jobs.apply({**item, "outcome": "applied", "approval_id": approval["approval_id"]})
        self.admin.execute("UPDATE members SET discord_id='w1',member_status='WITHDRAWN'")
        self.jobs.schedule(SCOPE)
        revoke = self.job("permissions")
        self.assertEqual(revoke["target"]["user_id"], USER)
        self.assertEqual(self.allow(revoke["job_id"])["action"], "revoke")

    def test_reassigned_discord_id_does_not_authorize_old_revoke(self):
        self.members(future_permission_pipeline=True)
        self.jobs.schedule(SCOPE)
        item = self.job("permissions")
        with patch.dict(os.environ, {"DISCORD_MEETING_ALLOW_GRANT": "true"}):
            approval = self.allow(item["job_id"], "absent")
        self.jobs.apply({**item, "outcome": "applied", "approval_id": approval["approval_id"]})
        self.admin.execute("UPDATE members SET discord_id='w1',member_status='WITHDRAWN'")
        self.jobs.schedule(SCOPE)
        revoke = self.job("permissions")
        self.admin.execute("INSERT INTO members VALUES (2,%s,'ACTIVE')", (USER,))
        self.assertIsNone(self.allow(revoke["job_id"]))
        self.assertEqual(self.admin.execute("""
            SELECT discord_id,managed FROM public.discord_meeting_permission_snapshot(1,1)
        """).fetchone(), (None, False))

    def test_permission_success_drift_and_missing_member_use_distinct_schedules(self):
        self.members(future_permission_pipeline=True)
        self.jobs.schedule(SCOPE)
        item = self.job("permissions")
        discord = Mock()
        discord.get_channel.return_value = {**CREATED, "permission_overwrites": []}
        discord.get_guild.return_value = {"id": GUILD, "owner_id": "8"*18}
        discord.get_guild_member.return_value = {"user": {"id": USER}, "roles": []}
        discord.list_guild_roles.return_value = [{"id": GUILD, "permissions": "0"}]
        worker = MeetingWorker(discord, self.allow, GUILD, CAT, grant=True)
        with patch.dict(os.environ, {"DISCORD_MEETING_ALLOW_GRANT": "true"}):
            self.assertEqual(self.jobs.apply(worker.process(item)), "applied")
        self.admin.execute("UPDATE discord_meeting_jobs SET finished_at=now()-interval '2 minutes'")
        for _ in range(5):
            self.jobs.schedule(SCOPE)
            self.assertEqual(self.admin.execute("SELECT count(*) FROM discord_meeting_jobs").fetchone(), (1,))
            self.assertFalse(self.jobs.pending())
        self.assertEqual(discord.get_channel.call_count, 1)
        self.admin.execute("UPDATE recruit_members SET status='CANCELED',canceled_at=now()")
        self.jobs.schedule(SCOPE)
        revoke = self.job("permissions")
        self.assertNotEqual(revoke["job_id"], item["job_id"])
        from discord_rest.errors import DiscordNotFound
        discord.get_guild_member.side_effect = DiscordNotFound("fixture", status=404, code=10007)
        self.assertEqual(self.jobs.apply(worker.process(revoke)), "applied")
        self.admin.execute("""
            UPDATE discord_meeting_jobs SET finished_at=now()-interval '59 minutes'
            WHERE job_id=%s
        """, (revoke["job_id"],))
        self.jobs.schedule(SCOPE)
        self.assertFalse(self.jobs.pending())
        self.assertEqual(discord.get_channel.call_count, 2)
        self.admin.execute("""
            UPDATE discord_meeting_jobs SET finished_at=now()-interval '61 minutes'
            WHERE job_id=%s
        """, (revoke["job_id"],))
        self.jobs.schedule(SCOPE)
        self.assertNotEqual(self.job("permissions")["job_id"], revoke["job_id"])

    def test_permission_handoff_requires_reconciliation_of_uncertain_write(self):
        self.members(future_permission_pipeline=True)
        self.jobs.schedule(SCOPE)
        item = self.job("permissions")
        with patch.dict(os.environ, {"DISCORD_MEETING_ALLOW_GRANT": "true"}):
            approval = self.allow(item["job_id"], "absent")
        self.jobs.apply({**item, "outcome": "unknown", "approval_id": approval["approval_id"]})
        self.assertEqual(self.admin.execute("SELECT outcome FROM discord_meeting_jobs").fetchone(), ("unknown",))
        self.admin.execute("UPDATE discord_meeting_control SET permission_owner='paused'")
        for outcome in ("unknown", "expired"):
            self.admin.execute("UPDATE discord_meeting_jobs SET outcome=%s", (outcome,))
            with self.assertRaises(psycopg.errors.RaiseException):
                self.admin.execute("UPDATE discord_meeting_control SET permission_owner='gateway'")
        self.admin.execute("UPDATE discord_meeting_jobs SET outcome='reconciled'")
        self.admin.execute("UPDATE discord_meeting_control SET permission_owner='gateway'")
