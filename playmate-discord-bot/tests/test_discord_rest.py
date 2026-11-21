"""Discord REST 클라이언트(discord_rest) 테스트 (서버리스 전환 1차).

실제 Discord에는 연결하지 않는다. 127.0.0.1의 가짜 HTTP 서버가 Discord API v10 응답을 흉내 낸다.
DB, AWS, Gateway도 쓰지 않는다. 대기(sleep)는 기록만 하므로 429/재시도 시험이 즉시 끝난다.
실행: python -m pytest tests/test_discord_rest.py  (또는 python tests/test_discord_rest.py)
"""
import ast
import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DISCORD_BOT_TOKEN", "verification-only")
os.environ.setdefault("DISCORD_GUILD_ID", "1")
os.environ["PLAYMATE_WEB_BASE_URL"] = ""

from discord_rest import (  # noqa: E402
    DiscordAuthError, DiscordForbidden, DiscordNetworkError, DiscordNotFound, DiscordRateLimited,
    DiscordRequestError, DiscordRestClient, DiscordServerError, DiscordTimeoutError,
)
from discord_rest import inactivity, permissions  # noqa: E402

TOKEN = "SECRET-TOKEN-do-not-log.abc123"
GUILD, CHANNEL, USER = 111111111111111111, 222222222222222222, 333333333333333333
KST = timezone(timedelta(hours=9))


class FakeDiscord:
    """Discord API 흉내. queue()로 (method, path)별 응답을 순서대로 넣고, 비어 있으면 200 {}을 돌려준다."""

    def __init__(self):
        self.requests, self.queues, self.executed = [], {}, []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _serve(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length).decode("utf-8") if length else ""
                path = self.path.split("?")[0].removeprefix("/api/v10")
                outer.requests.append({"method": self.command, "path": path, "query": self.path.partition("?")[2],
                                       "headers": dict(self.headers), "body": json.loads(body) if body else None})
                queue = outer.queues.get((self.command, path))
                spec = queue.pop(0) if queue else {"status": 200, "body": {}}
                if spec.get("executes", spec.get("status", 200) < 400):
                    outer.executed.append((self.command, path))
                time.sleep(spec.get("delay", 0))
                payload = json.dumps(spec["body"]).encode() if not isinstance(spec["body"], bytes) else spec["body"]
                try:
                    self.send_response(spec.get("status", 200))
                    for key, value in (spec.get("headers") or {}).items():
                        self.send_header(key, value)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except OSError:
                    pass

            do_GET = do_POST = do_PUT = do_DELETE = _serve

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_port}/api/v10"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def queue(self, method, path, *specs):
        self.queues.setdefault((method, path), []).extend(specs)

    def count(self, method, path):
        return sum(1 for r in self.requests if r["method"] == method and r["path"] == path)

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class RestTestCase(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDiscord()
        self.addCleanup(self.fake.close)
        self.sleeps = []

    def make(self, **kw):
        kw.setdefault("sleep", self.sleeps.append)
        kw.setdefault("timeout", 2.0)
        return DiscordRestClient(TOKEN, base_url=self.fake.url, **kw)


class NormalResponses(RestTestCase):
    def test_read_calls(self):
        self.fake.queue("GET", f"/guilds/{GUILD}/channels", {"body": [{"id": "1", "name": "a", "type": 0}]})
        self.fake.queue("GET", f"/channels/{CHANNEL}", {"body": {"id": str(CHANNEL), "type": 0, "topic": "t"}})
        client = self.make()
        self.assertEqual(client.list_guild_channels(GUILD)[0]["name"], "a")
        self.assertEqual(client.get_channel(CHANNEL)["topic"], "t")
        first = self.fake.requests[0]["headers"]
        self.assertEqual(first["Authorization"], f"Bot {TOKEN}")  # 전송에는 쓰이고 (로그에는 안 남는다, 아래 시험)
        self.assertTrue(first["User-Agent"].startswith("DiscordBot ("))

    def test_send_message_shape(self):
        self.fake.queue("POST", f"/channels/{CHANNEL}/messages", {"body": {"id": "9"}})
        self.make().send_message(CHANNEL, content="안녕", embeds=[{"title": "t"}], nonce="n-1")
        body = self.fake.requests[0]["body"]
        self.assertEqual(body["content"], "안녕")
        self.assertEqual(body["embeds"], [{"title": "t"}])
        self.assertEqual(body["allowed_mentions"], {"parse": []})  # 기본은 멘션 없음
        self.assertEqual((body["nonce"], body["enforce_nonce"]), ("n-1", True))
        self.assertEqual(self.fake.requests[0]["headers"]["Content-Type"], "application/json")

    def test_message_validation(self):
        client = self.make()
        for kwargs in ({}, {"content": "x" * 2001}, {"embeds": [{}] * 11}):
            with self.assertRaises(ValueError):
                client.send_message(CHANNEL, **kwargs)
        with self.assertRaises(ValueError):
            client.get_channel("../users/@me")  # 경로 조작 불가
        self.assertEqual(self.fake.requests, [])

    def test_dm_creates_channel_then_sends(self):
        self.fake.queue("POST", "/users/@me/channels", {"body": {"id": "555555555555555555"}})
        self.fake.queue("POST", "/channels/555555555555555555/messages", {"body": {"id": "1"}})
        self.make().send_dm(USER, content="DM")
        self.assertEqual(self.fake.requests[0]["body"], {"recipient_id": str(USER)})
        self.assertEqual(self.fake.requests[1]["path"], "/channels/555555555555555555/messages")

    def test_create_and_delete_channel(self):
        self.fake.queue("POST", f"/guilds/{GUILD}/channels", {"body": {"id": str(CHANNEL)}})
        client = self.make()
        overwrites = permissions.meeting_channel_overwrites(GUILD, [USER, USER], "PUBLIC")
        client.create_guild_channel(GUILD, name=" 모임 ", parent_id=7, topic="PlayMate 모임 #1 (PUBLIC)",
                                    permission_overwrites=overwrites, reason="생성")
        body = self.fake.requests[0]["body"]
        self.assertEqual((body["name"], body["type"], body["parent_id"]), ("모임", 0, "7"))
        self.assertEqual(len(body["permission_overwrites"]), 2)  # everyone + 참여자(중복 제거)
        self.assertEqual(self.fake.requests[0]["headers"]["X-Audit-Log-Reason"], "%EC%83%9D%EC%84%B1")
        self.assertTrue(client.delete_channel(CHANNEL))
        self.assertEqual(self.fake.requests[1]["method"], "DELETE")
        with self.assertRaises(ValueError):
            client.create_guild_channel(GUILD, name="x" * 101)

    def test_permissions_read_write(self):
        self.fake.queue("GET", f"/channels/{CHANNEL}", {"body": {"permission_overwrites": [
            {"id": str(GUILD), "type": 0, "allow": "1024", "deny": "2048"},
            {"id": str(USER), "type": 1, "allow": "68608", "deny": "0"}]}})
        client = self.make()
        self.assertEqual(client.get_member_overwrite(CHANNEL, USER)["allow"], "68608")
        self.assertIsNone(client.get_member_overwrite(CHANNEL, 999))
        client.set_member_permissions(CHANNEL, USER, allow=permissions.PARTICIPANT_ALLOW, deny=0)
        put = self.fake.requests[-1]
        self.assertEqual((put["method"], put["path"]), ("PUT", f"/channels/{CHANNEL}/permissions/{USER}"))
        self.assertEqual(put["body"], {"type": 1, "allow": "68608", "deny": "0"})  # 비트필드는 문자열
        self.fake.queue("DELETE", f"/channels/{CHANNEL}/permissions/{USER}", {"status": 404, "body": {"code": 10003}})
        self.assertFalse(client.clear_member_permissions(CHANNEL, USER))

    def test_recent_messages_query(self):
        self.fake.queue("GET", f"/channels/{CHANNEL}/messages", {"body": []})
        self.make().get_recent_messages(CHANNEL, 50, before=5)
        self.assertEqual(self.fake.requests[0]["query"], "limit=50&before=5")
        with self.assertRaises(ValueError):
            self.make().get_recent_messages(CHANNEL, 101)


class ErrorMapping(RestTestCase):
    def test_status_mapping_and_no_retry(self):
        cases = [(401, DiscordAuthError), (403, DiscordForbidden), (404, DiscordNotFound), (400, DiscordRequestError)]
        for status, expected in cases:
            self.fake.requests.clear()
            self.fake.queue("GET", f"/channels/{CHANNEL}", {"status": status, "body": {"code": 50001, "message": "m"}})
            with self.assertRaises(expected) as ctx:
                self.make().get_channel(CHANNEL)
            self.assertEqual(ctx.exception.status, status)
            self.assertFalse(ctx.exception.retryable)
            self.assertFalse(ctx.exception.outcome_unknown)
            self.assertEqual(len(self.fake.requests), 1, "4xx는 재시도하지 않는다")
        self.assertEqual(self.sleeps, [])

    def test_dm_blocked_is_distinguishable(self):
        self.fake.queue("POST", "/users/@me/channels", {"body": {"id": "5"}})
        self.fake.queue("POST", "/channels/5/messages", {"status": 403, "body": {"code": 50007, "message": "x"}})
        with self.assertRaises(DiscordForbidden) as ctx:
            self.make().send_dm(USER, content="x")
        self.assertTrue(ctx.exception.is_dm_blocked)

    def test_non_json_error_body(self):
        self.fake.queue("GET", f"/channels/{CHANNEL}", {"status": 403, "body": b"<html>blocked</html>"})
        with self.assertRaises(DiscordForbidden):
            self.make().get_channel(CHANNEL)


class RateLimit(RestTestCase):
    def test_get_retries_after_retry_after(self):
        path = f"/channels/{CHANNEL}"
        self.fake.queue("GET", path, {"status": 429, "body": {"retry_after": 1.5, "global": False}},
                        {"status": 200, "body": {"id": "ok"}})
        self.assertEqual(self.make().get_channel(CHANNEL)["id"], "ok")
        self.assertEqual(self.sleeps, [1.5])

    def test_header_used_when_body_is_not_json(self):
        path = f"/channels/{CHANNEL}"
        self.fake.queue("GET", path, {"status": 429, "body": b"slow down", "headers": {"Retry-After": "2"}},
                        {"status": 200, "body": {}})
        self.make().get_channel(CHANNEL)
        self.assertEqual(self.sleeps, [2.0])

    def test_post_retried_on_429_but_executes_once(self):
        """429는 실행되지 않은 요청이므로 메시지도 다시 보낸다. 서버에서 실제 생성된 것은 한 건이다."""
        path = f"/channels/{CHANNEL}/messages"
        self.fake.queue("POST", path, {"status": 429, "body": {"retry_after": 0.2}}, {"status": 200, "body": {"id": "1"}})
        self.make().send_message(CHANNEL, content="x")
        self.assertEqual(self.fake.count("POST", path), 2)
        self.assertEqual(self.fake.executed.count(("POST", path)), 1)
        self.assertEqual(self.sleeps, [0.2])

    def test_exhausted_and_too_long(self):
        path = f"/channels/{CHANNEL}"
        self.fake.queue("GET", path, *[{"status": 429, "body": {"retry_after": 1}}] * 5)
        with self.assertRaises(DiscordRateLimited) as ctx:
            self.make(max_retries=2).get_channel(CHANNEL)
        self.assertEqual((len(self.sleeps), ctx.exception.retry_after, ctx.exception.retryable), (2, 1.0, True))
        self.assertFalse(ctx.exception.outcome_unknown)  # 실행되지 않았다
        self.sleeps.clear()
        self.fake.queues.clear()  # 앞 시나리오에서 쓰지 않은 응답이 남아 있으면 다음 케이스를 오염시킨다
        self.fake.queue("GET", path, {"status": 429, "body": {"retry_after": 120, "global": True}})
        with self.assertRaises(DiscordRateLimited):
            self.make(max_retry_after=30).get_channel(CHANNEL)
        self.assertEqual(self.sleeps, [], "허용 대기 시간을 넘으면 기다리지 않는다 (Lambda 제한시간 보호)")

    def test_time_budget_stops_retrying(self):
        now = [0.0]
        self.fake.queue("GET", f"/channels/{CHANNEL}", *[{"status": 429, "body": {"retry_after": 10}}] * 3)
        client = self.make(time_budget=15, clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))
        with self.assertRaises(DiscordRateLimited):
            client.get_channel(CHANNEL)
        self.assertEqual(self.fake.count("GET", f"/channels/{CHANNEL}"), 2)  # 두 번째 대기는 예산 초과라 중단


class ServerErrorsAndTimeouts(RestTestCase):
    def test_idempotent_5xx_retried_with_backoff(self):
        path = f"/channels/{CHANNEL}/permissions/{USER}"
        self.fake.queue("PUT", path, {"status": 503, "body": {}}, {"status": 502, "body": {}}, {"status": 204, "body": b""})
        self.make().set_member_permissions(CHANNEL, USER, allow=1, deny=0)
        self.assertEqual(self.sleeps, [0.5, 1.0])

    def test_idempotent_5xx_exhausted(self):
        self.fake.queue("GET", f"/channels/{CHANNEL}", *[{"status": 500, "body": {}}] * 5)
        with self.assertRaises(DiscordServerError) as ctx:
            self.make(max_retries=2).get_channel(CHANNEL)
        self.assertEqual(len(self.fake.requests), 3)
        self.assertTrue(ctx.exception.retryable)
        self.assertFalse(ctx.exception.outcome_unknown)  # 읽기는 부작용이 없다

    def test_message_5xx_is_not_retried_and_flags_unknown(self):
        """메시지는 서버에서 만들어진 뒤 500이 올 수 있다. 자동 재시도하면 중복 전송이 된다."""
        path = f"/channels/{CHANNEL}/messages"
        self.fake.queue("POST", path, {"status": 500, "body": {}, "executes": True}, {"status": 200, "body": {"id": "2"}})
        with self.assertRaises(DiscordServerError) as ctx:
            self.make().send_message(CHANNEL, content="x")
        self.assertTrue(ctx.exception.outcome_unknown)
        self.assertEqual(self.fake.count("POST", path), 1, "재시도하지 않았다")
        self.assertEqual(self.fake.executed.count(("POST", path)), 1, "서버에는 정확히 한 건만 있다")
        self.assertEqual(self.sleeps, [])

    def test_channel_create_5xx_is_not_retried(self):
        path = f"/guilds/{GUILD}/channels"
        self.fake.queue("POST", path, {"status": 502, "body": {}, "executes": True})
        with self.assertRaises(DiscordServerError) as ctx:
            self.make().create_guild_channel(GUILD, name="c")
        self.assertTrue(ctx.exception.outcome_unknown)
        self.assertEqual(self.fake.count("POST", path), 1)

    def test_timeout_get_retried_post_not(self):
        path = f"/channels/{CHANNEL}"
        self.fake.queue("GET", path, {"body": {}, "delay": 0.6}, {"body": {"id": "ok"}})
        self.assertEqual(self.make(timeout=0.2).get_channel(CHANNEL)["id"], "ok")
        msg = f"/channels/{CHANNEL}/messages"
        self.fake.queue("POST", msg, {"body": {"id": "late"}, "delay": 0.6, "executes": True})
        with self.assertRaises(DiscordTimeoutError) as ctx:
            self.make(timeout=0.2).send_message(CHANNEL, content="x")
        self.assertTrue(ctx.exception.outcome_unknown)
        self.assertEqual(self.fake.count("POST", msg), 1)

    def test_connection_failure_before_send_is_safe_to_retry_even_for_post(self):
        """요청이 전달되지 않은 것이 확실한 연결 실패(maybe_sent=False)는 POST도 재시도한다 (중복 위험 없음)."""
        from discord_rest.transport import TransportError
        calls = []

        def refused(method, url, headers, body, timeout):
            calls.append(method)
            raise TransportError("connection error: ConnectionRefusedError", maybe_sent=False)

        client = DiscordRestClient(TOKEN, base_url=self.fake.url, transport=refused, sleep=self.sleeps.append,
                                   max_retries=2)
        with self.assertRaises(DiscordNetworkError) as ctx:
            client.send_message(CHANNEL, content="x")
        self.assertFalse(ctx.exception.outcome_unknown)
        self.assertEqual((len(calls), len(self.sleeps)), (3, 2))
        # 중간에 끊긴 연결(maybe_sent=True)은 POST를 재시도하지 않는다.
        calls.clear()

        def dropped(method, url, headers, body, timeout):
            calls.append(method)
            raise TransportError("connection error: RemoteDisconnected", maybe_sent=True)

        client = DiscordRestClient(TOKEN, base_url=self.fake.url, transport=dropped, sleep=self.sleeps.append)
        with self.assertRaises(DiscordNetworkError) as ctx:
            client.send_message(CHANNEL, content="x")
        self.assertTrue(ctx.exception.outcome_unknown)
        self.assertEqual(len(calls), 1)

    def test_urllib_transport_classifies_refused_vs_timeout(self):
        import urllib.error
        from unittest import mock
        from discord_rest.transport import TransportError, TransportTimeout, urllib_transport
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError(ConnectionRefusedError())):
            with self.assertRaises(TransportError) as ctx:
                urllib_transport("GET", "http://127.0.0.1:1/x", {}, None, 1)
            self.assertFalse(ctx.exception.maybe_sent)
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError(TimeoutError())):
            with self.assertRaises(TransportTimeout):
                urllib_transport("GET", "http://127.0.0.1:1/x", {}, None, 1)
        with mock.patch("urllib.request.urlopen", side_effect=ConnectionResetError()):
            with self.assertRaises(TransportError) as ctx:
                urllib_transport("GET", "http://127.0.0.1:1/x", {}, None, 1)
            self.assertTrue(ctx.exception.maybe_sent)

    def test_bad_2xx_body(self):
        self.fake.queue("GET", f"/channels/{CHANNEL}", {"body": b"not json"})
        from discord_rest import DiscordResponseError
        with self.assertRaises(DiscordResponseError):
            self.make().get_channel(CHANNEL)


class GatewayAndSecrets(RestTestCase):
    CORE = ("client", "errors", "transport", "permissions", "inactivity", "__init__")

    def test_core_modules_import_no_gateway_config_or_db(self):
        banned = {"discord", "config", "services", "repositories", "handlers", "bot", "psycopg", "dotenv"}
        for name in self.CORE:
            tree = ast.parse((ROOT / "discord_rest" / f"{name}.py").read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules = [node.module]
                for module in modules:
                    self.assertNotIn(module.split(".")[0], banned, f"{name}.py가 {module}을 import")

    def test_runtime_import_loads_no_discord_py_or_config(self):
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import discord_rest; "
                "bad=[m for m in ('discord','config','psycopg','aiohttp') if m in sys.modules]; "
                "print(','.join(bad)); sys.exit(1 if bad else 0)")
        done = subprocess.run([sys.executable, "-I", "-c", code, str(ROOT)], capture_output=True, text=True,
                              env={**os.environ, "DISCORD_BOT_TOKEN": "", "DISCORD_GUILD_ID": ""})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_works_without_cache_one_guild_object_never_needed(self):
        """채널은 매번 REST로 조회한다: 같은 채널을 두 번 읽으면 서버에 요청이 두 번 간다 (캐시 없음)."""
        self.fake.queue("GET", f"/channels/{CHANNEL}", {"body": {"id": "1"}}, {"body": {"id": "2"}})
        client = self.make()
        self.assertEqual((client.get_channel(CHANNEL)["id"], client.get_channel(CHANNEL)["id"]), ("1", "2"))

    def test_token_never_logged_or_in_errors(self):
        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(self.format(record) + "".join(map(str, record.args or ())))

        handler, log = Capture(), logging.getLogger("playmate.discord_rest")
        log.addHandler(handler)
        log.setLevel(logging.DEBUG)
        self.addCleanup(log.removeHandler, handler)
        texts = []
        path = f"/channels/{CHANNEL}"
        scenarios = [
            ("GET", path, [{"status": 401, "body": {"message": "401: Unauthorized"}}]),
            ("GET", path, [{"status": 403, "body": {"code": 50001, "message": "Missing Access"}}]),
            ("GET", path, [{"status": 429, "body": {"retry_after": 0.1}}, {"status": 500, "body": {}}] * 4),
            ("POST", path + "/messages", [{"status": 500, "body": {}}]),
        ]
        for method, p, specs in scenarios:
            self.fake.queue(method, p, *specs)
        client = self.make(max_retries=1)
        for call in (lambda: client.get_channel(CHANNEL), lambda: client.get_channel(CHANNEL),
                     lambda: client.get_channel(CHANNEL), lambda: client.send_message(CHANNEL, content="x")):
            try:
                call()
            except Exception as error:  # noqa: BLE001
                texts += [str(error), repr(error)]
        texts += [repr(client), str(client)]
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            dead = probe.getsockname()[1]
        try:
            DiscordRestClient(TOKEN, base_url=f"http://127.0.0.1:{dead}/api/v10", sleep=lambda s: None,
                              max_retries=1).get_channel(CHANNEL)
        except Exception as error:  # noqa: BLE001
            texts += [str(error), repr(error)]
        joined = "\n".join(records + texts)
        self.assertTrue(records, "로그 자체는 남아야 한다")
        self.assertNotIn(TOKEN, joined)
        self.assertNotIn("SECRET-TOKEN", joined)
        self.assertNotIn(str(CHANNEL), joined, "Discord ID는 마스킹되어야 한다")
        with self.assertRaises(ValueError) as ctx:
            DiscordRestClient("bad token\n")
        self.assertNotIn("bad token", str(ctx.exception))

    def test_base_url_must_be_https_or_loopback(self):
        for url in ("http://discord.com/api/v10", "ftp://x"):
            with self.assertRaises(ValueError):
                DiscordRestClient(TOKEN, base_url=url)
        DiscordRestClient(TOKEN)  # 기본값(https)


class ReuseOfExistingCode(unittest.TestCase):
    """기존 Gateway Bot 모듈의 순수 로직을 그대로 호출한다 (기존 파일은 수정하지 않았다)."""

    @classmethod
    def setUpClass(cls):
        from discord_rest import reuse
        cls.reuse = reuse

    def test_dm_plan_uses_existing_text_and_links(self):
        from services.notification_service import build_dm_message
        base = "https://playmate.example.test"
        n = {"notification_id": 1, "notification_type": "REPLY", "actor_member_id": 1, "receiver_member_id": 2,
             "receiver_discord_id": "444444444444444444", "receiver_dm_opt_in": None, "post_title": "제목",
             "target_missing": False, "post_id": 7, "post_type": "BOARD", "post_board_id": 3, "recruit_id": None,
             "career_category": None}
        plan = self.reuse.plan_dm(n, base)
        self.assertIsNone(plan.skip_reason)
        self.assertEqual(plan.discord_id, 444444444444444444)
        self.assertEqual(plan.text, build_dm_message(n, f"{base}/board/3/posts/7"))
        self.assertIn("/board/3/posts/7", plan.text)
        self.assertEqual(self.reuse.plan_dm({**n, "receiver_dm_opt_in": False}, base).skip_reason, "DM 알림 꺼짐")
        self.assertEqual(self.reuse.plan_dm({**n, "actor_member_id": 2}, base).skip_reason, "본인 알림")
        self.assertIsNone(self.reuse.plan_dm({**n, "post_type": "CAREER"}, base).text.count("http") or None)  # 근거 불일치 -> 링크 없음

    def test_hot_and_career_messages_match_existing_embeds(self):
        from services.career_notice_service import build_notice_embed
        from services.hot_content_service import BOARD, build_hot_embed
        content = {"post_id": 1, "board_id": 2, "board_name": "자유", "title": "T", "body": "내용", "comment_count": 3}
        self.assertEqual(self.reuse.hot_message_payload(BOARD, content, "https://x.test/a")["embeds"][0],
                         build_hot_embed(BOARD, content, "https://x.test/a").to_dict())
        post = {"post_id": 5, "category_code": "reviews", "title": "후기"}
        payload = self.reuse.career_notice_payload(post, "https://x.test/career/reviews/5")
        self.assertEqual(payload["embeds"][0], build_notice_embed(post, "https://x.test/career/reviews/5").to_dict())
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        json.dumps(payload)  # REST 본문으로 직렬화 가능

    def test_permission_bits_equal_existing_constants(self):
        import discord
        from services.meeting_space import PARTICIPANT_PERMISSIONS
        allow, deny = discord.PermissionOverwrite(**PARTICIPANT_PERMISSIONS).pair()
        self.assertEqual((allow.value, deny.value), (permissions.PARTICIPANT_ALLOW, 0))
        for visibility, view, read, send in (("PUBLIC", True, True, False), ("PRIVATE", False, False, False)):
            pair = discord.PermissionOverwrite(view_channel=view, read_message_history=read, send_messages=send).pair()
            entry = permissions.everyone_overwrite(GUILD, visibility)
            self.assertEqual((int(entry["allow"]), int(entry["deny"])), (pair[0].value, pair[1].value), visibility)

    def test_joined_and_revoked_judgement_from_rest_json(self):
        channel = {"permission_overwrites": [
            {"id": str(GUILD), "type": 0, "allow": "1024", "deny": "2048"},
            permissions.participant_overwrite(USER),
            {"id": "555", "type": 1, "allow": "1024", "deny": "2048"}]}
        self.assertTrue(self.reuse.joined_ok(channel, USER))
        self.assertFalse(self.reuse.joined_ok(channel, 555))
        self.assertFalse(self.reuse.joined_ok(channel, 999))  # overwrite 없음
        self.assertFalse(self.reuse.revoked_ok(channel, USER))  # 아직 쓰기 가능
        self.assertTrue(self.reuse.revoked_ok(channel, 555))
        self.assertTrue(self.reuse.revoked_ok(channel, 999))  # 개인 overwrite 없음 = 회수됨
        read, deny = permissions.revoked_permissions("PUBLIC")
        after = {"permission_overwrites": [permissions.overwrite(USER, 1, read, deny)]}
        self.assertTrue(self.reuse.revoked_ok(after, USER, "PUBLIC"))
        self.assertFalse(self.reuse.revoked_ok({"permission_overwrites": [permissions.overwrite(USER, 1, 1 << 10, 0)]},
                                               USER, "PRIVATE"))
        self.assertIsNone(permissions.revoked_permissions("PRIVATE"))
        # 역할 overwrite를 사용자로 오인하지 않는다 (ID가 같아도)
        role_only = {"permission_overwrites": [permissions.overwrite(USER, 0, permissions.PARTICIPANT_ALLOW, 0)]}
        self.assertFalse(self.reuse.joined_ok(role_only, USER))

    def test_inactivity_matches_existing_lifecycle(self):
        """기존 lifecycle._check_meeting이 경고를 보내는 경우와 REST 판정(WARN)이 같다."""
        from repositories.meeting_repository import InMemoryMeetingRepository
        from services import lifecycle
        import config
        now = datetime(2026, 11, 21, 12, 0, tzinfo=KST)
        days = timedelta(days=config.INACTIVITY_DAYS)

        def meeting(**kw):
            base = {"recruit_id": 1, "channel_id": 9, "last_activity_at": now - days, "inactivity_warned_at": None,
                    "scheduled_delete_at": None, "discord_deleted_at": None}
            return {**base, **kw}

        scenarios = {
            "exactly_7d": meeting(), "just_under": meeting(last_activity_at=now - days + timedelta(seconds=1)),
            "10d": meeting(last_activity_at=now - timedelta(days=10)), "no_activity": meeting(last_activity_at=None),
            "already_warned": meeting(inactivity_warned_at=now - timedelta(hours=1)),
            "deleted": meeting(discord_deleted_at=now), "scheduled_future": meeting(
                inactivity_warned_at=now - timedelta(hours=1), scheduled_delete_at=now + timedelta(hours=5)),
        }
        for name, state in scenarios.items():
            channel = SimpleNamespace(send=AsyncMock())
            guild = SimpleNamespace(get_channel=lambda cid, c=channel: c, fetch_channel=AsyncMock())
            repo = InMemoryMeetingRepository({9: dict(state)})
            asyncio.run(lifecycle._check_meeting(guild, repo, 9, dict(state), now))
            warned_by_existing = channel.send.await_count == 1
            action, scheduled = self.reuse.decide_inactivity(state, now)
            self.assertEqual(action == inactivity.WARN, warned_by_existing, name)
            if warned_by_existing:
                self.assertEqual(scheduled, repo._meetings[9]["scheduled_delete_at"], name)

    def test_inactivity_other_actions(self):
        now = datetime(2026, 11, 21, tzinfo=KST)
        rule = dict(inactivity_days=7, grace_hours=24)
        due = {"last_activity_at": now, "scheduled_delete_at": now - timedelta(minutes=1), "inactivity_warned_at": now}
        self.assertEqual(inactivity.decide_action(due, now, **rule)[0], inactivity.DELETE_DUE)
        wait = {**due, "scheduled_delete_at": now + timedelta(minutes=1)}
        self.assertEqual(inactivity.decide_action(wait, now, **rule)[0], inactivity.WAIT_DELETE)

    def test_latest_user_message_from_rest_messages(self):
        since = datetime(2026, 11, 14, 0, 0, tzinfo=timezone.utc)
        messages = [  # 최신순
            {"timestamp": "2026-11-20T10:00:00.000000+00:00", "author": {"id": "1", "bot": True}},
            {"timestamp": "2026-11-19T09:30:00.123000+00:00", "author": {"id": "2"}},
            {"timestamp": "2026-11-10T09:00:00+00:00", "author": {"id": "3"}},
        ]
        found = inactivity.latest_user_message_at(messages, since, KST)
        self.assertEqual(found, datetime(2026, 11, 19, 18, 30, 0, 123000, tzinfo=KST))
        self.assertIsNone(inactivity.latest_user_message_at(messages[:1], since))  # 봇만 있음
        self.assertIsNone(inactivity.latest_user_message_at(messages[2:], since))  # since 이전
        self.assertIsNone(inactivity.latest_user_message_at([], since))

    def test_find_and_safe_delete_meeting_channel(self):
        from services.meeting_space import channel_topic
        r = self.reuse
        self.assertTrue(channel_topic(7, "PUBLIC").startswith(r.topic_marker(7)))
        self.assertFalse(channel_topic(70, "PUBLIC").startswith(r.topic_marker(7)))  # #7이 #70과 섞이지 않는다
        channels = [{"id": "1", "type": 0, "topic": channel_topic(7, "PRIVATE")},
                    {"id": "2", "type": 0, "topic": channel_topic(70, "PUBLIC")}, {"id": "3", "type": 2, "topic": channel_topic(7)}]
        self.assertEqual([c["id"] for c in r.find_meeting_channels(channels, 7)], ["1"])

        calls = []

        class Stub:
            def __init__(self, channel):
                self.channel = channel

            def get_channel(self, channel_id):
                if isinstance(self.channel, Exception):
                    raise self.channel
                return self.channel

            def delete_channel(self, channel_id, **kw):
                calls.append(channel_id)
                return True

        ok = {"type": 0, "topic": channel_topic(7)}
        self.assertTrue(r.safe_delete_meeting_channel(Stub(ok), 5, 7))
        self.assertEqual(calls, [5])
        for blocked, label in ((Stub(ok), "보호"), (Stub({"type": 0, "topic": "다른 채널"}), "표지"),
                               (Stub({"type": 4, "topic": channel_topic(7)}), "카테고리"),
                               (Stub({"type": 0, "topic": channel_topic(8)}), "다른 모임")):
            protected = {5} if label == "보호" else frozenset()
            self.assertFalse(r.safe_delete_meeting_channel(blocked, 5, 7, protected), label)
        self.assertEqual(calls, [5], "안전 확인에 걸린 채널은 지우지 않았다")
        self.assertTrue(r.safe_delete_meeting_channel(Stub(DiscordNotFound("gone")), 5, 7))  # 이미 없음
        self.assertFalse(r.safe_delete_meeting_channel(Stub(DiscordServerError("x")), 5, 7))  # 불명확 -> 지우지 않음
        with self.assertRaises(DiscordAuthError):
            r.safe_delete_meeting_channel(Stub(DiscordAuthError("x")), 5, 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
