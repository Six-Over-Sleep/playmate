"""Runner integration tests for an explicitly identified, disposable issue184 cluster."""
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

import test_career_share as career
import test_dm_share as dm
import test_hot_share as hot
from test_db_runner import FakeSqs, environment, message

from career_share import contract
from career_share.queues import FakeQueue
from career_share.service import CareerShareService
from db_runner.results import ResultConsumer
from db_runner.scheduler import Scheduler
from db_runner.settings import load_settings
from dm_share.service import DmShareService
from hot_share.service import HotShareService


def setUpModule():
    dsn = os.environ.get("PLAYMATE_TEST_PG_DSN")
    cluster_id = os.environ.get("ISSUE184_CLUSTER_ID")
    if not dsn or not cluster_id:
        raise unittest.SkipTest("explicit Issue #184 PostgreSQL 18 DSN and cluster ID required")
    import psycopg
    params = psycopg.conninfo.conninfo_to_dict(dsn)
    allowed = {"host", "port", "dbname", "user", "password", "connect_timeout", "sslmode"}
    if (set(params) - allowed or not params.get("port") or not params.get("password")
            or tuple(params.get(k) for k in ("host", "dbname", "user"))
            != ("127.0.0.1", "playmate_issue184_test", "issue184_test")):
        raise RuntimeError("refusing non-Issue #184 DSN")
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "SELECT current_database(), current_user, current_setting('server_version_num')::int,"
            " system_identifier::text FROM pg_control_system()"
        ).fetchone()
    if row[:2] != ("playmate_issue184_test", "issue184_test") or row[2] // 10000 != 18 or row[3] != cluster_id:
        raise RuntimeError("Issue #184 PostgreSQL cluster identity mismatch")


def consumer(feature, service):
    sqs = FakeSqs()
    return ResultConsumer(feature, service, sqs, load_settings(environment(feature))), sqs


def check_delivery(case, runner, sqs, read, kind, unit, token):
    valid = message(kind, unit, claim_token=token)
    initial = read()
    case.assertEqual(initial["status"], "PENDING")
    wrong = message("HOT", "hot-1") if kind != "HOT" else message()
    case.assertEqual(runner.process(wrong), "invalid")
    case.assertEqual(read(), initial)
    case.assertNotIn("delete", sqs.events)
    case.assertEqual(runner.process(message(kind, unit)), "acked")
    case.assertEqual(read(), initial)
    sqs.fail_delete = True
    delete = sqs.delete_message
    observed_at_delete = []

    def observe_commit(**kwargs):
        observed_at_delete.append(read())
        delete(**kwargs)

    with patch.object(sqs, "delete_message", side_effect=observe_commit):
        case.assertEqual(runner.process(valid), "delete_failed")
    committed = read()
    case.assertEqual(committed["status"], "SENT")
    case.assertEqual(observed_at_delete, [committed])
    case.assertEqual(str(committed["discord_message_id"]), "123456789012345678")
    sqs.fail_delete = False
    case.assertEqual(runner.process(valid | {"ReceiptHandle": "redelivered"}), "acked")
    case.assertEqual(read(), committed)
    case.assertEqual(runner.process(message(kind, unit, claim_token=token, outcome="UNKNOWN")), "acked")
    case.assertEqual(read(), committed)


class CareerRunnerPg18(unittest.TestCase):
    def setUp(self):
        self.fixture = career.PostgresBackend()
        self.addCleanup(self.fixture.close)
        self.queue = FakeQueue()
        self.service = CareerShareService(self.fixture.repo, self.queue, career.make_settings(), clock=lambda: career.T0)
        self.runner, self.sqs = consumer("career", self.service)

    def claim(self, *ids):
        for pid in ids:
            self.fixture.add_post(pid)
        self.service.relay(career.T0)
        return [message(unit=f"post-{pid}", claim_token=self.fixture.row(pid)["claim_token"]) for pid in ids]

    def test_result_replay_and_stale_token(self):
        self.claim(1)
        check_delivery(self, self.runner, self.sqs, lambda: self.fixture.row(1),
                       "IMMEDIATE", "post-1", self.fixture.row(1)["claim_token"])

    def test_sql_error_rolls_back_and_other_result_is_processed(self):
        first, second = self.claim(1, 2)
        db = self.service.repo._db
        transaction = db.transaction

        def inject(work):
            def fail_after_write(cur):
                work(cur)
                cur.execute("SELECT 1 / 0")
            return transaction(fail_after_write)

        with patch.object(db, "transaction", side_effect=inject):
            self.assertEqual(self.runner.process(first), "db_failed")
        self.assertEqual(self.fixture.row(1)["status"], "PENDING")
        self.assertNotIn("delete", self.sqs.events)
        self.assertEqual(self.runner.process(second), "acked")
        self.assertEqual(self.fixture.row(2)["status"], "SENT")

    def test_commit_reply_loss_simulation_after_real_commit(self):
        first, = self.claim(1)
        db = self.service.repo._db
        transaction = db.transaction

        def lose_reply(work):
            transaction(work)
            raise TimeoutError("simulated lost commit reply")

        with patch.object(db, "transaction", side_effect=lose_reply):
            self.assertEqual(self.runner.process(first), "db_failed")
        committed = self.fixture.row(1)
        self.assertEqual(committed["status"], "SENT")
        self.assertNotIn("delete", self.sqs.events)
        self.assertEqual(self.runner.process(first), "acked")
        self.assertEqual(self.fixture.row(1), committed)

    def test_backend_termination_rolls_back_and_reconnects(self):
        first, second = self.claim(1, 2)
        db = self.service.repo._db
        transaction = db.transaction

        def inject(work):
            def terminate_after_write(cur):
                work(cur)
                cur.execute("SELECT pg_backend_pid() AS pid")
                pid = cur.fetchone()["pid"]
                self.assertTrue(self.fixture.admin.execute("SELECT pg_terminate_backend(%s, 5000)", (pid,)).fetchone()[0])
                cur.execute("SELECT 1")
            return transaction(terminate_after_write)

        with patch.object(db, "transaction", side_effect=inject):
            self.assertEqual(self.runner.process(first), "db_failed")
        self.assertEqual(self.fixture.row(1)["status"], "PENDING")
        self.assertNotIn("delete", self.sqs.events)
        self.assertIsNone(db._conn)
        self.assertEqual(self.runner.process(second), "acked")
        self.assertEqual(self.fixture.row(2)["status"], "SENT")
        self.assertEqual(self.runner.process(first), "acked")
        self.assertEqual(self.fixture.row(1)["status"], "SENT")

    def test_connection_failure_leaves_result_for_retry(self):
        first, = self.claim(1)
        db = self.service.repo._db
        db.close()
        def rejected_connect():
            # The verified test server rejects the startup parameter before any query runs.
            return self.fixture.psycopg.connect(
                os.environ["PLAYMATE_TEST_PG_DSN"], options="-c statement_timeout=not-a-duration"
            )

        with patch.object(db, "_connect", side_effect=rejected_connect):
            self.assertEqual(self.runner.process(first), "db_failed")
        self.assertNotIn("delete", self.sqs.events)
        self.assertEqual(self.fixture.row(1)["status"], "PENDING")
        self.assertEqual(self.runner.process(first), "acked")
        self.assertEqual(self.fixture.row(1)["status"], "SENT")

    def test_two_schedulers_claim_one_relay_and_one_digest(self):
        now = career.T0.replace(hour=11)
        self.fixture.add_post(1, created_at=now)
        self.fixture.add_post(2, category="lab", sub="JOB_STRATEGY", created_at=now)
        second_queue = FakeQueue()
        other = CareerShareService(self.fixture.repo_b, second_queue, career.make_settings())
        barrier = threading.Barrier(2, timeout=5)

        def tick(service):
            barrier.wait()
            Scheduler({"career": service}, load_settings(environment("career")), clock=lambda: now).tick(threading.Event())

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(tick, (self.service, other)))
        jobs = [contract.loads(body) for queue in (self.queue, second_queue) for _, body in queue.messages]
        self.assertCountEqual([job["kind"] for job in jobs], ["IMMEDIATE", "DIGEST"])
        self.assertEqual(self.fixture.row(1)["attempt_count"], 1)
        self.assertEqual(self.fixture.row(2)["attempt_count"], 1)
        self.assertEqual(self.fixture.batch_count(), 1)

    def test_restarted_scheduler_recovers_expired_claim_via_verify(self):
        self.claim(1)
        now = career.T0 + timedelta(minutes=31)
        queue = FakeQueue()
        fresh = CareerShareService(self.fixture.repo_b, queue, career.make_settings(), clock=lambda: now)
        Scheduler({"career": fresh}, load_settings(environment("career")), clock=lambda: now).tick(threading.Event())
        self.assertEqual(self.fixture.row(1)["status"], "UNKNOWN")
        self.assertEqual(queue.messages, [])
        now += timedelta(minutes=31)
        fresh.recover(now)
        job, = [contract.loads(body) for _, body in queue.messages]
        self.assertEqual(job["type"], "verify")
        runner, _ = consumer("career", fresh)
        self.assertEqual(runner.process(message(claim_token=job["claim_token"], job_id=job["job_id"])), "acked")
        self.assertEqual(self.fixture.row(1)["status"], "SENT")


class HotRunnerPg18(hot.PgCase):
    def test_result_replay_and_stale_token(self):
        self.baseline_empty()
        pid = self.post()
        self.like(pid, 10)
        service = HotShareService(self.repo, FakeQueue(), hot.make_settings(), clock=lambda: hot.T0)
        service.relay(hot.T0)
        runner, sqs = consumer("hot", service)
        check_delivery(self, runner, sqs, lambda: self.row(pid), "HOT", f"hot-{pid}", self.row(pid)["claim_token"])


class DmRunnerPg18(dm.PgCase):
    def service(self):
        return DmShareService(self.repo(), FakeQueue(), dm.make_settings(), clock=lambda: dm.T0)

    def test_result_replay_and_stale_token(self):
        nid = self.notify()
        service = self.service()
        service.relay(dm.T0)
        runner, sqs = consumer("dm", service)
        check_delivery(self, runner, sqs, lambda: self.delivery(nid),
                       "DM", f"dm-{nid}", self.delivery(nid)["claim_token"])
        self.assertEqual((self.notif(nid)["status"], self.notif(nid)["retry_count"]), ("SENT", 0))

    def test_auth_result_commits_and_blocks_new_claims(self):
        old = self.notify()
        service = self.service()
        service.relay(dm.T0)
        new = self.notify()
        runner, _ = consumer("dm", service)
        result = message("DM", f"dm-{old}", claim_token=self.delivery(old)["claim_token"],
                         outcome="FAILED_RETRY", auth_error=True)
        self.assertEqual(runner.process(result), "acked")
        self.assertTrue(service.repo.auth_open())
        self.assertEqual((self.notif(old)["status"], self.notif(old)["retry_count"]), ("PENDING", 0))
        self.assertEqual(service.relay(dm.T0)["claimed"], 0)
        self.assertIsNone(self.delivery(new))
