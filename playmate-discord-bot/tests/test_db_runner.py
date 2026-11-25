"""Offline runner tests: no real AWS credentials, network or PostgreSQL are used."""
import json
import os
import signal
import socket
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from career_share.settings import SettingsError
from career_share.repository import InMemoryCareerShareRepository
from career_share.service import CareerShareService
from career_share.queues import FakeQueue
from db_runner.settings import load_settings
from db_runner.scheduler import Scheduler
from db_runner.results import ResultConsumer, Lease, validate_result
from db_runner.runtime import ProcessLock, install_signals
from db_runner import __main__ as entry
from db_runner import services as wiring

UTC = timezone.utc
BASE = "https://sqs.ap-northeast-2.amazonaws.com/123456789012/playmate-test-"


def environment(*features):
    env = dict(PLAYMATE_ENVIRONMENT="test", AWS_DEFAULT_REGION="ap-northeast-2", DB_HOST="127.0.0.1",
               DB_USER="test", DB_PASSWORD="test-only", DB_NAME="runner_test", PLAYMATE_WEB_BASE_URL="https://playmate.example.com",
               CAREER_SHARE_CUTOVER_AT="2026-01-01T00:00:00+00:00", HOT_SHARE_DB_TIMEZONE="UTC")
    for feature in features:
        env[f"DB_RUNNER_{feature.upper()}_ENABLED"] = "true"
        env[f"{feature.upper()}_SHARE_SEND_QUEUE_URL"] = BASE + feature + "-share-send" + (".fifo" if feature == "dm" else "")
        env[f"{feature.upper()}_SHARE_RESULT_QUEUE_URL"] = BASE + feature + "-share-result"
    if "dm" in features:
        env["DB_RUNNER_DM_MODE"] = "relay"
    return env


def message(kind="IMMEDIATE", unit="post-1", **fields):
    body = dict(v=1, type="result", kind=kind, unit_id=unit, claim_token="old-token", job_id=unit + ":old-token",
                outcome="SENT", message_id="123456789012345678")
    body.update(fields)
    return {"MessageId": "id", "ReceiptHandle": "SECRET-RECEIPT", "Body": json.dumps(body)}


class FakeSqs:
    def __init__(self):
        self.events, self.messages, self.fail_delete, self.fail_visibility = [], [], False, False

    def receive_message(self, **kwargs):
        self.events.append("receive")
        return {"Messages": self.messages[:1]}

    def change_message_visibility(self, **kwargs):
        self.events.append("renew")
        if self.fail_visibility:
            raise TimeoutError("SECRET-RECEIPT")

    def delete_message(self, **kwargs):
        self.events.append("delete")
        if self.fail_delete:
            raise TimeoutError("SECRET-RECEIPT")
        self.messages.clear()


class OfflineTest(unittest.TestCase):
    def setUp(self):
        self.patches = [mock.patch("socket.getaddrinfo", side_effect=AssertionError("network forbidden")),
                        mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")),
                        mock.patch.dict(os.environ, {"AWS_EC2_METADATA_DISABLED": "true", "PLAYMATE_TEST_PG_DSN": ""})]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)


class SettingsTests(OfflineTest):
    def test_safe_defaults_no_clients(self):
        settings = load_settings({})
        self.assertFalse(settings.features)
        with mock.patch.object(entry, "sqs_client", side_effect=AssertionError("AWS forbidden")), \
                mock.patch.object(entry, "build_service", side_effect=AssertionError("DB forbidden")):
            for mode in ("scheduler", "results"):
                entry.run(mode, settings, threading.Event())

    def test_all_features(self):
        settings = load_settings(environment("career", "hot", "dm"))
        self.assertEqual(settings.features, ("career", "hot", "dm"))
        self.assertGreater(settings.read_timeout, settings.wait_seconds)

    def test_validation(self):
        cases = [("DB_RUNNER_CAREER_ENABLED", "tru"), ("DB_PASSWORD", ""), ("DB_PORT", "70000"),
                 ("PLAYMATE_WEB_BASE_URL", ""), ("AWS_DEFAULT_REGION", ""), ("PLAYMATE_ENVIRONMENT", "production"),
                 ("DB_RUNNER_READ_TIMEOUT_SECONDS", "20"), ("DB_RUNNER_DIGEST_GRACE_MINUTES", "-1"),
                 ("CAREER_SHARE_RESULT_QUEUE_URL", BASE.replace("-test-", "-prod-") + "career-share-result")]
        for key, value in cases:
            with self.subTest(key=key), self.assertRaises(SettingsError):
                load_settings(dict(environment("career"), **{key: value}))

    def test_cross_feature_queue_and_dm_opt_in(self):
        env = environment("career", "hot")
        env["HOT_SHARE_RESULT_QUEUE_URL"] = env["CAREER_SHARE_RESULT_QUEUE_URL"]
        with self.assertRaises(SettingsError):
            load_settings(env)
        env = environment("dm")
        env["DB_RUNNER_DM_MODE"] = "disabled"
        with self.assertRaises(SettingsError):
            load_settings(env)
        env = environment("dm")
        env["DM_SHARE_SEND_QUEUE_URL"] = env["DM_SHARE_SEND_QUEUE_URL"].removesuffix(".fifo")
        with self.assertRaises(SettingsError):
            load_settings(env)

    def test_check_never_builds_clients(self):
        with mock.patch.dict(os.environ, environment("career"), clear=True), \
                mock.patch.object(sys, "argv", ["db_runner", "scheduler", "--check"]), \
                mock.patch.object(entry, "run", side_effect=AssertionError("must not run")):
            self.assertEqual(entry.main(), 0)

    def test_iam_role_only_and_timeouts(self):
        resolver = SimpleNamespace(providers=[SimpleNamespace(METHOD=x) for x in ("env", "shared-credentials-file", "iam-role")])
        session = mock.Mock()
        session.get_component.return_value = resolver
        config = mock.Mock(side_effect=lambda **kw: kw)
        boto = mock.Mock()
        botocore_session = SimpleNamespace(get_session=lambda: session)
        botocore = SimpleNamespace(session=botocore_session)
        with mock.patch.dict(sys.modules, {"boto3": boto, "botocore": botocore, "botocore.session": botocore_session,
                                          "botocore.config": SimpleNamespace(Config=config)}):
            wiring.sqs_client(load_settings(environment("career")))
        self.assertEqual([p.METHOD for p in resolver.providers], ["iam-role"])
        kwargs = boto.Session.return_value.client.call_args.kwargs
        self.assertEqual(kwargs["config"]["read_timeout"], 30)
        self.assertEqual(kwargs["config"]["retries"]["total_max_attempts"], 2)


class ResultsTests(OfflineTest):
    def setUp(self):
        super().setUp()
        self.settings = load_settings(environment("career", "hot", "dm"))
        self.sqs = FakeSqs()
        self.service = mock.Mock()
        self.service.apply_result.side_effect = lambda result: self.sqs.events.append("commit") or "applied"
        self.consumer = ResultConsumer("career", self.service, self.sqs, self.settings)

    def test_ack_only_after_commit(self):
        self.assertEqual(self.consumer.process(message()), "acked")
        self.assertEqual(self.sqs.events, ["renew", "commit", "delete"])

    def test_db_and_commit_unknown_never_delete(self):
        for error in (ConnectionError("DB_PASSWORD"), TimeoutError("commit uncertain")):
            self.sqs.events.clear()
            self.service.apply_result.side_effect = error
            self.assertEqual(self.consumer.process(message()), "db_failed")
            self.assertNotIn("delete", self.sqs.events)

    def test_normal_return_variants(self):
        self.service.apply_result.side_effect = None
        for result in ("applied", "ignored", "duplicate", "auth_hold", "missing_notification", "applied_post_not_shareable"):
            self.service.apply_result.return_value = result
            self.assertEqual(self.consumer.process(message()), "acked")

    def test_wrong_queue_rejected_before_db(self):
        for bad in (message("HOT", "hot-1"), message("DM", "dm-1"), message("DIGEST", "post-1")):
            self.assertEqual(self.consumer.process(bad), "invalid")
        self.service.apply_result.assert_not_called()
        self.assertEqual(self.sqs.events, [])

    def test_each_feature_route(self):
        for feature, kind, unit in (("career", "DIGEST", "digest-2026-11-25"), ("hot", "HOT", "hot-2"), ("dm", "DM", "dm-3")):
            self.assertEqual(validate_result(feature, message(kind, unit)["Body"])["kind"], kind)

    def test_delete_failure_redelivery_uses_existing_idempotence(self):
        repo = InMemoryCareerShareRepository()
        now = datetime(2026, 11, 25, 11, tzinfo=UTC)
        repo.add_post(1, created_at=now)
        from career_share.settings import load_db_settings
        service = CareerShareService(repo, FakeQueue(), load_db_settings(environment("career")), clock=lambda: now)
        service.relay(now)
        claim = repo.rows[1]["claim_token"]
        msg = message(claim_token=claim)
        consumer = ResultConsumer("career", service, self.sqs, self.settings)
        self.sqs.fail_delete = True
        self.assertEqual(consumer.process(msg), "delete_failed")
        self.assertEqual(repo.rows[1]["status"], "SENT")
        self.sqs.fail_delete = False
        self.assertEqual(consumer.process(msg), "acked")
        self.assertEqual(repo.rows[1]["attempt_count"], 1)
        # A stale claim is ignored by the existing repository, then ACKed by the adapter.
        self.assertEqual(consumer.process(message(claim_token="stale")), "acked")
        self.assertEqual(repo.rows[1]["status"], "SENT")

    def test_poison_redrive_simulation(self):
        poison = {"Body": "not json", "ReceiptHandle": "secret"}
        class RedriveSqs(FakeSqs):
            # Each receive represents a new visibility window, not an AWS integration test.
            def __init__(self):
                super().__init__()
                self.receives, self.dlq, self.messages = 0, [], [poison]

            def receive_message(self, **kwargs):
                self.receives += 1
                if self.receives > 5 and self.messages:
                    self.dlq.extend(self.messages)
                    self.messages.clear()
                return {"Messages": self.messages[:1]}

        self.consumer.client = redrive = RedriveSqs()
        for _ in range(5):
            self.assertEqual(self.consumer.poll_once(threading.Event()), "invalid")
        self.assertEqual(self.consumer.poll_once(threading.Event()), "empty")
        self.assertEqual(redrive.dlq, [poison])
        self.assertNotIn("delete", self.sqs.events)
        self.service.apply_result.assert_not_called()

    def test_database_transaction_commit_boundary_with_fake_connection(self):
        from repositories.db import Database
        class Connection:
            closed = False
            fail_commit = False

            def transaction(inner):
                from contextlib import contextmanager
                @contextmanager
                def transaction():
                    yield
                    if inner.fail_commit:
                        raise TimeoutError("commit reply lost")
                    self.sqs.events.append("commit")
                return transaction()

            def cursor(inner, **kwargs):
                from contextlib import nullcontext
                return nullcontext(mock.sentinel.cursor)

        connection = Connection()
        db = Database(lambda: connection)
        self.service.apply_result.side_effect = lambda result: db.transaction(lambda cur: "applied")
        self.assertEqual(self.consumer.process(message()), "acked")
        self.assertEqual(self.sqs.events, ["renew", "commit", "delete"])
        self.sqs.events.clear()
        connection.fail_commit = True
        self.assertEqual(self.consumer.process(message()), "db_failed")
        self.assertNotIn("delete", self.sqs.events)

    def test_heartbeat_renews_while_processing(self):
        lease = Lease(self.sqs, self.consumer.queue, "secret", self.settings)
        lease.done = mock.Mock()
        lease.done.wait.side_effect = [False, True]
        lease.run()
        self.assertEqual(self.sqs.events, ["renew"])
        self.assertTrue(lease.safe_to_ack())

    def test_lease_failure_no_ack_or_apply(self):
        self.sqs.fail_visibility = True
        self.assertEqual(self.consumer.process(message()), "lease_failed")
        self.service.apply_result.assert_not_called()
        self.assertNotIn("delete", self.sqs.events)

    def test_lease_failure_during_db_preserves_message(self):
        def commit(result):
            self.sqs.fail_visibility = True
            lease.renew()
        lease = Lease(self.sqs, self.consumer.queue, "secret", self.settings)
        self.consumer.lease_factory = lambda *args: lease
        self.service.apply_result.side_effect = commit
        self.assertEqual(self.consumer.process(message()), "lease_failed")
        self.assertNotIn("delete", self.sqs.events)

    def test_expired_lease_never_ack(self):
        lease = Lease(self.sqs, self.consumer.queue, "secret", self.settings)
        self.consumer.lease_factory = lambda *args: lease
        self.service.apply_result.side_effect = lambda result: setattr(lease, "deadline", 0)
        self.assertEqual(self.consumer.process(message()), "lease_failed")
        self.assertNotIn("delete", self.sqs.events)

    def test_no_sensitive_exception_logging(self):
        self.service.apply_result.side_effect = RuntimeError("SECRET-RECEIPT Discord-token DB-password recipient-id")
        with self.assertLogs("db_runner", level="ERROR") as logs:
            self.consumer.process(message())
        output = " ".join(logs.output)
        for value in ("SECRET-RECEIPT", "Discord-token", "DB-password", "recipient-id"):
            self.assertNotIn(value, output)

    def test_stop_before_and_after_receive(self):
        stop = threading.Event()
        stop.set()
        self.consumer.poll_once(stop)
        self.assertEqual(self.sqs.events, [])
        stop.clear()
        self.sqs.receive_message = lambda **kwargs: stop.set() or {"Messages": [message()]}
        self.assertEqual(self.consumer.poll_once(stop), "stopped")
        self.service.apply_result.assert_not_called()

    def test_stop_during_commit_drains_ack_then_no_new_poll(self):
        stop = threading.Event()
        self.sqs.messages = [message()]
        self.service.apply_result.side_effect = lambda result: stop.set() or self.sqs.events.append("commit")
        self.consumer.run(stop)
        self.assertEqual(self.sqs.events, ["receive", "renew", "commit", "delete"])

    def test_queue_failure_isolated(self):
        bad = ResultConsumer("career", self.service, self.sqs, self.settings)
        bad.service.apply_result.side_effect = ConnectionError()
        good_service = mock.Mock()
        good_sqs = FakeSqs()
        good = ResultConsumer("hot", good_service, good_sqs, self.settings)
        threads = [threading.Thread(target=bad.process, args=(message(),)),
                   threading.Thread(target=good.process, args=(message("HOT", "hot-2"),))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(2)
            self.assertFalse(t.is_alive())
        self.assertNotIn("delete", self.sqs.events)
        self.assertIn("delete", good_sqs.events)


class SchedulerTests(OfflineTest):
    def setUp(self):
        super().setUp()
        self.settings = load_settings(environment("career", "hot", "dm"))
        self.now = datetime(2026, 11, 25, 10, 59, tzinfo=UTC)
        self.elapsed = 0
        self.services = {f: mock.Mock() for f in self.settings.features}
        self.scheduler = self.new_scheduler()
        self.stop = threading.Event()

    def new_scheduler(self):
        return Scheduler(self.services, self.settings, clock=lambda: self.now, monotonic=lambda: self.elapsed)

    def advance(self, seconds):
        self.elapsed += seconds
        self.now += timedelta(seconds=seconds)
        self.scheduler.tick(self.stop)

    def test_intervals_and_kst_digest(self):
        self.scheduler.tick(self.stop)
        self.services["career"].digest.assert_not_called()
        self.advance(59)
        self.assertEqual(self.services["career"].relay.call_count, 1)
        self.advance(1)
        self.assertEqual(self.services["career"].relay.call_count, 2)
        actual, scheduled = self.services["career"].digest.call_args.args
        self.assertEqual(scheduled.hour, 20)
        self.assertEqual(scheduled.utcoffset(), timedelta(hours=9))
        self.advance(240)
        self.assertEqual(self.services["hot"].relay.call_count, 2)
        self.services["career"].digest.assert_called_once()
        for service in self.services.values():
            service.baseline.assert_not_called()

    def test_execution_duration_does_not_shift_minute_slots(self):
        def work(now):
            self.elapsed += 10
            self.now += timedelta(seconds=10)
        self.services["career"].relay.side_effect = work
        self.scheduler.tick(self.stop)
        self.advance(49)
        self.assertEqual(self.services["career"].relay.call_count, 1)
        self.advance(1)
        self.assertEqual(self.services["career"].relay.call_count, 2)

    def test_digest_grace_boundaries_and_restart(self):
        for offset, expected in ((-1, 0), (0, 1), (1800, 1), (1801, 0)):
            with self.subTest(offset=offset):
                self.now = datetime(2026, 11, 25, 11, tzinfo=UTC) + timedelta(seconds=offset)
                self.services["career"].digest.reset_mock()
                scheduler = self.new_scheduler()
                scheduler.tick(self.stop)
                scheduler.tick(self.stop)
                self.assertEqual(self.services["career"].digest.call_count, expected)
        self.now = datetime(2026, 11, 25, 15, 1, tzinfo=UTC)  # next KST day, no yesterday catch-up
        self.services["career"].digest.reset_mock()
        self.new_scheduler().tick(self.stop)
        self.services["career"].digest.assert_not_called()

    def test_custom_grace_and_failure_once(self):
        from dataclasses import replace
        self.settings = replace(self.settings, digest_grace_minutes=5)
        self.now = datetime(2026, 11, 25, 11, 6, tzinfo=UTC)
        self.new_scheduler().tick(self.stop)
        self.services["career"].digest.assert_not_called()
        self.now -= timedelta(minutes=2)
        scheduler = self.new_scheduler()
        self.services["career"].digest.side_effect = TimeoutError()
        scheduler.tick(self.stop)
        scheduler.tick(self.stop)
        self.services["career"].digest.assert_called_once()

    def test_recover_only_600_seconds(self):
        from dataclasses import replace
        self.settings = replace(self.settings, dm_mode="recover")
        self.scheduler = self.new_scheduler()
        self.scheduler.tick(self.stop)
        self.advance(599)
        self.services["dm"].recover.assert_called_once()
        self.advance(1)
        self.assertEqual(self.services["dm"].recover.call_count, 2)
        self.services["dm"].relay.assert_not_called()

    def test_failure_isolation_coalesce_and_stop(self):
        self.services["career"].relay.side_effect = ConnectionError()
        self.scheduler.tick(self.stop)
        self.services["hot"].relay.assert_called_once()
        self.advance(3600)
        self.assertEqual(self.services["career"].relay.call_count, 2)
        self.stop.set()
        self.advance(3600)
        self.assertEqual(self.services["career"].relay.call_count, 2)

    def test_overlap_and_long_job(self):
        self.services["career"].relay.side_effect = lambda now: (self.scheduler.tick(self.stop), self.advance(120))
        self.scheduler.tick(self.stop)
        self.services["career"].relay.assert_called_once()
        self.scheduler.tick(self.stop)
        self.services["career"].relay.assert_called_once()


class LifecycleTests(OfflineTest):
    def test_signal_handlers_only_request_stop(self):
        handlers = {}
        stop = threading.Event()
        with mock.patch("signal.signal", side_effect=lambda sig, handler: handlers.update({sig: handler})):
            install_signals(stop)
        for sig in (signal.SIGTERM, signal.SIGINT):
            stop.clear()
            handlers[sig](sig, None)
            self.assertTrue(stop.is_set())

    def test_process_lock_release_and_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            with ProcessLock(directory, "scheduler"), ProcessLock(directory, "results"):
                with self.assertRaises(RuntimeError):
                    with ProcessLock(directory, "scheduler"):
                        pass
            with ProcessLock(directory, "scheduler"):
                pass

    def test_service_builders_and_fifo_wrapper_unchanged(self):
        from dm_share.fifo import DmFifoPublisher
        from repositories.dm_delivery_repository import SENDER_LAMBDA, GATEWAY_TAKEOVER_MINUTES, AUTH_HOLD_MINUTES
        with mock.patch.dict(os.environ, environment("career", "hot", "dm"), clear=True):
            for feature in ("career", "hot", "dm"):
                service = wiring.build_service(feature)
                wiring.configure_publisher(service, mock.sentinel.sqs)
                if feature == "dm":
                    self.assertIsInstance(service.publisher, DmFifoPublisher)
                    self.assertIs(service.publisher.inner._client, mock.sentinel.sqs)
                self.assertIsNone(service.repo._db._conn)  # no DB touched by builder
                wiring.close_service(service)
        self.assertEqual((SENDER_LAMBDA, GATEWAY_TAKEOVER_MINUTES, AUTH_HOLD_MINUTES), ("LAMBDA", 16, 10))

    def test_results_threads_close_and_crash_is_nonzero(self):
        settings = load_settings(environment("career", "hot"))
        services = {feature: mock.Mock() for feature in settings.features}
        stop = threading.Event()
        with mock.patch.object(entry, "build_service", side_effect=lambda feature: services[feature]), \
                mock.patch.object(entry, "sqs_client", return_value=mock.Mock()), \
                mock.patch.object(entry.ResultConsumer, "run", side_effect=RuntimeError("secret")), \
                mock.patch.object(entry, "close_service") as close:
            with self.assertRaises(RuntimeError):
                entry.run("results", settings, stop)
        self.assertTrue(stop.is_set())
        self.assertEqual(close.call_count, 2)

    def test_cleanup_failure_does_not_skip_other_resource(self):
        client = mock.Mock()
        with mock.patch.object(entry, "close_service", side_effect=RuntimeError("secret")):
            entry.cleanup(mock.sentinel.service, client)
        client.close.assert_called_once()

    def test_database_close_releases_connection(self):
        from repositories.db import Database
        db = Database(lambda: None)
        connection = db._conn = mock.Mock()
        db.close()
        db.close()
        connection.close.assert_called_once()
        self.assertIsNone(db._conn)

    def test_dm_auth_service_pauses_verification_without_new_policy(self):
        from dm_share.service import DmShareService
        from dm_share.settings import load_dm_settings
        repo = mock.Mock()
        repo.auth_open.return_value = True
        service = DmShareService(repo, FakeQueue(), load_dm_settings(environment("dm")))
        now = datetime(2026, 11, 25, tzinfo=UTC)
        result = service.recover(now)
        self.assertTrue(result["paused_auth"])
        repo.expire_lambda_claims.assert_called_once_with(now)
        repo.claim_verifications.assert_not_called()
        repo.finalize_unverifiable.assert_not_called()

    def test_dm_401_existing_repository_does_not_increment_notification_retry(self):
        from repositories.dm_delivery_repository import DmDeliveryRepository
        repo = DmDeliveryRepository(mock.Mock())
        cursor = mock.Mock()
        now = datetime(2026, 11, 25, tzinfo=UTC)
        result = repo._apply_auth(cursor, {"status": "PENDING"}, 1, "FAILED_RETRY", "job", now)
        self.assertEqual(result, "auth_failed")
        self.assertEqual(cursor.execute.call_count, 1)
        sql, params = cursor.execute.call_args.args
        self.assertIn("notification_dm_deliveries", sql)
        self.assertNotIn("retry_count", sql)
        self.assertIn("DISCORD_AUTH_401", params[1])


class ReviewRegressionTests(OfflineTest):
    def test_visibility_cap_includes_poll_and_processing_time(self):
        settings = load_settings(dict(environment("career"), DB_RUNNER_VISIBILITY_SECONDS="43200"))
        sqs = FakeSqs()
        sqs.messages = [message()]
        elapsed = 100.0
        renewals = []

        def receive(**kwargs):
            nonlocal elapsed
            self.assertEqual(kwargs["VisibilityTimeout"], 43200)
            elapsed += 20
            return {"Messages": sqs.messages}

        sqs.receive_message = receive
        sqs.change_message_visibility = lambda **kw: renewals.append(kw["VisibilityTimeout"])
        service = mock.Mock()
        consumer = ResultConsumer("career", service, sqs, settings)

        def commit(result):
            nonlocal elapsed
            elapsed += 60.5
            consumer.lease.renew()
            elapsed = 100 + 43200
            consumer.lease.renew()

        service.apply_result.side_effect = commit
        with mock.patch("db_runner.results.time.monotonic", side_effect=lambda: elapsed):
            self.assertEqual(consumer.poll_once(threading.Event()), "lease_failed")
        self.assertEqual(renewals, [43179, 43118])
        self.assertNotIn("delete", sqs.events)

    def check_heartbeat_during_commit(self, *, fail=False, hang=False):
        from dataclasses import replace
        settings = replace(load_settings(environment("career")), heartbeat_seconds=0.01)
        sqs = FakeSqs()
        service = mock.Mock()
        consumer = ResultConsumer("career", service, sqs, settings)
        renewal_started, release, joining = threading.Event(), threading.Event(), threading.Event()
        allow_renewal, deletes = threading.Event(), mock.Mock()
        outcomes = []
        sqs.delete_message = deletes

        def renew(**kwargs):
            if threading.current_thread().name != "result-visibility":
                return
            renewal_started.set()
            if not release.wait(5):
                raise TimeoutError()
            if fail:
                raise ConnectionError()

        sqs.change_message_visibility = renew

        def commit(result):
            if not renewal_started.wait(5):
                raise AssertionError("heartbeat did not start")
            thread = consumer.lease.thread
            original_join = thread.join

            def tracked_join(*args, **kwargs):
                joining.set()
                original_join(*args, **kwargs)

            thread.join = tracked_join

        service.apply_result.side_effect = commit
        worker = threading.Thread(target=lambda: outcomes.append(consumer.process(message())), daemon=True)
        try:
            with mock.patch("db_runner.results.HEARTBEAT_JOIN_SECONDS", 0 if hang else 3):
                worker.start()
                self.assertTrue(joining.wait(5), "commit completed but lease shutdown did not start")
                deletes.assert_not_called()
                if hang:
                    worker.join(2)
                    self.assertFalse(worker.is_alive(), "consumer waited indefinitely for heartbeat")
                    self.assertTrue(consumer.heartbeat_running)
                    sqs.receive_message = mock.Mock()
                    self.assertEqual(consumer.poll_once(allow_renewal), "lease_failed")
                    sqs.receive_message.assert_not_called()
                release.set()
                worker.join(5)
                self.assertFalse(worker.is_alive())
            self.assertEqual(outcomes, ["lease_failed" if fail or hang else "acked"])
            if fail or hang:
                deletes.assert_not_called()
            else:
                deletes.assert_called_once()
                self.assertFalse(consumer.heartbeat_running)
        finally:
            release.set()
            worker.join(5)
            if consumer.lease is not None:
                consumer.lease.thread.join(5)

    def test_db_commit_waits_for_successful_heartbeat_before_delete(self):
        self.check_heartbeat_during_commit()

    def test_heartbeat_failure_after_commit_prevents_delete(self):
        self.check_heartbeat_during_commit(fail=True)

    def test_heartbeat_join_timeout_prevents_delete_and_next_receive(self):
        self.check_heartbeat_during_commit(hang=True)

    def test_digest_grace_must_be_positive_integer(self):
        name = "DB_RUNNER_DIGEST_GRACE_MINUTES"
        for value in ("0", "-1", "1.5"):
            with self.subTest(value=value), self.assertRaisesRegex(SettingsError, name):
                load_settings({name: value})
        self.assertEqual(load_settings({name: "1"}).digest_grace_minutes, 1)
        self.assertEqual(load_settings({}).digest_grace_minutes, 30)

    def test_digest_delayed_execution_across_kst_date_boundary(self):
        settings = load_settings(environment("career"))
        now = datetime(2026, 11, 25, 11, 20, tzinfo=UTC)
        service, stop = mock.Mock(), threading.Event()
        scheduler = Scheduler({"career": service}, settings, clock=lambda: now, monotonic=lambda: 1)
        scheduler.tick(stop)
        actual, scheduled = service.digest.call_args.args
        self.assertEqual(actual, now)
        self.assertEqual(scheduled.isoformat(), "2026-11-25T20:00:00+09:00")
        now = datetime(2026, 11, 25, 15, 0, tzinfo=UTC)
        scheduler.tick(stop)
        service.digest.assert_called_once()
        now = datetime(2026, 11, 26, 11, 1, tzinfo=UTC)
        scheduler.tick(stop)
        self.assertEqual(service.digest.call_count, 2)
        self.assertEqual(service.digest.call_args.args[1].isoformat(), "2026-11-26T20:00:00+09:00")


if __name__ == "__main__":
    unittest.main()
