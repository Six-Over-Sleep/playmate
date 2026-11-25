import hashlib
import hmac
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch
from uuid import uuid4

from app.routers import discord_meeting_internal as api


class ApprovalTests(unittest.TestCase):
    def test_signature_is_bound_to_body_and_timestamp(self):
        secret = "offline-test-only-key" * 2
        stamp = "1780000000"
        body = b'{"job_id":"job-a"}'
        sig = hmac.new(secret.encode(), b"POST " + api.APPROVAL_PATH.encode() + b"\n" +
                       stamp.encode() + b"\n" + body, hashlib.sha256).hexdigest()
        self.assertTrue(api.authenticate(body, stamp, sig, secret, int(stamp)))
        self.assertFalse(api.authenticate(body + b" ", stamp, sig, secret, int(stamp)))
        self.assertFalse(api.authenticate(body, stamp, sig, secret, int(stamp) + 16))

    def authorize(self, job, *rows, nonce=None):
        cur = Mock()
        cur.fetchone.side_effect = [
            {"consumer_ready": True, "create_owner": "lambda", "permission_owner": "lambda"}, None, job, *rows
        ]

        @contextmanager
        def cursor(*, commit):
            self.assertTrue(commit)
            yield cur

        with patch.object(api, "db_cursor", cursor):
            approved = api.issue_approval(str(uuid4()), nonce or str(uuid4()), "absent")
        return approved, cur

    def test_replayed_consumed_approval_does_not_get_second_write(self):
        result, cur = self.authorize({"fresh": True, "approved_at": "already-consumed", "finished_at": None})
        self.assertIsNone(result)
        self.assertEqual(cur.execute.call_count, 3)

    def test_stale_membership_and_untracked_revocation_are_denied(self):
        job = {"fresh": True, "approved_at": None, "finished_at": None, "kind": "permissions",
               "fingerprint": "joined-1", "member_id": 2, "recruit_id": 1,
               "target": {"user_id": "user-a", "channel_id": "channel-a"}}
        current = {"fingerprint": "canceled-2", "desired": "revoke", "managed": True,
                   "discord_id": "user-a", "discord_text_channel_id": "channel-a"}
        self.assertIsNone(self.authorize(job, current)[0])
        self.assertIsNone(self.authorize(job, {**current, "fingerprint": "joined-1", "managed": False})[0])

    def test_approval_response_is_returned_after_commit(self):
        job = {"fresh": True, "approved_at": None, "finished_at": None, "kind": "create",
               "recruit_id": 1, "target": {"guild_id": "example"}}
        nonce = str(uuid4())
        result, cur = self.authorize(job, {"title": "A"}, {"expires_at": 102.0}, nonce=nonce)
        self.assertEqual(result, {"guild_id": "example", "name": "A", "action": "create",
                                  "approval_id": nonce, "expires_at": 102.0})
        self.assertIn("approved_at=clock_timestamp()", cur.execute.call_args.args[0])
