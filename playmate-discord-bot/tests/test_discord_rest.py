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
# 환경변수는 모듈 전체에 쓰지 않는다. 기존 모듈(config)을 import하는 ReuseOfExistingCode만 setUpClass에서 임시로 넣고
# tearDownClass에서 되돌린다 (다른 테스트 파일의 환경에 영향을 주지 않는다).

from unittest import mock  # noqa: E402

from discord_rest import (  # noqa: E402
    DELETE_ALREADY_GONE, DELETE_DELETED, DELETE_GONE_AFTER_RETRY,
    DiscordAuthError, DiscordForbidden, DiscordNetworkError, DiscordNotFound, DiscordRateLimited,
    DiscordRedirectError, DiscordRequestError, DiscordRestClient, DiscordServerError, DiscordTimeoutError,
)
from discord_rest import inactivity, permissions  # noqa: E402
from discord_rest.transport import make_urllib_transport  # noqa: E402

TOKEN = "SECRET-TOKEN-do-not-log.abc123"
GUILD, CHANNEL, USER = 111111111111111111, 222222222222222222, 333333333333333333
KST = timezone(timedelta(hours=9))

# -- 외부 접속 차단 ---------------------------------------------------------------------
# 이 파일의 모든 테스트는 loopback(127.0.0.1)에만 접속해야 한다. 다른 호스트(discord.com 등)로 이름 조회나 연결을 시도하면
# 즉시 AssertionError로 막고, 시도 기록을 남겨 모듈이 끝날 때 한 번 더 확인한다.
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_BLOCKED: list[str] = []
_real_getaddrinfo, _real_connect = socket.getaddrinfo, socket.socket.connect
_patches: list = []


def _guard_getaddrinfo(host, *args, **kwargs):
    if str(host).strip("[]") not in _LOOPBACK:
        _BLOCKED.append(str(host))
        raise AssertionError(f"외부 호스트 이름 조회 차단: {host}")
    return _real_getaddrinfo(host, *args, **kwargs)


def _guard_connect(self, address):
    host = address[0] if isinstance(address, tuple) else address
    if str(host).strip("[]") not in _LOOPBACK:
        _BLOCKED.append(str(host))
        raise AssertionError(f"외부 호스트 연결 차단: {host}")
    return _real_connect(self, address)


def setUpModule():
    for patcher in (mock.patch("socket.getaddrinfo", _guard_getaddrinfo),
                    mock.patch("socket.socket.connect", _guard_connect)):
        patcher.start()
        _patches.append(patcher)


def tearDownModule():
    while _patches:
        _patches.pop().stop()
    assert not _BLOCKED, f"테스트가 외부 호스트에 접속을 시도했다: {_BLOCKED}"


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
        self.assertEqual(client.delete_channel(CHANNEL), DELETE_DELETED)
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
        opener_open = "urllib.request.OpenerDirector.open"  # 전송 계층은 리다이렉트를 막은 전용 opener를 쓴다
        with mock.patch(opener_open, side_effect=urllib.error.URLError(ConnectionRefusedError())):
            with self.assertRaises(TransportError) as ctx:
                urllib_transport("GET", "http://127.0.0.1:1/x", {}, None, 1)
            self.assertFalse(ctx.exception.maybe_sent)
        with mock.patch(opener_open, side_effect=urllib.error.URLError(TimeoutError())):
            with self.assertRaises(TransportTimeout):
                urllib_transport("GET", "http://127.0.0.1:1/x", {}, None, 1)
        with mock.patch(opener_open, side_effect=ConnectionResetError()):
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
        # 기존 config는 import 시점에 토큰/길드 환경변수를 요구한다. 이 클래스 동안만 가짜 값을 넣고 끝나면 되돌린다
        # (config를 import하며 .env에서 읽은 값도 함께 되돌아간다). 웹 주소는 비워 로컬 설정이 섞이지 않게 한다.
        cls._env = mock.patch.dict(os.environ, {"DISCORD_BOT_TOKEN": "verification-only", "DISCORD_GUILD_ID": "1",
                                                "PLAYMATE_WEB_BASE_URL": ""})
        cls._env.start()
        from discord_rest import reuse
        cls.reuse = reuse

    @classmethod
    def tearDownClass(cls):
        cls._env.stop()

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

    def test_find_meeting_channels_and_topic_marker(self):
        from services.meeting_space import channel_topic
        r = self.reuse
        self.assertTrue(channel_topic(7, "PUBLIC").startswith(r.topic_marker(7)))
        self.assertFalse(channel_topic(70, "PUBLIC").startswith(r.topic_marker(7)))  # #7이 #70과 섞이지 않는다
        channels = [{"id": "1", "type": 0, "topic": channel_topic(7, "PRIVATE")},
                    {"id": "2", "type": 0, "topic": channel_topic(70, "PUBLIC")}, {"id": "3", "type": 2, "topic": channel_topic(7)}]
        self.assertEqual([c["id"] for c in r.find_meeting_channels(channels, 7)], ["1"])

    def _safe_delete_harness(self):
        """REST 클라이언트 대역. 조회/삭제 횟수를 센다."""
        from services.meeting_space import channel_topic
        guild = 777000000000000001
        state = {"gets": 0, "deleted": []}

        class Stub:
            def __init__(self, channel, delete_error=None):
                self.channel, self.delete_error = channel, delete_error

            def get_channel(self, channel_id):
                state["gets"] += 1
                if isinstance(self.channel, Exception):
                    raise self.channel
                return self.channel

            def delete_channel(self, channel_id, **kw):
                if self.delete_error is not None:
                    raise self.delete_error
                state["deleted"].append(channel_id)
                return DELETE_DELETED

        def chan(**kw):
            base = {"id": "5", "guild_id": str(guild), "type": 0, "topic": channel_topic(7)}
            base.update(kw)
            return {k: v for k, v in base.items() if v is not _DROP}

        def run(channel, delete_error=None, **kw):
            args = dict(guild_id=guild, protected_ids=frozenset(), activity=inactivity.NO_ACTIVITY)
            args.update(kw)
            return self.reuse.safe_delete_meeting_channel(Stub(channel, delete_error), 5, 7, **args)

        return state, chan, run, guild

    def test_safe_delete_keeps_every_existing_guard(self):
        """기존 delete_meeting_channel의 보호 조건(보호 목록, 텍스트 채널, 주제 표지, 직전 중단)이 그대로 유지된다."""
        state, chan, run, _ = self._safe_delete_harness()
        self.assertTrue(run(chan()))
        self.assertEqual(state["deleted"], [5])
        refusals = {
            "보호 목록(정수)": lambda: run(chan(), protected_ids={5}),
            "보호 목록(문자열 ID)": lambda: run(chan(), protected_ids=["5", "6"]),
            "텍스트 채널 아님": lambda: run(chan(type=4)),
            "음성 채널": lambda: run(chan(type=2)),
            "주제 표지 다름": lambda: run(chan(topic="다른 채널")),
            "주제 없음": lambda: run(chan(topic=None)),
            "다른 모임 표지": lambda: run(chan(topic="PlayMate 모임 #8 (PUBLIC)")),
            "#7 vs #70": lambda: run(chan(topic="PlayMate 모임 #70 (PUBLIC)")),
            "삭제 직전 중단(should_abort)": lambda: run(chan(), should_abort=lambda: True),
        }
        for label, call in refusals.items():
            with self.subTest(label):
                self.assertFalse(call(), label)
        self.assertEqual(state["deleted"], [5], "거부된 경우에는 삭제하지 않았다")

    def test_safe_delete_new_guards_guild_response_id_and_activity(self):
        """B8 + B5: 서버 ID, 응답 채널 ID, 활동 확인 결과를 추가로 확인한다."""
        state, chan, run, guild = self._safe_delete_harness()
        refusals = {
            "다른 서버": lambda: run(chan(guild_id="999")),
            "guild_id 없음(DM 등)": lambda: run(chan(guild_id=_DROP)),
            "응답 채널 ID 불일치": lambda: run(chan(id="6")),
            "응답 채널 ID 없음": lambda: run(chan(id=_DROP)),
        }
        for label, call in refusals.items():
            with self.subTest(label):
                self.assertFalse(call(), label)
        self.assertEqual(state["deleted"], [])
        # 활동 확인 결과가 NO_ACTIVITY(또는 명시적 NOT_APPLICABLE)가 아니면 REST 호출조차 하지 않는다.
        gets_before = state["gets"]
        for bad in (inactivity.ACTIVE, inactivity.UNKNOWN, None, "", "weird", inactivity.DELETE_DUE):
            with self.subTest(activity=bad):
                self.assertFalse(run(chan(), activity=bad))
        self.assertEqual((state["gets"], state["deleted"]), (gets_before, []), "활동이 확인되지 않으면 조회도 삭제도 없다")
        self.assertTrue(run(chan(), activity=inactivity.ACTIVITY_NOT_APPLICABLE))  # 방금 만든 채널 롤백 등 명시한 경우
        self.assertEqual(state["deleted"], [5])
        self.assertEqual(guild, 777000000000000001)

    def test_safe_delete_requires_explicit_safety_arguments(self):
        state, chan, run, guild = self._safe_delete_harness()
        r = self.reuse

        class Never:
            def get_channel(self, *a):
                raise AssertionError("호출되면 안 된다")

        with self.assertRaises(TypeError):
            r.safe_delete_meeting_channel(Never(), 5, 7)  # guild_id, protected_ids, activity 모두 누락
        with self.assertRaises(TypeError):  # protected_ids 누락 (기본값이 없어 깜빡할 수 없다)
            r.safe_delete_meeting_channel(Never(), 5, 7, guild_id=guild, activity=inactivity.NO_ACTIVITY)
        with self.assertRaises(TypeError):  # activity 누락
            r.safe_delete_meeting_channel(Never(), 5, 7, guild_id=guild, protected_ids=frozenset())
        for bad in (None, "5", b"5", ["abc"], [0], [-1], [True], 5):
            with self.subTest(protected_ids=bad), self.assertRaises(ValueError):
                r.safe_delete_meeting_channel(Never(), 5, 7, guild_id=guild, protected_ids=bad,
                                              activity=inactivity.NO_ACTIVITY)
        for bad in (0, -1, "x", None, True):
            with self.subTest(guild_id=bad), self.assertRaises(ValueError):
                r.safe_delete_meeting_channel(Never(), 5, 7, guild_id=bad, protected_ids=frozenset(),
                                              activity=inactivity.NO_ACTIVITY)

    def test_safe_delete_error_handling_does_not_confirm_unknown_outcomes(self):
        state, chan, run, _ = self._safe_delete_harness()
        self.assertTrue(run(DiscordNotFound("gone")))  # 이미 없음
        self.assertFalse(run(DiscordServerError("x")))  # 조회 불명확 -> 지우지 않음
        self.assertFalse(run(DiscordForbidden("x")))
        with self.assertRaises(DiscordAuthError):
            run(DiscordAuthError("x"))
        # 삭제 요청 자체가 불명확하게 끝나면 True(삭제 확정)로 보고하지 않는다
        self.assertFalse(run(chan(), delete_error=DiscordServerError("x")))
        self.assertFalse(run(chan(), delete_error=DiscordTimeoutError("x")))
        self.assertFalse(run(chan(), delete_error=DiscordForbidden("x")))
        with self.assertRaises(DiscordAuthError):
            run(chan(), delete_error=DiscordAuthError("x"))
        self.assertEqual(state["deleted"], [])

    def test_safe_delete_over_real_client_and_fake_server(self):
        """진짜 클라이언트 + 가짜 서버: 재시도 후 404는 '채널 없음'으로, 5xx 소진은 '불명확'으로 보고한다. 실제 Discord는 아님."""
        from services.meeting_space import channel_topic
        fake = FakeDiscord()
        self.addCleanup(fake.close)
        guild = 777000000000000001
        channel_json = {"id": str(CHANNEL), "guild_id": str(guild), "type": 0, "topic": channel_topic(7)}
        path = f"/channels/{CHANNEL}"

        def run(**kw):
            client = DiscordRestClient(TOKEN, base_url=fake.url, sleep=lambda s: None, timeout=2)
            args = dict(guild_id=guild, protected_ids=frozenset(), activity=inactivity.NO_ACTIVITY)
            args.update(kw)
            return self.reuse.safe_delete_meeting_channel(client, CHANNEL, 7, **args)

        def reset(*delete_specs):
            fake.requests.clear(); fake.queues.clear(); fake.executed.clear()
            fake.queue("GET", path, {"body": channel_json})
            fake.queue("DELETE", path, *delete_specs)

        reset({"status": 204, "body": b""})
        self.assertTrue(run())
        self.assertEqual(fake.count("DELETE", path), 1)
        reset({"status": 502, "body": {}, "executes": True}, {"status": 404, "body": {"code": 10003}})
        self.assertTrue(run(), "재시도 뒤 404: 채널이 없는 것은 확실하다")
        self.assertEqual(fake.count("DELETE", path), 2, "이미 지워졌으면 더 보내지 않는다")
        reset({"status": 502, "body": {}, "executes": True}, *[{"status": 502, "body": {}}] * 3)
        self.assertFalse(run(), "5xx 소진: 삭제 여부 불명확. True로 확정하지 않는다")
        self.assertEqual(fake.count("DELETE", path), 4)
        reset({"status": 403, "body": {"code": 50013}})
        self.assertFalse(run())
        self.assertEqual(fake.count("DELETE", path), 1, "403은 재시도하지 않는다")
        reset({"status": 204, "body": b""})
        fake.requests.clear()
        self.assertFalse(run(activity=inactivity.UNKNOWN))
        self.assertFalse(run(guild_id=guild + 1))
        self.assertEqual(fake.count("DELETE", path), 0, "활동 미확인/다른 서버는 삭제 요청을 보내지 않는다")

    def test_delete_due_matches_existing_lifecycle(self):
        """예약 시각이 지난 뒤(DELETE_DUE 이후)의 삭제/취소/보류 결과가 기존 lifecycle._check_meeting과 같다."""
        import discord
        from repositories.meeting_repository import InMemoryMeetingRepository
        from services import lifecycle
        from services.meeting_space import channel_topic

        now = datetime(2026, 11, 21, 12, 0, tzinfo=KST)
        warned = now - timedelta(hours=25)

        def meeting(**kw):
            base = {"recruit_id": 1, "channel_id": 9, "last_activity_at": now - timedelta(days=8),
                    "inactivity_warned_at": warned, "scheduled_delete_at": now - timedelta(minutes=1),
                    "discord_deleted_at": None}
            return {**base, **kw}

        def message(at, bot=False):
            return SimpleNamespace(created_at=at, author=SimpleNamespace(bot=bot))

        scenarios = {  # 이름: (모임 상태, 채널 최근 메시지(최신순) 또는 None=조회 실패, 채널의 last_message_id)
            "예약 지남 + 활동 없음(빈 채널)": (meeting(), [], None),
            "예약 지남 + 봇 메시지만": (meeting(), [message(now - timedelta(hours=2), bot=True)], 2),
            "예약 지남 + 경고 이후 사용자 메시지": (meeting(), [message(now - timedelta(hours=3))], 3),
            "예약 지남 + 경고 이전 사용자 메시지만": (meeting(), [message(warned - timedelta(hours=1))], 4),
            "예약 지남 + 경고 이후 활동이 DB에 기록됨": (meeting(last_activity_at=warned + timedelta(hours=1)), [], None),
            "예약 지남 + 최근 메시지 조회 실패": (meeting(), None, None),
            "예약 전": (meeting(scheduled_delete_at=now + timedelta(hours=1)), [], None),
            "경고 없이 예약만 있고 지남": (meeting(inactivity_warned_at=None), [], None),
        }

        class FakeChannel:
            def __init__(self, messages):
                self.type, self.topic, self.name = discord.ChannelType.text, channel_topic(1), "c"
                self.delete, self.send, self._messages = AsyncMock(), AsyncMock(), messages

            def history(self, limit):
                async def generator():
                    if self._messages is None:
                        raise RuntimeError("history unavailable")
                    for item in self._messages:
                        yield item
                return generator()

        for name, (state, messages, last_id) in scenarios.items():
            with self.subTest(name):
                channel = FakeChannel(messages)

                async def fetch(channel_id, c=channel):
                    raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "gone")

                guild = SimpleNamespace(get_channel=lambda channel_id, c=channel: c, fetch_channel=fetch)
                repo = InMemoryMeetingRepository({9: dict(state)})
                asyncio.run(lifecycle._check_meeting(guild, repo, 9, dict(state), now))
                stored = repo._meetings[9]
                existing = (channel.delete.await_count == 1,                       # 삭제 요청을 보냈는가
                            stored["scheduled_delete_at"] is None and state["scheduled_delete_at"] is not None
                            and stored.get("discord_deleted_at") is None)           # 예약이 취소되었는가

                action, _ = self.reuse.decide_inactivity(state, now)
                rest = None if messages is None else [
                    {"timestamp": m.created_at.astimezone(timezone.utc).isoformat(), "author": {"bot": m.author.bot}}
                    for m in messages]
                verdict = None
                if action == inactivity.DELETE_DUE:
                    verdict = inactivity.check_activity_for_deletion(
                        rest, state["inactivity_warned_at"], limit=50,  # DELETE_DUE이면 경고 시각이 있다
                        last_message_id=None if last_id is None else
                        ((int(now.timestamp() * 1000) - 1420070400000) << 22))
                ours = (action == inactivity.DELETE_DUE and verdict == inactivity.NO_ACTIVITY,
                        action == inactivity.CANCEL_SCHEDULE or verdict == inactivity.ACTIVE)
                self.assertEqual(ours, existing, f"{name}: 새 판정 {ours} vs 기존 {existing}")


_DROP = object()  # 테스트 헬퍼: 딕셔너리에서 키를 빼기 위한 표식


class RedirectSafety(RestTestCase):
    """B1: 리다이렉트를 따르지 않는다. 가짜 서버 두 대: self.fake(원래 서버)가 self.other(다른 출처)로 리다이렉트한다."""

    PATHS = {"GET": f"/channels/{CHANNEL}", "POST": f"/channels/{CHANNEL}/messages",
             "PUT": f"/channels/{CHANNEL}/permissions/{USER}", "DELETE": f"/channels/{CHANNEL}"}
    CALLS = {"GET": lambda c: c.get_channel(CHANNEL), "POST": lambda c: c.send_message(CHANNEL, content="hi"),
             "PUT": lambda c: c.set_member_permissions(CHANNEL, USER, allow=1, deny=0),
             "DELETE": lambda c: c.delete_channel(CHANNEL)}

    def setUp(self):
        super().setUp()
        self.other = FakeDiscord()  # 따라가면 200 {}으로 "성공"해 버리는 다른 출처
        self.addCleanup(self.other.close)

    def test_redirects_are_never_followed_for_any_method(self):
        for status in (301, 302, 303, 307, 308):
            for method, call in self.CALLS.items():
                with self.subTest(status=status, method=method):
                    self.fake.requests.clear(); self.other.requests.clear(); self.fake.queues.clear()
                    self.fake.queue(method, self.PATHS[method], {"status": status, "body": b"", "executes": False,
                                                                 "headers": {"Location": f"{self.other.url}/steal"}})
                    with self.assertRaises(DiscordRedirectError) as ctx:
                        call(self.make())
                    error = ctx.exception
                    self.assertEqual((error.status, error.retryable, error.outcome_unknown), (status, False, False))
                    self.assertIsInstance(error, DiscordRequestError)
                    self.assertEqual(len(self.fake.requests), 1, "리다이렉트는 재시도하지 않는다")
                    self.assertEqual(self.other.requests, [], "다른 출처로 요청(과 Authorization)이 가지 않았다")
                    self.assertEqual(self.fake.executed, [], "서버가 요청을 처리하지 않았다")
                    for leaked in ("steal", TOKEN, str(self.other.server.server_port)):
                        self.assertNotIn(leaked, str(error))

    def test_post_302_is_not_reported_as_success(self):
        """예전 동작: POST 302가 GET으로 바뀌어 다른 서버의 200을 '메시지 전송 성공'으로 반환했다."""
        self.fake.queue("POST", self.PATHS["POST"], {"status": 302, "body": b"", "executes": False,
                                                     "headers": {"Location": f"{self.other.url}/channels/{CHANNEL}/messages"}})
        self.other.queue("GET", f"/channels/{CHANNEL}/messages", {"body": {"id": "FAKE-SUCCESS"}})
        with self.assertRaises(DiscordRedirectError):
            self.make().send_message(CHANNEL, content="hi")
        self.assertEqual(self.other.requests, [])

    def test_authorization_header_only_goes_to_the_configured_origin(self):
        self.fake.queue("GET", self.PATHS["GET"], {"body": {"id": "1"}})
        self.make().get_channel(CHANNEL)
        self.assertEqual(self.fake.requests[0]["headers"]["Authorization"], f"Bot {TOKEN}")
        self.assertEqual(self.other.requests, [])


class ProxyEnvironment(RestTestCase):
    """B6: 프록시 환경변수가 loopback 테스트 요청과 토큰을 엉뚱한 곳으로 보내지 않는다."""

    def test_env_proxy_variables_are_ignored_by_default(self):
        dead = "http://127.0.0.1:9"  # 아무도 듣지 않는 가짜 프록시
        env = {name: dead for name in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY")}
        env.update(no_proxy="", NO_PROXY="")
        self.fake.queue("GET", f"/channels/{CHANNEL}", {"body": {"id": "ok"}})
        with mock.patch.dict(os.environ, env):
            self.assertEqual(self.make().get_channel(CHANNEL)["id"], "ok")
        self.assertEqual(self.fake.count("GET", f"/channels/{CHANNEL}"), 1)

    def test_env_proxy_is_used_only_when_explicitly_enabled(self):
        proxy = FakeDiscord()  # 프록시 역할의 가짜 서버
        self.addCleanup(proxy.close)
        address = proxy.url.rsplit("/api/v10", 1)[0]
        with mock.patch.dict(os.environ, {"http_proxy": address, "HTTP_PROXY": address, "no_proxy": "", "NO_PROXY": ""}):
            client = self.make(transport=make_urllib_transport(use_env_proxy=True))
            client.get_channel(CHANNEL)
        self.assertEqual(len(proxy.requests), 1, "명시적으로 켜면 환경변수 프록시를 쓴다")
        self.assertEqual(self.fake.requests, [])


class DeleteChannelSemantics(RestTestCase):
    """B2: DELETE 재시도 뒤의 404와 처음부터의 404를 구분하고, 불명확한 결과를 확정하지 않는다."""
    PATH = f"/channels/{CHANNEL}"

    def test_first_attempt_404(self):
        self.fake.queue("DELETE", self.PATH, {"status": 404, "body": {"code": 10003}})
        with self.assertRaises(DiscordNotFound) as ctx:
            self.make().delete_channel(CHANNEL)
        self.assertEqual((ctx.exception.attempts, ctx.exception.after_ambiguous), (1, False))
        self.fake.queue("DELETE", self.PATH, {"status": 404, "body": {"code": 10003}})
        self.assertEqual(self.make().delete_channel(CHANNEL, missing_ok=True), DELETE_ALREADY_GONE)

    def test_404_after_ambiguous_attempt_is_gone_after_retry_not_an_error(self):
        ambiguous = {"5xx(서버는 삭제함)": {"status": 502, "body": {}, "executes": True},
                     "타임아웃(서버는 삭제함)": {"body": {}, "delay": 0.6, "executes": True}}
        for label, first in ambiguous.items():
            for missing_ok in (False, True):
                with self.subTest(label, missing_ok=missing_ok):
                    self.fake.requests.clear(); self.fake.queues.clear()
                    self.fake.queue("DELETE", self.PATH, first, {"status": 404, "body": {"code": 10003}})
                    result = self.make(timeout=0.2).delete_channel(CHANNEL, missing_ok=missing_ok)
                    self.assertEqual(result, DELETE_GONE_AFTER_RETRY)
                    self.assertEqual(self.fake.count("DELETE", self.PATH), 2, "이미 지워진 채널에 세 번째 요청은 없다")

    def test_404_after_429_is_still_a_first_404(self):
        """429는 실행되지 않은 요청이라, 그 뒤의 404는 '처음부터 없었음'과 같다."""
        for missing_ok, expect in ((True, DELETE_ALREADY_GONE), (False, None)):
            with self.subTest(missing_ok=missing_ok):
                self.fake.requests.clear(); self.fake.queues.clear()
                self.fake.queue("DELETE", self.PATH, {"status": 429, "body": {"retry_after": 0.1}},
                                {"status": 404, "body": {"code": 10003}})
                if expect is None:
                    with self.assertRaises(DiscordNotFound) as ctx:
                        self.make().delete_channel(CHANNEL, missing_ok=missing_ok)
                    self.assertEqual((ctx.exception.attempts, ctx.exception.after_ambiguous), (2, False))
                else:
                    self.assertEqual(self.make().delete_channel(CHANNEL, missing_ok=missing_ok), expect)

    def test_success_sends_exactly_one_request(self):
        self.fake.queue("DELETE", self.PATH, {"status": 204, "body": b""})
        self.assertEqual(self.make().delete_channel(CHANNEL, reason="정리"), DELETE_DELETED)
        self.assertEqual(self.fake.count("DELETE", self.PATH), 1)

    def test_unknown_outcome_is_raised_not_confirmed(self):
        """5xx/타임아웃이 재시도 횟수만큼 이어지면 '삭제됨'도 '실패'도 확정하지 않고 예외로 알린다."""
        self.fake.queue("DELETE", self.PATH, {"status": 502, "body": {}, "executes": True}, *[{"status": 502, "body": {}}] * 3)
        with self.assertRaises(DiscordServerError):
            self.make().delete_channel(CHANNEL, missing_ok=True)
        self.assertEqual(self.fake.count("DELETE", self.PATH), 4)
        self.fake.queues.clear()
        self.fake.queue("DELETE", self.PATH, *[{"body": {}, "delay": 0.5}] * 4)
        with self.assertRaises(DiscordTimeoutError):
            self.make(timeout=0.1, max_retries=1).delete_channel(CHANNEL)

    def test_forbidden_is_not_retried(self):
        self.fake.queue("DELETE", self.PATH, {"status": 403, "body": {"code": 50013}})
        with self.assertRaises(DiscordForbidden):
            self.make().delete_channel(CHANNEL)
        self.assertEqual(self.fake.count("DELETE", self.PATH), 1)


class ConstructorValidation(unittest.TestCase):
    """B4: 입력 검증. 오류 메시지에 토큰 값이 나오지 않는다."""

    def test_bad_tokens_rejected_without_echoing_them(self):
        bad = ["", "   ", "abc def", "abc\n", "abc\r\nX-Evil: 1", "tok\x00en", "토큰abc", "tökén", "😀", "tab\tbed"]
        for token in bad:
            with self.subTest(token=repr(token)), self.assertRaises(ValueError) as ctx:
                DiscordRestClient(token)
            if token.strip():
                self.assertNotIn(token, str(ctx.exception))
        for token in (None, 123, b"abc", ["abc"]):
            with self.subTest(token=repr(token)), self.assertRaises(ValueError):
                DiscordRestClient(token)
        DiscordRestClient("abc.DEF_123-xyz")  # 정상

    def test_numeric_parameters(self):
        for name, values in {"timeout": (0, -1, None, "5", float("nan"), float("inf"), True),
                             "max_retries": (-1, 1.5, "3", True, None),
                             "backoff_base": (-1, float("nan"), "1"), "max_backoff": (-0.1, float("inf")),
                             "max_retry_after": (-1, float("nan")), "time_budget": (0, -5, "10", float("nan"), True)}.items():
            for value in values:
                with self.subTest(name=name, value=repr(value)), self.assertRaises(ValueError):
                    DiscordRestClient(TOKEN, **{name: value})
        DiscordRestClient(TOKEN, timeout=0.001, max_retries=0, backoff_base=0, max_backoff=0, max_retry_after=0,
                          time_budget=1)

    def test_max_retries_zero_means_a_single_attempt(self):
        fake = FakeDiscord()
        self.addCleanup(fake.close)
        fake.queue("GET", f"/channels/{CHANNEL}", {"status": 500, "body": {}}, {"body": {"id": "late"}})
        with self.assertRaises(DiscordServerError):
            DiscordRestClient(TOKEN, base_url=fake.url, max_retries=0, sleep=lambda s: None).get_channel(CHANNEL)
        self.assertEqual(len(fake.requests), 1)

    def test_blank_message_content_rejected_before_any_request(self):
        fake = FakeDiscord()
        self.addCleanup(fake.close)
        client = DiscordRestClient(TOKEN, base_url=fake.url, sleep=lambda s: None)
        for content in ("", "   ", "\n\t ", "　"):
            for embeds in (None, [{"title": "t"}]):
                with self.subTest(content=repr(content), embeds=bool(embeds)), self.assertRaises(ValueError):
                    client.send_message(CHANNEL, content=content, embeds=embeds)
        with self.assertRaises(ValueError):
            client.send_message(CHANNEL, content=123)
        self.assertEqual(fake.requests, [], "검증 실패 시 요청을 보내지 않는다")
        fake.queue("POST", f"/channels/{CHANNEL}/messages", {"body": {"id": "1"}}, {"body": {"id": "2"}})
        client.send_message(CHANNEL, content=" 앞뒤 공백은 허용 ")
        client.send_message(CHANNEL, embeds=[{"title": "t"}])  # content 없이 embeds만
        self.assertEqual(len(fake.requests), 2)


class MessageQuery(RestTestCase):
    """B3: before/after 동시 지정 금지, 정상 페이지네이션 유지."""
    PATH = f"/channels/{CHANNEL}/messages"

    def test_before_and_after_together_rejected(self):
        with self.assertRaises(ValueError):
            self.make().get_recent_messages(CHANNEL, 50, before=5, after=3)
        self.assertEqual(self.fake.requests, [])

    def test_pagination_is_preserved(self):
        self.fake.queue("GET", self.PATH, {"body": [{"id": "30"}, {"id": "20"}]}, {"body": [{"id": "10"}]}, {"body": []})
        client = self.make()
        first = client.get_recent_messages(CHANNEL, 2)
        second = client.get_recent_messages(CHANNEL, 2, before=int(first[-1]["id"]))
        client.get_recent_messages(CHANNEL, 2, after=int(second[0]["id"]))
        self.assertEqual([r["query"] for r in self.fake.requests], ["limit=2", "limit=2&before=20", "limit=2&after=10"])

    def test_limit_must_be_an_int_in_range(self):
        for bad in (True, "50", 50.0, 0, 101, -1, None):
            with self.subTest(limit=repr(bad)), self.assertRaises(ValueError):
                self.make().get_recent_messages(CHANNEL, bad)
        for good in (1, 100):
            self.fake.queue("GET", self.PATH, {"body": []})
            self.make().get_recent_messages(CHANNEL, good)


class NonceRetryPolicy(RestTestCase):
    """B7: nonce/enforce_nonce는 문서 설명과 코드 주석이 일치하고, 실제 검증 전까지 자동 재시도 정책은 그대로다."""
    PATH = f"/channels/{CHANNEL}/messages"

    def test_docstring_describes_documented_but_unverified_behavior(self):
        doc = DiscordRestClient.send_message.__doc__
        for phrase in ("enforce_nonce", "25자", "새 메시지를 만들지 않고 그 기존 메시지를 돌려준다", "검증하지 않았다",
                       "자동 재시도 정책을\n    바꾸지 않는다"):
            self.assertIn(phrase, doc)

    def test_ambiguous_failures_are_still_not_retried_even_with_nonce(self):
        self.fake.queue("POST", self.PATH, {"status": 500, "body": {}, "executes": True}, {"body": {"id": "2"}})
        with self.assertRaises(DiscordServerError) as ctx:
            self.make().send_message(CHANNEL, content="x", nonce="n-1")
        self.assertTrue(ctx.exception.outcome_unknown)
        self.assertEqual(self.fake.count("POST", self.PATH), 1)
        self.fake.requests.clear(); self.fake.queues.clear()
        self.fake.queue("POST", self.PATH, {"body": {"id": "late"}, "delay": 0.6, "executes": True}, {"body": {"id": "2"}})
        with self.assertRaises(DiscordTimeoutError) as ctx:
            self.make(timeout=0.2).send_message(CHANNEL, content="x", nonce="n-1")
        self.assertTrue(ctx.exception.outcome_unknown)
        self.assertEqual(self.fake.count("POST", self.PATH), 1)

    def test_429_is_still_retried_with_nonce(self):
        self.fake.queue("POST", self.PATH, {"status": 429, "body": {"retry_after": 0.1}}, {"body": {"id": "1"}})
        self.make().send_message(CHANNEL, content="x", nonce="n-1")
        self.assertEqual(self.fake.count("POST", self.PATH), 2)
        self.assertEqual({r["body"]["nonce"] for r in self.fake.requests}, {"n-1"})  # 같은 nonce로 다시 보낸다


class InactivitySafety(unittest.TestCase):
    """B5: 시간대 없는 입력, 누락 필드, 확인 불가 상황은 삭제를 허용하지 않는다 (순수 함수 테스트)."""
    RULE = dict(inactivity_days=7, grace_hours=24)
    NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    SINCE = NOW - timedelta(days=1)

    @staticmethod
    def msg(at, bot=False):
        return {"timestamp": at.isoformat(), "author": {"id": "1", "bot": bot}}

    @staticmethod
    def snowflake_at(moment):
        return (int(moment.timestamp() * 1000) - 1420070400000) << 22

    def test_naive_datetimes_are_rejected_clearly(self):
        naive = datetime(2026, 11, 21, 12, 0)
        with self.assertRaises(ValueError):
            inactivity.decide_action({}, naive, **self.RULE)
        for key in ("last_activity_at", "inactivity_warned_at", "scheduled_delete_at", "discord_deleted_at"):
            with self.subTest(key), self.assertRaisesRegex(ValueError, key):
                inactivity.decide_action({key: naive}, self.NOW, **self.RULE)
        with self.assertRaises(ValueError):
            inactivity.latest_user_message_at([], naive)
        with self.assertRaises(ValueError):
            inactivity.check_activity_for_deletion([], naive, limit=50)
        with self.assertRaises(ValueError):
            inactivity.decide_action({"last_activity_at": "2026-11-01"}, self.NOW, **self.RULE)  # datetime이 아님

    def test_cancel_schedule_branch(self):
        due = {"scheduled_delete_at": self.NOW - timedelta(minutes=1), "inactivity_warned_at": self.NOW - timedelta(hours=25),
               "last_activity_at": self.NOW - timedelta(hours=24)}
        self.assertEqual(inactivity.decide_action(due, self.NOW, **self.RULE)[0], inactivity.CANCEL_SCHEDULE)
        self.assertEqual(inactivity.decide_action({**due, "last_activity_at": self.NOW - timedelta(days=9)}, self.NOW,
                                                  **self.RULE)[0], inactivity.DELETE_DUE)
        self.assertEqual(inactivity.decide_action({**due, "scheduled_delete_at": self.NOW + timedelta(seconds=1)},
                                                  self.NOW, **self.RULE)[0], inactivity.WAIT_DELETE)
        # 예약은 있는데 경고 시각이 없으면 삭제하지 않는다 (기존 _delete_checked와 같음)
        self.assertEqual(inactivity.decide_action({**due, "inactivity_warned_at": None}, self.NOW, **self.RULE)[0],
                         inactivity.HOLD)

    def test_missing_or_bad_timestamps_fail_safely(self):
        bad_lists = [[{"author": {}}], [{"timestamp": None}], [{"timestamp": ""}], [{"timestamp": 123}],
                     [{"timestamp": "yesterday"}], ["not a dict"], [None]]
        for messages in bad_lists:
            with self.subTest(messages=messages):
                with self.assertRaises(inactivity.ActivityUnverifiable):
                    inactivity.latest_user_message_at(messages, self.SINCE)
                self.assertEqual(inactivity.check_activity_for_deletion(messages, self.SINCE, limit=50), inactivity.UNKNOWN)
        with self.assertRaises(inactivity.ActivityUnverifiable):
            inactivity.latest_user_message_at(None, self.SINCE)
        self.assertTrue(issubclass(inactivity.ActivityUnverifiable, ValueError))
        # latest_user_message_at은 기존 lifecycle처럼 첫 사용자 메시지에서 멈추므로 뒤쪽의 깨진 메시지는 보지 않는다.
        # 그래도 삭제 판단(check_activity_for_deletion)은 목록 전체를 검증해 UNKNOWN으로 막는다.
        broken_tail = [self.msg(self.NOW - timedelta(hours=1)), {"author": {"bot": False}}]
        self.assertIsNotNone(inactivity.latest_user_message_at(broken_tail, self.SINCE))
        self.assertEqual(inactivity.check_activity_for_deletion(broken_tail, self.SINCE, limit=50), inactivity.UNKNOWN)

    def test_only_a_confirmed_absence_of_activity_allows_deletion(self):
        check = inactivity.check_activity_for_deletion
        hour = timedelta(hours=1)
        at = lambda hours: self.NOW - hour * hours  # noqa: E731  (since 이후: 23시간 전까지)
        cases = {
            "조회 실패(None)": (None, {}, inactivity.UNKNOWN),
            "list 아님": ("x", {}, inactivity.UNKNOWN),
            "사용자 메시지 발견": ([self.msg(at(2)), self.msg(at(30))], {}, inactivity.ACTIVE),
            "봇 뒤에 사용자 메시지": ([self.msg(at(1), bot=True), self.msg(at(3))], {}, inactivity.ACTIVE),
            "since까지 봇 메시지뿐": ([self.msg(at(1), bot=True), self.msg(at(30))], {}, inactivity.NO_ACTIVITY),
            "since 이후 봇만, 페이지 안 참": ([self.msg(at(1), bot=True), self.msg(at(2), bot=True)], {}, inactivity.NO_ACTIVITY),
            "빈 목록, last_message_id 모름": ([], {}, inactivity.UNKNOWN),
            "빈 목록, 채널에 메시지 없음": ([], {"last_message_id": None}, inactivity.NO_ACTIVITY),
            "빈 목록, 마지막 메시지가 since 이후(권한으로 숨김 의심)": (
                [], {"last_message_id": self.snowflake_at(at(2))}, inactivity.UNKNOWN),
            "빈 목록, 마지막 메시지가 since 이전": ([], {"last_message_id": self.snowflake_at(at(30))}, inactivity.NO_ACTIVITY),
            "빈 목록, last_message_id 형식 오류": ([], {"last_message_id": "abc"}, inactivity.UNKNOWN),
            "최신순 아님": ([self.msg(at(5), bot=True), self.msg(at(2), bot=True)], {}, inactivity.UNKNOWN),
        }
        for label, (messages, extra, expected) in cases.items():
            with self.subTest(label):
                self.assertEqual(check(messages, self.SINCE, limit=50, **extra), expected, label)
        full = [self.msg(at(1 + i / 100), bot=True) for i in range(5)]  # 5개 모두 since 이후 봇 메시지
        self.assertEqual(check(full, self.SINCE, limit=5), inactivity.UNKNOWN, "페이지가 가득 차 더 오래된 사용자 메시지를 못 봄")
        self.assertEqual(check(full, self.SINCE, limit=6), inactivity.NO_ACTIVITY)
        for bad_limit in (0, -1, True, "5", None):
            with self.subTest(limit=bad_limit), self.assertRaises(ValueError):
                check([], self.SINCE, limit=bad_limit)

    def test_snowflake_time_round_trip(self):
        moment = datetime(2026, 11, 21, 3, 4, 5, 123000, tzinfo=timezone.utc)
        self.assertEqual(inactivity.snowflake_time(self.snowflake_at(moment)), moment)

    def test_deletion_requires_both_the_schedule_decision_and_confirmed_inactivity(self):
        """계약 예시: DELETE_DUE이고 NO_ACTIVITY일 때만 삭제 허용. 그 밖에는 모두 삭제하지 않는다."""
        due = {"scheduled_delete_at": self.NOW - timedelta(minutes=1), "inactivity_warned_at": self.SINCE,
               "last_activity_at": self.NOW - timedelta(days=9)}
        action, _ = inactivity.decide_action(due, self.NOW, **self.RULE)
        self.assertEqual(action, inactivity.DELETE_DUE)
        for messages, expected_allowed in (([], False), (None, False), ([self.msg(self.NOW - timedelta(hours=2))], False),
                                           ([self.msg(self.NOW - timedelta(hours=30), bot=True)], True)):
            verdict = inactivity.check_activity_for_deletion(messages, self.SINCE, limit=50)
            self.assertEqual(verdict == inactivity.NO_ACTIVITY, expected_allowed, (messages, verdict))


class ExternalAccessGuard(unittest.TestCase):
    """이 파일의 테스트가 실제 Discord(외부 호스트)에 접속하지 않는다는 것을 보장하는 장치를 확인한다."""

    def test_guard_blocks_the_default_discord_url(self):
        before = len(_BLOCKED)
        with self.assertRaises(AssertionError):
            DiscordRestClient(TOKEN, sleep=lambda s: None).get_channel(CHANNEL)  # 기본 base_url = https://discord.com/api/v10
        self.assertEqual(_BLOCKED[before:], ["discord.com"])
        del _BLOCKED[before:]  # 의도한 차단 기록은 모듈 종료 검사에서 제외한다

    def test_no_unexpected_external_access_so_far(self):
        self.assertEqual(_BLOCKED, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
