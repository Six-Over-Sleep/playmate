import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from career_share.queues import FakeQueue
from career_share.settings import SettingsError
from discord_rest.errors import DiscordNotFound, DiscordRequestError, DiscordServerError, DiscordTimeoutError
from discord_rest.permissions import PARTICIPANT_ALLOW
from meeting_share.worker_lambda import Approval, MeetingWorker, handler
from meeting_share.runner import Consumer, load

GUILD, CAT, CHANNEL, USER = ("1" * 18, "2" * 18, "3" * 18, "4" * 18)
TARGET = {"guild_id": GUILD, "category_id": CAT, "visibility": "PUBLIC"}
CREATED = {"id": CHANNEL, "guild_id": GUILD, "parent_id": CAT, "type": 0,
           "topic": "PlayMate 모임 #1 (PUBLIC)"}


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.list_guild_channels.return_value = []
        self.client.get_channel.return_value = {"id": CAT, "guild_id": GUILD, "type": 4}
        self.client.create_guild_channel.return_value = CREATED
        self.job = {"v": 1, "job_id": str(uuid4()), "recruit_id": 1,
                    "kind": "create", "target": TARGET, "verify": False}
        self.issued = set()
        self.action = "create"
        self.before_write = lambda: None

        def approve(key, grant_from):
            if key in self.issued:
                return None
            self.issued.add(key)
            self.before_write()
            return {**self.job["target"], "action": self.action, "name": "Meeting",
                    "approval_id": str(uuid4()), "expires_at": 105}

        self.approve = Mock(side_effect=approve)
        self.worker = MeetingWorker(self.client, self.approve, GUILD, CAT, clock=lambda: 100)

    def test_single_create_authorization_and_no_participant_overwrites(self):
        self.assertEqual(self.worker.process(self.job)["outcome"], "applied")
        self.assertEqual(self.worker.process(self.job)["outcome"], "skipped")
        self.client.create_guild_channel.assert_called_once()
        self.assertEqual(len(self.client.create_guild_channel.call_args.kwargs["permission_overwrites"]), 1)

    def test_concurrent_duplicate_fails_closed_when_only_one_permit_is_issued(self):
        lock = threading.Lock()
        barrier = threading.Barrier(2, timeout=3)
        approve = self.approve.side_effect

        def race(key, mode):
            barrier.wait()
            with lock:
                return approve(key, mode)

        self.approve.side_effect = race
        with ThreadPoolExecutor(max_workers=2) as pool:
            outputs = list(pool.map(self.worker.process, (self.job, self.job)))
        self.assertCountEqual([item["outcome"] for item in outputs], ["applied", "skipped"])
        self.client.create_guild_channel.assert_called_once()

    def test_timeout_then_verify_never_creates_again(self):
        self.client.create_guild_channel.side_effect = DiscordTimeoutError("timeout")
        self.assertEqual(self.worker.process(self.job)["outcome"], "unknown")
        self.assertEqual(self.worker.process({**self.job, "verify": True})["outcome"], "skipped")
        self.client.list_guild_channels.return_value = [CREATED]
        self.assertEqual(self.worker.process({**self.job, "verify": True})["channel_id"], CHANNEL)
        self.client.create_guild_channel.assert_called_once()

    def test_publish_failure_redelivery_recovers_created_channel(self):
        queue = FakeQueue()
        queue.fail_next = 1
        event = {"Records": [{"messageId": "one", "body": json.dumps(self.job)}]}
        self.assertTrue(handler(event, worker=self.worker, publisher=queue, queue_url="result")["batchItemFailures"])
        self.client.list_guild_channels.return_value = [CREATED]
        self.assertFalse(handler(event, worker=self.worker, publisher=queue, queue_url="result")["batchItemFailures"])
        self.assertEqual(json.loads(queue.bodies("result")[0])["outcome"], "found")
        self.client.create_guild_channel.assert_called_once()

    def test_conflicting_topic_or_wrong_category_never_creates(self):
        conflict = {**CREATED, "parent_id": "9" * 18}
        self.client.list_guild_channels.return_value = [CREATED, conflict]
        self.assertEqual(self.worker.process(self.job)["reason"], "duplicate_marker")
        self.client.list_guild_channels.return_value = [conflict]
        self.assertEqual(self.worker.process(self.job)["reason"], "marker_outside_scope")
        self.approve.assert_not_called()
        self.client.create_guild_channel.assert_not_called()

    def test_invalid_configured_category_is_terminal(self):
        for response in ({"id": CAT, "guild_id": GUILD, "type": 0},
                         DiscordNotFound("fixture", status=404, code=10003)):
            with self.subTest(response=type(response)):
                self.client.get_channel.side_effect = [response]
                with self.assertLogs("meeting_share.worker_lambda", level="WARNING") as logs:
                    result = self.worker.process(self.job)
                self.assertEqual((result["outcome"], result["reason"]), ("skipped", "invalid_category"))
                self.assertIn("MEETING_WRITE_FAILURE", logs.output[0])
        self.approve.assert_not_called()
        self.client.create_guild_channel.assert_not_called()

    def test_competing_workers_do_not_retry_unclassified_last_slot_400(self):
        overflow = "5" * 18
        snapshot = [{"parent_id": CAT}] * 49
        barrier = threading.Barrier(2, timeout=5)
        lock = threading.Lock()
        occupied = []

        def list_channels(_guild):
            barrier.wait()
            return snapshot

        def create(_guild, **kwargs):
            with lock:
                if kwargs["parent_id"] in occupied:
                    raise DiscordRequestError("category full fixture", status=400, code=50035)
                occupied.append(kwargs["parent_id"])
                return {**CREATED, "topic": kwargs["topic"], "parent_id": str(kwargs["parent_id"])}

        client = Mock()
        client.list_guild_channels.side_effect = list_channels
        client.get_channel.side_effect = lambda cid: {"id": str(cid), "guild_id": GUILD, "type": 4}
        client.create_guild_channel.side_effect = create
        worker = MeetingWorker(client, self.approve, GUILD, CAT,
                               additional_categories=(overflow,), clock=lambda: 100)
        second = {**self.job, "recruit_id": 2, "job_id": str(uuid4())}
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(worker.process, (self.job, second)))
        self.assertCountEqual([item["outcome"] for item in outcomes], ["applied", "rejected"])
        self.assertEqual(occupied, [int(CAT)])
        self.assertEqual(client.create_guild_channel.call_count, 2)
        # After an operator reviews the rejection and authorizes a new job, use a fresh capacity view.
        rejected = self.job if outcomes[0]["outcome"] == "rejected" else second
        client.list_guild_channels.side_effect = None
        client.list_guild_channels.return_value = [{"parent_id": CAT}] * 50
        self.assertEqual(worker.process({**rejected, "job_id": str(uuid4())})["outcome"], "applied")
        self.assertEqual(occupied, [int(CAT), int(overflow)])

    def test_general_400_and_server_wide_channel_limit_are_rejected_without_retry(self):
        for code in (50035, 30013):
            with self.subTest(code=code):
                self.job = {**self.job, "job_id": str(uuid4())}
                self.client.create_guild_channel.side_effect = DiscordRequestError("fixture", status=400, code=code)
                with self.assertLogs("meeting_share.worker_lambda", level="WARNING") as logs:
                    output = self.worker.process(self.job)
                self.assertEqual(output["outcome"], "rejected")
                self.assertIn(f"code={code}", logs.output[0])
        self.assertEqual(self.client.create_guild_channel.call_count, 2)

    def test_server_error_never_triggers_another_create(self):
        self.client.create_guild_channel.side_effect = DiscordServerError(
            "fixture", status=503, outcome_unknown=True
        )
        self.assertEqual(self.worker.process(self.job)["outcome"], "unknown")
        self.assertEqual(self.worker.process({**self.job, "verify": True})["reason"], "verification_not_found")
        self.client.create_guild_channel.assert_called_once()

    def test_preapproval_502_timeout_and_lookup_failure_stop_blocking_fifo_after_deadline(self):
        now = [100]
        self.job["approve_before"] = 300
        event = {"Records": [{"messageId": "old", "body": json.dumps(self.job)}]}
        worker = MeetingWorker(self.client, self.approve, GUILD, CAT, clock=lambda: now[0])
        self.client.list_guild_channels.side_effect = [DiscordTimeoutError("fixture"), [], []]
        self.approve.side_effect = [RuntimeError("fixture 502"), TimeoutError("fixture timeout")]
        queue = FakeQueue()
        for _ in range(3):
            self.assertEqual(handler(event, worker=worker, publisher=queue, queue_url="result"),
                             {"batchItemFailures": [{"itemIdentifier": "old"}]})
        now[0] = 300
        self.assertEqual(handler(event, worker=worker, publisher=queue, queue_url="result"),
                         {"batchItemFailures": []})
        self.assertEqual(self.client.list_guild_channels.call_count, 3)
        self.assertEqual(self.approve.call_count, 2)
        self.client.create_guild_channel.assert_not_called()

    def test_capacity_allocation_keeps_channel_50_and_uses_registered_overflow_for_51(self):
        overflow = "5" * 18
        worker = MeetingWorker(self.client, self.approve, GUILD, CAT,
                               additional_categories=(overflow,), clock=lambda: 100)
        self.client.get_channel.side_effect = lambda cid: {"id": str(cid), "guild_id": GUILD, "type": 4}
        self.client.list_guild_channels.return_value = [{"parent_id": CAT}] * 49
        self.assertEqual(worker.process(self.job)["outcome"], "applied")
        self.assertEqual(self.client.create_guild_channel.call_args.kwargs["parent_id"], int(CAT))
        self.job = {**self.job, "job_id": str(uuid4())}
        self.client.list_guild_channels.return_value = [{"parent_id": CAT}] * 50
        self.client.create_guild_channel.return_value = {**CREATED, "parent_id": overflow}
        self.assertEqual(worker.process(self.job)["outcome"], "applied")
        self.assertEqual(self.client.create_guild_channel.call_args.kwargs["parent_id"], int(overflow))
        self.client.list_guild_channels.return_value += [{"parent_id": overflow}] * 50
        self.job = {**self.job, "job_id": str(uuid4())}
        self.assertEqual(worker.process(self.job)["reason"], "categories_full")
        self.assertEqual(self.approve.call_count, 2)
        self.assertEqual(self.client.create_guild_channel.call_count, 2)

    def test_overflow_recovery_and_permissions_require_registered_scope(self):
        overflow = "5" * 18
        worker = MeetingWorker(self.client, self.approve, GUILD, CAT,
                               additional_categories=(overflow,), clock=lambda: 100)
        self.client.list_guild_channels.return_value = [{**CREATED, "parent_id": overflow}]
        self.assertEqual(worker.process(self.job)["outcome"], "found")
        self.assertEqual(self.worker.process(self.job)["reason"], "marker_outside_scope")
        self.approve.assert_not_called()
        self.permission_job()
        self.action = "revoke"
        self.client.get_channel.return_value["parent_id"] = overflow
        self.assertEqual(self.worker.process(self.job)["outcome"], "skipped")
        self.assertEqual(worker.process(self.job)["outcome"], "applied")
        for ids in ((CAT,), ("bad",), (overflow, overflow)):
            with self.assertRaises(ValueError):
                MeetingWorker(self.client, self.approve, GUILD, CAT, additional_categories=ids)

    def test_wrong_create_response_parent_is_unknown(self):
        self.client.create_guild_channel.return_value = {**CREATED, "parent_id": "5" * 18}
        self.assertEqual(self.worker.process(self.job)["outcome"], "unknown")

    def test_absent_guild_member_does_not_block_next_fifo_message(self):
        self.permission_job()
        self.action = "revoke"
        self.client.get_guild_member.side_effect = [
            DiscordNotFound("fixture", status=404, code=10007),
            self.client.get_guild_member.return_value,
        ]
        second = {**self.job, "job_id": str(uuid4())}
        event = {"Records": [{"messageId": str(i), "body": json.dumps(job)}
                             for i, job in enumerate((self.job, second))]}
        queue = FakeQueue()
        self.assertEqual(handler(event, worker=self.worker, publisher=queue, queue_url="result"),
                         {"batchItemFailures": []})
        self.assertEqual([json.loads(body)["outcome"] for body in queue.bodies("result")],
                         ["member_absent", "applied"])
        self.assertEqual(self.approve.call_count, 1)

    def permission_job(self, visibility="PUBLIC"):
        self.job = {**self.job, "kind": "permissions", "target": {
            **TARGET, "channel_id": CHANNEL, "user_id": USER, "visibility": visibility,
        }}
        self.overwrites = []
        self.client.get_channel.return_value = {**CREATED, "permission_overwrites": self.overwrites}
        self.client.get_channel.return_value["topic"] = f"PlayMate 모임 #1 ({visibility})"
        self.client.get_guild.return_value = {"id": GUILD, "owner_id": "8" * 18}
        self.client.get_guild_member.return_value = {"user": {"id": USER}, "roles": []}
        self.client.list_guild_roles.return_value = [{"id": GUILD, "permissions": "0"}]

    def test_late_grant_after_cancel_needs_new_reconcile(self):
        self.permission_job()
        self.worker.grant = True
        self.action = "grant"
        membership = {"status": "JOINED"}

        def apply(channel, user, *, allow, deny):
            self.assertEqual(membership["status"], "CANCELED")
            self.overwrites[:] = [{"id": USER, "type": 1, "allow": str(allow), "deny": str(deny)}]

        self.client.set_member_permissions.side_effect = apply
        self.before_write = lambda: membership.update(status="CANCELED")
        self.assertEqual(self.worker.process(self.job)["outcome"], "applied")
        self.assertEqual(int(self.overwrites[0]["allow"]), PARTICIPANT_ALLOW)
        self.job = {**self.job, "job_id": str(uuid4())}
        self.action = "revoke"
        self.worker.process(self.job)
        self.assertEqual(int(self.overwrites[0]["deny"]), 1 << 11)

    def test_private_revoke_clears_only_member_overwrite(self):
        self.permission_job("PRIVATE")
        self.action = "revoke"
        self.overwrites.append({"id": USER, "type": 1, "allow": str(PARTICIPANT_ALLOW), "deny": "0"})
        self.assertEqual(self.worker.process(self.job)["outcome"], "applied")
        self.client.clear_member_permissions.assert_called_once_with(int(CHANNEL), int(USER))

    def test_staff_and_manual_overwrites_do_not_get_approvals(self):
        self.permission_job()
        self.action = "revoke"
        self.client.list_guild_roles.return_value[0]["permissions"] = "8"
        self.assertEqual(self.worker.process(self.job)["outcome"], "skipped")
        self.client.list_guild_roles.return_value[0]["permissions"] = "0"
        self.overwrites.append({"id": USER, "type": 1, "allow": "1", "deny": "0"})
        self.assertEqual(self.worker.process(self.job)["outcome"], "skipped")
        self.approve.assert_not_called()

    def test_grant_is_disabled_even_if_approval_says_grant(self):
        self.permission_job()
        self.action = "grant"
        self.assertEqual(self.worker.process(self.job)["outcome"], "rejected")
        self.client.set_member_permissions.assert_not_called()


class ApprovalTests(unittest.TestCase):
    def test_denied_or_expired_approval_cannot_enable_write(self):
        url = "https://example.test/internal/discord-meeting/approve"
        transport = Mock(return_value=(409, {}, b"{}"))
        approve = Approval(url, "x" * 32, transport, clock=lambda: 100)
        self.assertIsNone(approve(str(uuid4()), "disabled"))

        def expired(method, url, headers, body, timeout):
            return 200, {}, json.dumps({"approval_id": json.loads(body)["nonce"], "expires_at": 99}).encode()

        with self.assertRaises(ValueError):
            Approval(url, "x" * 32, expired, clock=lambda: 100)(str(uuid4()), "disabled")

    def test_approval_rejects_unsecured_or_unexpected_endpoint(self):
        for url in ("http://example.test/internal/discord-meeting/approve", "https://example.test/redirect"):
            with self.assertRaises(ValueError):
                Approval(url, "x" * 32)


class ConsumerTests(unittest.TestCase):
    def test_commit_failure_preserves_message_and_success_acks(self):
        service, client = Mock(), Mock()
        data = {"v": 1, "job_id": str(uuid4()), "kind": "create", "outcome": "found", "channel_id": CHANNEL}
        client.receive_message.return_value = {"Messages": [{"ReceiptHandle": "fake", "Body": json.dumps(data)}]}
        settings = SimpleNamespace(queues={"meeting": "fake"}, wait_seconds=20, read_timeout=30,
                                   visibility_seconds=360, heartbeat_seconds=60)
        consumer = Consumer("meeting", service, client, settings)
        service.apply_result.side_effect = RuntimeError("commit unknown")
        self.assertEqual(consumer.poll_once(threading.Event()), "db_failed")
        service.heartbeat.assert_not_called()
        client.delete_message.assert_not_called()
        events = []
        service.apply_result.side_effect = lambda _: events.append("commit")
        client.delete_message.side_effect = lambda **_: events.append("ack")
        self.assertEqual(consumer.poll_once(threading.Event()), "acked")
        self.assertEqual(events, ["commit", "ack"])

    def test_disabled_mode_needs_no_secrets_or_queue(self):
        self.assertIsNone(load({}))

    def test_permission_handoff_opt_in_fails_even_without_scheduler(self):
        for key in ("DB_RUNNER_MEETING_PERMISSIONS", "DB_RUNNER_MEETING_GRANT"):
            with self.assertRaisesRegex(SettingsError, "keep Gateway permission ownership"):
                load({"DB_RUNNER_MEETING_ENABLED": "true", key: "true"})


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_legacy_policy_grants_staff_and_replaces_manual_overwrites_on_cancel(self):
        import discord
        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "offline-test", "DISCORD_GUILD_ID": GUILD,
                                      "PYTHON_DOTENV_DISABLED": "1"}):
            from services import permissions

        class Member:
            id = int(USER)
            guild_permissions = discord.Permissions(administrator=True)

        member = Member()
        manual = discord.PermissionOverwrite(send_messages=True, manage_messages=True)
        channel = SimpleNamespace(overwrites={member: manual}, set_permissions=AsyncMock())
        guild = SimpleNamespace(fetch_member=AsyncMock(return_value=member))
        with patch.object(permissions, "resolve_channel", AsyncMock(return_value=("present", channel))):
            self.assertTrue(await permissions.grant_participant_permissions(guild, int(CHANNEL), int(USER)))
            self.assertEqual(channel.set_permissions.call_args.kwargs["overwrite"], permissions.participant_overwrite())
            for visibility, expected in (
                ("PUBLIC", discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=False)),
                ("PRIVATE", None),
            ):
                self.assertTrue(await permissions.remove_participant_permissions(guild, int(CHANNEL), int(USER), visibility))
                channel.set_permissions.assert_awaited_with(member, overwrite=expected)

    async def test_new_managed_channel_records_activity_on_cache_miss(self):
        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "offline-test", "DISCORD_GUILD_ID": GUILD,
                                      "PYTHON_DOTENV_DISABLED": "1"}):
            from handlers.message_handler import handle_message
        repository = Mock()
        repository.get_managed_meeting.return_value = None
        repository.get_managed_meeting_uncached.return_value = {"recruit_id": 1}
        channel = SimpleNamespace(id=int(CHANNEL), topic="PlayMate 모임 #1 (PUBLIC)")
        await handle_message(SimpleNamespace(author=SimpleNamespace(bot=False), guild=object(), channel=channel),
                             repository)
        repository.record_activity.assert_called_once()
        self.assertEqual(repository.get_managed_meeting_uncached.call_count, 2)

    async def test_gateway_defers_to_owner_and_releases_guard(self):
        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "offline-test", "DISCORD_GUILD_ID": GUILD,
                                      "PYTHON_DOTENV_DISABLED": "1"}):
            from services.db_sync import DbSync
        repo, operation, guild = Mock(), AsyncMock(), object()
        sync = DbSync(Mock(), repo)
        repo.acquire_gateway_writer.return_value = (False, None)
        await sync._run_owned("create", operation, guild)
        operation.assert_not_awaited()
        guard = Mock()
        repo.acquire_gateway_writer.return_value = (True, guard)
        operation.side_effect = RuntimeError("fake Discord failure")
        with self.assertRaises(RuntimeError):
            await sync._run_owned("create", operation, guild)
        operation.assert_awaited_once_with(guild)
        guard.close.assert_called_once()
