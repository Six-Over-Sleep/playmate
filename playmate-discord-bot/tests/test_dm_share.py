"""댓글·대댓글 DM Lambda 전환(dm_share, Issue #171) 테스트.

실제 Discord/AWS/공용 DB에는 접속하지 않는다. 받는 사람별 DM 채널을 가진 가짜 Discord(127.0.0.1)와 메모리 SQS를 쓰고,
#163 테스트의 외부 접속 차단 장치를 재사용한다. DB 테스트는 일회용 로컬 PostgreSQL에서만 실행한다 (public 스키마를 다시 만든다).
  PLAYMATE_TEST_PG_DSN="host=127.0.0.1 port=55432 user=postgres password=test dbname=pm" python tests/test_dm_share.py
회원 탈퇴는 backend의 실제 member_service.withdraw_member를 같은 DB에서 실행한다 (db_cursor만 테스트 DB로 바꾼다).
"""
import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ["DISCORD_BOT_TOKEN"] = "verification-only"
os.environ["DISCORD_GUILD_ID"] = "1"
for _name in ("PLAYMATE_WEB_BASE_URL", "PLAYMATE_TEST_MODE", "DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME",
              "DB_SSLMODE", "PLAYMATE_DM_POLL_ENABLED"):
    os.environ[_name] = ""

import discord  # noqa: E402

import test_career_share as cs  # noqa: E402  (외부 접속 차단, 취업 Worker·설정 재사용)
from test_hot_share import hot_job  # noqa: E402
from career_share import contract  # noqa: E402
from career_share.queues import FakeQueue  # noqa: E402
from career_share.settings import SettingsError  # noqa: E402
from career_share.worker import CareerShareWorker  # noqa: E402
from career_share.worker_lambda import handle_records  # noqa: E402
from discord_rest import DiscordRestClient  # noqa: E402
from dm_share import db_lambda  # noqa: E402
from dm_share import settings as dm_settings  # noqa: E402
from dm_share.messages import dm_payload  # noqa: E402
from dm_share.service import DmShareService  # noqa: E402
from dm_share.worker_lambda import DmShareWorker  # noqa: E402
from hot_share.worker_lambda import HotShareWorker  # noqa: E402
from repositories import dm_delivery_repository as dmr  # noqa: E402
from services import notification_policy  # noqa: E402

UTC = timezone.utc
T0 = datetime.now(UTC).replace(microsecond=0)   # Gateway가 실제 시계를 쓰므로 실제 현재 시각을 기준으로 한다
TOKEN = cs.TOKEN
BASE = "https://playmate.example.com"
SEND_Q, RESULT_Q = "queue://dm-send", "queue://dm-result"
DSN = os.environ.get("PLAYMATE_TEST_PG_DSN")
SQL_DIR = REPO / "database" / "sql"
RECEIVER, ACTOR = 1, 2
RECEIVER_DISCORD = 111111111111111111


def setUpModule():
    cs.setUpModule()


def tearDownModule():
    cs.tearDownModule()


def make_settings(**over) -> dm_settings.DmSettings:
    values = dict(send_queue_url=SEND_Q, base_url=BASE, relay_limit=20, job_ttl_seconds=50, claim_stale_minutes=10,
                  retry_seconds=60, max_attempts=3, verify_interval_minutes=10, max_verifies=6, verify_settle_minutes=30,
                  absent_required=2)
    values.update(over)
    return dm_settings.DmSettings(**values)


def notification_row(nid=7, kind="COMMENT", title="내 글", **over):
    row = dict(notification_id=nid, notification_type=kind, receiver_member_id=RECEIVER, actor_member_id=ACTOR,
               post_id=10, comment_id=100, retry_count=0, receiver_discord_id=str(RECEIVER_DISCORD), receiver_dm_opt_in=None,
               post_title=title, post_type="BOARD", post_board_id=3, recruit_id=None, career_category=None, target_missing=False)
    row.update(over)
    return row


def dm_job(nid=7, recipient=RECEIVER_DISCORD, claimed_at=T0, token="dmtok1"):
    service = DmShareService(None, FakeQueue(), make_settings())
    claim = {"unit_id": f"dm-{nid}", "kind": "DM", "claim_token": token, "claimed_at": claimed_at,
             "recipient_id": str(recipient), "notification": notification_row(nid)}
    return service._job(claim, claimed_at, contract.TYPE_SEND)


# -- 받는 사람별 DM 채널을 가진 가짜 Discord ----------------------------------------------------------------------
class FakeDmDiscord:
    """POST /users/@me/channels로 DM 채널을 열고, 채널별로 메시지를 저장·조회한다.

    fail_post: 다음 메시지 POST 동작 목록 ('ok', '500', 'store500', 'late500', '429', '403:50007', '403:50001', '400:50033')
    fail_open: {user_id: (status, code)} DM 채널 열기 실패 / fail_get: 메시지 목록 GET 실패 횟수 / hide_history: 목록을 비워서 줌
    """

    def __init__(self):
        self.lock = threading.RLock()
        self.now = T0
        self.seq = 0
        self.messages: dict[int, list] = {}
        self.posts: list[tuple[int, dict]] = []
        self.opens: list[int] = []
        self.requests = 0
        self.fail_post: list[str] = []
        self.fail_open: dict[int, tuple[int, int]] = {}
        self.fail_get = 0
        self.fail_get_status = 500      # fail_get 동안의 GET 응답 (500 / 401 / 429)
        self.hide_history = False
        self.delayed: list[tuple[int, dict]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, body, headers=None):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Type", "application/json")
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                path = self.path.split("?")[0]
                with outer.lock:
                    outer.requests += 1
                    if path.endswith("/users/@me/channels"):
                        user = int(body["recipient_id"])
                        outer.opens.append(user)
                        if user in outer.fail_open:
                            status, code = outer.fail_open[user]
                            return self._send(status, {"message": "err", "code": code})
                        return self._send(200, {"id": str(outer.channel_of(user)), "type": 1,
                                                "last_message_id": outer.last_id(outer.channel_of(user))})
                    channel = int(path.split("/channels/")[1].split("/")[0])
                    outer.posts.append((channel, body))
                    mode = outer.fail_post.pop(0) if outer.fail_post else "ok"
                    if mode in ("ok", "store500", "late500"):
                        outer.seq += 1
                        message = dict(body, id=str(cs.snowflake(outer.now, outer.seq)), timestamp=outer.now.isoformat(),
                                       channel_id=str(channel), author={"id": "9", "bot": True})
                        if mode == "late500":
                            outer.delayed.append((channel, message))
                        else:
                            outer.messages.setdefault(channel, []).append(message)
                    if mode == "ok":
                        return self._send(200, message)
                    if mode in ("500", "store500", "late500"):
                        return self._send(500, {"message": "boom"})
                    if mode == "429":
                        return self._send(429, {"message": "rate", "retry_after": 0.01, "global": False}, {"Retry-After": "0.01"})
                    status, code = mode.split(":")
                    return self._send(int(status), {"message": "err", "code": int(code)})

            def do_GET(self):
                path, _, query = self.path.partition("?")
                params = dict(p.split("=") for p in query.split("&") if p)
                with outer.lock:
                    outer.requests += 1
                    channel = int(path.split("/channels/")[1].split("/")[0])
                    if path.endswith("/messages"):
                        if outer.fail_get > 0:
                            outer.fail_get -= 1
                            if outer.fail_get_status == 429:
                                return self._send(429, {"message": "rate", "retry_after": 0.01, "global": False},
                                                  {"Retry-After": "0.01"})
                            return self._send(outer.fail_get_status, {"message": "err", "code": 0})
                        items = [] if outer.hide_history else sorted(outer.messages.get(channel, []),
                                                                     key=lambda m: int(m["id"]), reverse=True)
                        if "before" in params:
                            items = [m for m in items if int(m["id"]) < int(params["before"])]
                        return self._send(200, items[:int(params.get("limit", 50))])
                    return self._send(200, {"id": str(channel), "type": 1, "last_message_id": outer.last_id(channel)})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_port}/api/v10"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @staticmethod
    def channel_of(user: int) -> int:
        return 800000000000000000 + user % 100000

    def last_id(self, channel):
        ids = [int(m["id"]) for m in self.messages.get(channel, [])]
        return str(max(ids)) if ids else None

    def bot_messages(self, user=RECEIVER_DISCORD):
        return [m for m in self.messages.get(self.channel_of(user), []) if (m.get("author") or {}).get("bot")]

    def markers(self, user=RECEIVER_DISCORD):
        return [((m.get("embeds") or [{}])[0].get("footer") or {}).get("text") for m in self.bot_messages(user)]

    def release_delayed(self, moment):
        with self.lock:
            for channel, message in self.delayed:
                self.seq += 1
                message.update(id=str(cs.snowflake(moment, self.seq)), timestamp=moment.isoformat())
                self.messages.setdefault(channel, []).append(message)
            self.delayed = []

    def seed_user_messages(self, count, start, user=RECEIVER_DISCORD):
        with self.lock:
            for i in range(count):
                self.seq += 1
                moment = start + timedelta(seconds=i)
                self.messages.setdefault(self.channel_of(user), []).append(
                    {"id": str(cs.snowflake(moment, self.seq)), "timestamp": moment.isoformat(), "content": "hi",
                     "embeds": [], "author": {"id": str(user)}})

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def rest_client(fake):
    return DiscordRestClient(TOKEN, base_url=fake.url, timeout=3.0, max_retries=0, sleep=lambda s: None)


# =====================================================================================================================
# DB 없이 실행하는 테스트
# =====================================================================================================================
class PolicyAndMessages(unittest.TestCase):
    def test_gateway_module_reexports_same_rules(self):
        import config
        from services import notification_service as ns
        for name in ("dm_allowed", "build_dm_message", "DM_MESSAGES", "LINK_LABEL"):
            self.assertIs(getattr(ns, name), getattr(notification_policy, name))
        for row in (notification_row(), notification_row(actor_member_id=RECEIVER), notification_row(target_missing=True),
                    notification_row(receiver_dm_opt_in=False), notification_row(receiver_discord_id="w12"),
                    notification_row(kind="REACTION")):
            self.assertEqual(ns.NotificationService.skip_reason(row), notification_policy.skip_reason(row))
        self.assertEqual((dm_settings.DEFAULTS["retry_seconds"], dm_settings.DEFAULTS["max_attempts"]),
                         (config.NOTIFICATION_RETRY_DELAY_SECONDS, config.NOTIFICATION_MAX_ATTEMPTS))
        self.assertEqual(dm_settings.DEFAULTS["job_ttl_seconds"], 50)
        self.assertLess(dm_settings.DEFAULTS["job_ttl_seconds"], dm_settings.DEFAULTS["retry_seconds"])

    def test_embed_format_and_gateway_text_unchanged(self):
        payload = dm_payload(notification_row(nid=42, title="@everyone [내] 글"), f"{BASE}/board/3/posts/10")
        embed = payload["embeds"][0]
        self.assertEqual(embed["title"], "💬 내 게시글에 새 댓글이 달렸어요.")
        self.assertEqual(embed["footer"]["text"], "ref:dm-42")
        self.assertIn(f"[{notification_policy.LINK_LABEL}]({BASE}/board/3/posts/10)", embed["description"])
        self.assertNotIn("@everyone", embed["description"])
        self.assertEqual(set(embed), {"title", "color", "footer", "description", "url"})
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        reply = dm_payload(notification_row(kind="REPLY", title=None), None)["embeds"][0]
        self.assertEqual((reply["title"], "description" in reply), ("↪️ 내 댓글에 새 답글이 달렸어요.", False))
        self.assertEqual(notification_policy.build_dm_message(notification_row(title="내 글"), "https://x.test/a"),
                         "💬 내 게시글에 새 댓글이 달렸어요.\n게시글: 내 글\n🔗 PlayMate에서 보기: https://x.test/a")
        job = dm_job(nid=42)
        self.assertEqual((job["unit_id"], job["kind"], job["recipient_id"]), ("dm-42", "DM", str(RECEIVER_DISCORD)))
        self.assertEqual(contract.parse_time(job["not_after"]) - T0, timedelta(seconds=50))

    def test_settings(self):
        env = {"DM_SHARE_SEND_QUEUE_URL": "https://sqs/dm"}
        self.assertEqual(dm_settings.load_dm_settings(env).job_ttl_seconds, 50)
        for bad in ({}, env | {"CAREER_SHARE_SEND_QUEUE_URL": "https://sqs/dm"}, env | {"HOT_SHARE_SEND_QUEUE_URL": "https://sqs/dm"},
                    env | {"DM_SHARE_JOB_TTL_SECONDS": "60"}, env | {"DM_SHARE_JOB_TTL_SECONDS": "90"},   # R4: TTL >= 재시도 간격 거부
                    env | {"DM_SHARE_CLAIM_STALE_MINUTES": "1", "DM_SHARE_JOB_TTL_SECONDS": "90", "DM_SHARE_RETRY_SECONDS": "200"}):
            with self.assertRaises(SettingsError, msg=bad):
                dm_settings.load_dm_settings(bad)

    def test_dm_poll_flag(self):
        code = "import config; print(config.DM_POLL_ENABLED)"
        for value, expected in (("", "True"), ("true", "True"), ("false", "False"), ("0", "False"), ("off", "False")):
            env = dict(os.environ, PLAYMATE_DM_POLL_ENABLED=value)
            out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertEqual(out.stdout.strip(), expected, out.stderr[-300:])
        src = (ROOT / "bot.py").read_text(encoding="utf-8")
        gate = src.index("if DM_POLL_ENABLED:")
        self.assertLess(src.index("build_notification_command(notification_service)"), gate, "/알림설정은 플래그와 무관하게 등록")
        self.assertIn("create_notification_task", src[gate:gate + 200])


class WorkerIsolation(unittest.TestCase):
    """DM·취업·HOT 작업이 다른 Worker로 가도 Discord 호출 전에 거부된다."""

    def setUp(self):
        self.fake = FakeDmDiscord()
        self.client = rest_client(self.fake)

    def tearDown(self):
        self.fake.close()

    def test_every_wrong_pairing_is_rejected_before_any_request(self):
        career_job = dict(hot_job(), unit_id="post-7", kind="IMMEDIATE", marker="ref:post-7")
        career_job["payload"]["embeds"][0]["footer"]["text"] = "ref:post-7"
        workers = {"career": CareerShareWorker(self.client, 555555555555555555, clock=lambda: T0),
                   "hot": HotShareWorker(self.client, 666666666666666666, clock=lambda: T0),
                   "dm": DmShareWorker(self.client, clock=lambda: T0)}
        jobs = {"career": career_job, "hot": hot_job(), "dm": dm_job()}
        for wname, worker in workers.items():
            for jname, job in jobs.items():
                if wname == jname:
                    continue
                for candidate in (job, {k: v for k, v in job.items() if k != "payload"} | {"type": contract.TYPE_VERIFY}):
                    with self.assertRaises(contract.ContractError, msg=f"{jname} -> {wname}"):
                        worker.process(candidate)
        for bad in (dict(dm_job(), recipient_id="w12"), dict(dm_job(), recipient_id=""), dict(dm_job(), kind="HOT")):
            with self.assertRaises(contract.ContractError):
                workers["dm"].process(bad)
        self.assertEqual(self.fake.requests, 0)

    def test_dm_job_sent_once_even_if_delivered_twice(self):
        worker = DmShareWorker(self.client, clock=lambda: T0)
        job = dm_job()
        first, second = worker.process(job), worker.process(job, receive_count=2)
        self.assertEqual((first["outcome"], second["outcome"], first["message_id"]), ("SENT", "SENT", second["message_id"]))
        self.assertEqual(self.fake.markers(), ["ref:dm-7"])
        self.assertEqual(first["channel_id"], str(self.fake.channel_of(RECEIVER_DISCORD)))


# =====================================================================================================================
# 일회용 PostgreSQL 테스트
# =====================================================================================================================
SCHEMA = """
CREATE TABLE members (member_id BIGINT PRIMARY KEY, discord_id VARCHAR(64), nickname VARCHAR(50),
    member_status VARCHAR(20) DEFAULT 'ACTIVE', role_code VARCHAR(20) DEFAULT 'USER', course VARCHAR(40), cohort INT,
    profile_image_url TEXT, external_dm_opt_in BOOLEAN, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE posts (post_id BIGINT PRIMARY KEY, board_id BIGINT, post_type VARCHAR(30), title VARCHAR(100),
    author_member_id BIGINT, deleted_at TIMESTAMP);
CREATE TABLE comments (comment_id BIGINT PRIMARY KEY, post_id BIGINT REFERENCES posts(post_id), author_member_id BIGINT,
    deleted_at TIMESTAMP);
CREATE TABLE recruits (recruit_id BIGINT PRIMARY KEY, post_id BIGINT UNIQUE);
CREATE TABLE career_posts (post_id BIGINT PRIMARY KEY, category_code VARCHAR(20));
CREATE TABLE member_enrollments (enrollment_id BIGINT PRIMARY KEY, member_id BIGINT);
CREATE TABLE enrollment_verifications (verification_id BIGINT PRIMARY KEY,
    enrollment_id BIGINT REFERENCES member_enrollments(enrollment_id));
CREATE TABLE member_career_specs (member_id BIGINT PRIMARY KEY);
CREATE TABLE post_reactions (post_id BIGINT, member_id BIGINT, reaction_type VARCHAR(10));
INSERT INTO members (member_id, discord_id, nickname) VALUES
    (1, '111111111111111111', 'receiver'), (2, '222222222222222222', 'actor'), (3, '333333333333333333', 'third');
INSERT INTO posts VALUES (10, 3, 'BOARD', '내 글', 1, NULL);
"""


@unittest.skipUnless(DSN, "PLAYMATE_TEST_PG_DSN 없음: PostgreSQL 통합 테스트 미실시")
class PgCase(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
        if conninfo_to_dict(DSN).get("host") not in ("127.0.0.1", "localhost"):
            self.fail("일회용 로컬 DB(127.0.0.1/localhost)에서만 실행합니다.")
        self.psycopg = psycopg
        self.admin = psycopg.connect(DSN, autocommit=True, options="-c TimeZone=Asia/Seoul")
        self.admin.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        self.admin.execute(SCHEMA)
        for name in ("022_discord_bot_tables.sql", "053_notification_dm_deliveries.sql"):
            self.admin.execute((SQL_DIR / name).read_text(encoding="utf-8"))
        self._dbs, self._fakes, self._extra = [], [], []
        self.comment_seq = 100

    def tearDown(self):
        for fake in self._fakes:
            fake.close()
        for db in self._dbs:
            db._reset()
        for conn in self._extra:
            conn.close()
        self.admin.close()

    # -- 준비 도구 ----------------------------------------------------------------------------------------------
    def new_db(self, app="dm_test"):
        """Gateway(connect_from_env)·Lambda(connect_for_lambda)와 같은 세션 TimeZone=Asia/Seoul 연결."""
        from repositories.db import Database
        db = Database(lambda: self.psycopg.connect(DSN, autocommit=True, application_name=app,
                                                   options="-c TimeZone=Asia/Seoul"))
        self._dbs.append(db)
        return db

    def repo(self, app="dm_test"):
        return dmr.DmDeliveryRepository(self.new_db(app), retry_seconds=60, max_attempts=3)

    def notify(self, kind="COMMENT", receiver=RECEIVER, actor=ACTOR):
        self.comment_seq += 1
        self.admin.execute("INSERT INTO comments VALUES (%s, 10, %s, NULL)", (self.comment_seq, actor))
        return self.admin.execute(
            "INSERT INTO notifications (receiver_member_id, actor_member_id, notification_type, post_id, comment_id) "
            "VALUES (%s, %s, %s, 10, %s) RETURNING notification_id", (receiver, actor, kind, self.comment_seq)).fetchone()[0]

    def notif(self, nid):
        cur = self.admin.cursor(row_factory=self.psycopg.rows.dict_row)
        cur.execute("SELECT status, retry_count, error_message, sent_at FROM notifications WHERE notification_id = %s", (nid,))
        return cur.fetchone()

    def delivery(self, nid):
        cur = self.admin.cursor(row_factory=self.psycopg.rows.dict_row)
        cur.execute(f"SELECT * FROM {dmr.TABLE} WHERE notification_id = %s", (nid,))
        return cur.fetchone()

    def age_attempts(self, seconds=120):
        """notifications.last_attempt_at(DB 실제 시계)을 과거로 옮긴다 = 60초 재시도 간격이 지났다."""
        self.admin.execute("UPDATE notifications SET last_attempt_at = last_attempt_at - make_interval(secs => %s) "
                           "WHERE last_attempt_at IS NOT NULL", (seconds,))

    def age_retry(self, seconds=120):
        """전송 행의 next_retry_at을 과거로 옮긴다 = Gateway(실제 시계)가 기록한 60초 재시도 시각이 지났다."""
        self.admin.execute(f"UPDATE {dmr.TABLE} SET next_retry_at = next_retry_at - make_interval(secs => %s) "
                           "WHERE next_retry_at IS NOT NULL", (seconds,))

    def age_claims(self, minutes, nid=None):
        """전송 행의 claimed_at을 과거로 옮긴다 = Lambda 선점 후 그만큼 지났다 (16분 교차 인수 판정은 DB 시각 기준)."""
        self.admin.execute(f"UPDATE {dmr.TABLE} SET claimed_at = claimed_at - make_interval(mins => %s) "
                           "WHERE (%s::bigint IS NULL OR notification_id = %s)", (minutes, nid, nid))

    def age_auth(self, minutes):
        """인증 표시 행의 updated_at(DB 시각)을 과거로 옮긴다 = 마지막 401 이후 그만큼 지났다."""
        self.admin.execute(f"UPDATE {dmr.TABLE} SET updated_at = updated_at - make_interval(mins => %s) "
                           "WHERE error_message LIKE 'DISCORD_AUTH%%'", (minutes,))

    def lam(self, **over):
        pipe = LambdaPipe(self, **over)
        self._fakes.append(pipe.fake)
        return pipe

    def gateway(self, client=None, *, deliveries=True, takeover=dmr.GATEWAY_TAKEOVER_MINUTES):
        from repositories.notification_repository import PostgresNotificationRepository
        from services.notification_service import NotificationService
        db = self.new_db("dm_gateway")
        client = client or FakeGatewayClient()
        repo = dmr.DmDeliveryRepository(db, retry_seconds=60, max_attempts=3,
                                        gateway_takeover_minutes=takeover) if deliveries else None
        return NotificationService(client, PostgresNotificationRepository(db), base_url=BASE, deliveries=repo), client

    def wait_until_waiting(self, app):
        for _ in range(200):
            n = self.admin.execute("SELECT COUNT(*) FROM pg_stat_activity WHERE application_name = %s AND wait_event_type = 'Lock'",
                                   (app,)).fetchone()[0]
            if n:
                return
            time.sleep(0.05)
        self.fail(f"{app} 연결이 잠금 대기에 들어가지 않았습니다.")


class LambdaPipe:
    """DM DB Lambda 서비스 + 메모리 SQS + DM Worker(가짜 Discord)."""

    def __init__(self, case, **over):
        self.fake = FakeDmDiscord()
        self.queue = FakeQueue()
        self.clock = T0
        self.repo = case.repo("dm_lambda")
        self.service = DmShareService(self.repo, self.queue, make_settings(**over), clock=lambda: self.clock)
        self.worker = DmShareWorker(rest_client(self.fake), clock=lambda: self.clock)
        self.results: list[dict] = []

    def at(self, moment):
        self.clock = moment
        self.fake.now = moment
        return self

    def relay(self):
        return self.service.relay(self.clock)

    def jobs(self):
        return [contract.loads(b) for b in self.queue.bodies(SEND_Q)]

    def run_worker(self, *, receive_count=1):
        bodies = self.queue.bodies(SEND_Q)
        self.queue.messages = [m for m in self.queue.messages if m[0] != SEND_Q]
        before = len(self.queue.bodies(RESULT_Q))
        out = handle_records({"Records": [{"messageId": f"m{i}", "body": b,
                                           "attributes": {"ApproximateReceiveCount": str(receive_count)}}
                                          for i, b in enumerate(bodies)]}, self.worker, self.queue, RESULT_Q)
        self.results += [contract.loads(b) for b in self.queue.bodies(RESULT_Q)[before:]]
        return out

    def apply_results(self):
        bodies = self.queue.bodies(RESULT_Q)
        self.queue.messages = [m for m in self.queue.messages if m[0] != RESULT_Q]
        return [self.service.apply_result(b, self.clock) for b in bodies]

    def cycle(self):
        relay = self.relay()
        self.run_worker()
        return relay, self.apply_results()


class FakeGatewayClient:
    """discord.py Client 대역: fetch_user -> user.send(text). send_errors/fetch_errors는 순서대로 한 번씩 발생한다."""

    def __init__(self):
        self.sent: list[tuple[int, str]] = []
        self.send_errors: list[Exception] = []
        self.fetch_errors: list[Exception] = []

    def get_user(self, discord_id):
        return None

    async def fetch_user(self, discord_id):
        if self.fetch_errors:
            raise self.fetch_errors.pop(0)

        async def send(text):
            if self.send_errors:
                raise self.send_errors.pop(0)
            self.sent.append((discord_id, text))
        return SimpleNamespace(send=send)


def http_error(kind, status):
    return getattr(discord, kind)(SimpleNamespace(status=status, reason="test"), "test")


def run(coro):
    return asyncio.run(coro)


# -- 정상 경로 -----------------------------------------------------------------------------------------------------
class NormalPathTests(PgCase):
    def test_gateway_sends_text_through_shared_claim(self):
        nid = self.notify()
        service, client = self.gateway()
        run(service.poll_once())
        self.assertEqual(len(client.sent), 1)
        self.assertTrue(client.sent[0][1].startswith("💬 내 게시글에 새 댓글이 달렸어요.\n게시글: 내 글"))
        self.assertEqual(self.notif(nid)["status"], "SENT")
        row = self.delivery(nid)
        self.assertEqual((row["sender"], row["status"]), ("GATEWAY", "SENT"))
        run(service.poll_once())
        self.assertEqual(len(client.sent), 1)

    def test_lambda_sends_embed(self):
        nid = self.notify()
        p = self.lam()
        relay, applied = p.cycle()
        self.assertEqual((relay["claimed"], applied), (1, ["applied"]))
        self.assertEqual(p.fake.markers(), [f"ref:dm-{nid}"])
        sent = json.dumps(p.fake.posts[-1][1], ensure_ascii=False)
        self.assertIn("💬 내 게시글에 새 댓글이 달렸어요.", sent)
        self.assertIn(f"{BASE}/board/3/posts/10", sent)
        self.assertNotIn("actor", sent)
        self.assertEqual(self.notif(nid)["status"], "SENT")
        row = self.delivery(nid)
        self.assertEqual((row["sender"], row["status"], row["discord_message_id"]),
                         ("LAMBDA", "SENT", p.results[-1]["message_id"]))
        self.assertEqual(p.cycle()[0]["claimed"], 0)

    def test_skip_rules_applied_at_claim(self):
        self.admin.execute("INSERT INTO members (member_id, discord_id, nickname, external_dm_opt_in) VALUES "
                           "(4, '444444444444444444', 'off', FALSE), (5, 'w5', 'withdrawn', NULL)")
        off, gone, self_n, reaction = (self.notify(receiver=4), self.notify(receiver=5), self.notify(actor=RECEIVER),
                                       self.notify(kind="REACTION"))
        p = self.lam()
        self.assertEqual(p.cycle()[0]["claimed"], 0)
        self.assertEqual({nid: self.notif(nid)["error_message"] for nid in (off, gone, self_n, reaction)},
                         {off: "DM 알림 꺼짐", gone: "Discord 계정 없음", self_n: "본인 알림", reaction: "지원하지 않는 알림 종류: REACTION"})
        self.assertEqual({self.notif(n)["status"] for n in (off, gone, self_n, reaction)}, {"SKIPPED"})
        self.assertIsNone(self.delivery(off))

    def test_legacy_gateway_path_when_table_absent(self):
        self.admin.execute(f"DROP TABLE {dmr.TABLE}")
        nid = self.notify()
        service, client = self.gateway()
        run(service.poll_once())
        self.assertEqual((len(client.sent), self.notif(nid)["status"]), (1, "SENT"))


# -- 공동 선점 ----------------------------------------------------------------------------------------------------
class SharedClaimTests(PgCase):
    def test_gateway_and_lambda_claim_concurrently_disjoint(self):
        ids = [self.notify() for _ in range(12)]
        repos = [self.repo(f"dm_c{i}") for i in range(4)]
        for r in repos:
            r.available()
        barrier, out = threading.Barrier(4), [None] * 4

        def go(i):
            barrier.wait()
            out[i] = repos[i].claim("GATEWAY" if i % 2 else "LAMBDA", T0, limit=5, stale_seconds=600)
        threads = [threading.Thread(target=go, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(15)
        claimed = [c["notification"]["notification_id"] for batch in out for c in batch]
        self.assertEqual(len(claimed), len(set(claimed)), "같은 알림을 두 곳이 선점하지 않음")
        rest = self.repo().claim("LAMBDA", T0, limit=50, stale_seconds=600)
        self.assertEqual(sorted(claimed + [c["notification"]["notification_id"] for c in rest]), ids)

    def test_upsert_guard_only_reclaims_retryable_failed(self):
        """후보 SQL과 별개로 UPSERT 자체가 진행 중·완료·불명 행의 재선점을 막는다 (두 번째 방어선을 직접 검증)."""
        repo = self.repo()
        cases = {"gateway_pending": ("GATEWAY", "PENDING", None), "lambda_pending": ("LAMBDA", "PENDING", None),
                 "sent": ("GATEWAY", "SENT", None), "unknown": ("LAMBDA", "UNKNOWN", None),
                 "failed_final": ("LAMBDA", "FAILED", None), "failed_future": ("GATEWAY", "FAILED", T0 + timedelta(seconds=30)),
                 "failed_due": ("GATEWAY", "FAILED", T0 - timedelta(seconds=1))}
        ids = {}
        for name, (sender, status, retry) in cases.items():
            nid = ids[name] = self.notify()
            self.admin.execute(
                f"INSERT INTO {dmr.TABLE} (notification_id, sender, status, claim_token, claimed_at, claim_expires_at, next_retry_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (nid, sender, status, f"old-{name}", T0.replace(tzinfo=None), (T0 + timedelta(minutes=10)).replace(tzinfo=None),
                 retry.astimezone(UTC).replace(tzinfo=None) if retry else None))

        def work(cur):
            return {name: repo._claim_row(cur, notification_row(nid=nid), "LAMBDA", T0, 600) for name, nid in ids.items()}
        tokens = repo._db.transaction(work)
        for name in cases:
            row = self.delivery(ids[name])
            if name == "failed_due":
                self.assertIsNotNone(tokens[name])
                self.assertEqual((row["claim_token"], row["sender"], row["status"]), (tokens[name], "LAMBDA", "PENDING"))
            else:
                self.assertIsNone(tokens[name], name)
                self.assertEqual(row["claim_token"], f"old-{name}", f"{name}: 소유권 유지")

    def test_both_running_send_each_notification_once(self):
        ids = [self.notify() for _ in range(8)]
        service, client = self.gateway()
        p = self.lam(relay_limit=3)
        for _ in range(4):
            p.cycle()
            run(service.poll_once())
        lambda_sent = [m.split("-")[1] for m in p.fake.markers()]
        gateway_sent = len(client.sent)
        self.assertEqual(len(lambda_sent) + gateway_sent, len(ids))
        self.assertEqual({self.notif(n)["status"] for n in ids}, {"SENT"})
        senders = {self.delivery(n)["sender"] for n in ids}
        self.assertEqual(senders, {"GATEWAY", "LAMBDA"})

    def test_gateway_crash_after_claim_is_closed_without_resend(self):
        nid = self.notify()
        self.repo("dm_gateway").claim("GATEWAY", T0, limit=10, stale_seconds=600)   # Gateway가 선점 후 죽음
        p = self.lam()
        self.assertEqual(p.at(T0 + timedelta(minutes=5)).cycle()[0]["claimed"], 0, "Gateway 선점 중에는 Lambda가 가져가지 않음")
        with self.assertLogs("dm_share", level="WARNING") as logs:
            out, _ = p.at(T0 + timedelta(minutes=11)).cycle()
        self.assertEqual((out["gateway_expired"], out["claimed"]), (1, 0))
        self.assertTrue(any("만료" in line for line in logs.output))
        self.assertEqual((self.notif(nid)["status"], self.notif(nid)["retry_count"]), ("FAILED", 1))
        self.assertEqual((self.delivery(nid)["status"], self.delivery(nid)["next_retry_at"]), ("FAILED", None))
        self.age_attempts()
        self.assertEqual(p.at(T0 + timedelta(minutes=20)).cycle()[0]["claimed"], 0)
        self.assertEqual(p.fake.posts, [])

    def test_gateway_failure_policy_under_shared_claim(self):
        certain, uncertain, timeout, nouser = (self.notify() for _ in range(4))
        client = FakeGatewayClient()
        service, _ = self.gateway(client)
        # 순서대로 처리된다 (created_at 순): 403(확실) / 500(불명) / 타임아웃(불명) / 사용자 없음
        client.send_errors = [http_error("Forbidden", 403), http_error("HTTPException", 500), asyncio.TimeoutError()]
        client.fetch_errors = []
        run(service.deliver_claimed(self.repo("g").claim("GATEWAY", T0, limit=1, stale_seconds=600)[0]))
        with self.assertLogs("dm_share", level="WARNING"):
            run(service.deliver_claimed(self.repo("g").claim("GATEWAY", T0, limit=1, stale_seconds=600)[0]))
            run(service.deliver_claimed(self.repo("g").claim("GATEWAY", T0, limit=1, stale_seconds=600)[0]))
        client.fetch_errors = [http_error("NotFound", 404)]
        run(service.deliver_claimed(self.repo("g").claim("GATEWAY", T0, limit=1, stale_seconds=600)[0]))
        self.assertEqual((self.notif(certain)["status"], self.notif(certain)["retry_count"]), ("PENDING", 1))
        self.assertIsNotNone(self.delivery(certain)["next_retry_at"])
        for nid in (uncertain, timeout):
            self.assertEqual((self.notif(nid)["status"], self.notif(nid)["retry_count"]), ("FAILED", 1), "불명은 재발송 없이 마감")
            self.assertIsNone(self.delivery(nid)["next_retry_at"])
        self.assertEqual((self.notif(nouser)["status"], self.notif(nouser)["error_message"]), ("SKIPPED", "Discord 사용자 없음"))
        self.assertEqual(client.sent, [])

    def test_gateway_retry_count_three_then_failed(self):
        nid = self.notify()
        client = FakeGatewayClient()
        service, _ = self.gateway(client)
        for attempt in range(1, 4):
            client.send_errors = [http_error("Forbidden", 403)]
            claims = self.repo("g").claim("GATEWAY", datetime.now(UTC) + timedelta(seconds=61 * attempt), limit=5,
                                          stale_seconds=600)
            self.assertEqual(len(claims), 1, attempt)
            run(service.deliver_claimed(claims[0]))
            self.age_attempts()
        self.assertEqual((self.notif(nid)["status"], self.notif(nid)["retry_count"]), ("FAILED", 3))
        self.assertIsNone(self.delivery(nid)["next_retry_at"])
        self.assertEqual(self.repo().claim("LAMBDA", T0 + timedelta(hours=1), limit=5, stale_seconds=600), [])

    def test_failed_reclaim_rotates_token_and_ignores_old_result(self):
        nid = self.notify()
        p = self.lam()
        p.fake.fail_post = ["429"]
        p.cycle()
        first = p.results[-1]
        self.assertEqual((first["outcome"], self.notif(nid)["status"], self.notif(nid)["retry_count"]), ("FAILED_RETRY", "PENDING", 1))
        self.assertEqual(p.at(T0 + timedelta(seconds=30)).relay()["claimed"], 0, "60초 전에는 재선점하지 않음")
        self.age_attempts()
        p.queue.messages.clear()
        self.assertEqual(p.at(T0 + timedelta(seconds=61)).relay()["claimed"], 1)
        new_token = p.jobs()[0]["claim_token"]
        self.assertNotEqual(new_token, first["claim_token"])
        stale = dict(first, outcome="SENT", message_id="1" * 18)
        self.assertEqual(p.service.apply_result(contract.dumps(stale), p.clock), "ignored", "이전 토큰의 결과는 반영하지 않음")
        p.run_worker()
        self.assertEqual(p.apply_results(), ["applied"])
        self.assertEqual((self.notif(nid)["status"], self.delivery(nid)["claim_token"]), ("SENT", new_token))
        self.assertEqual(len(p.fake.bot_messages()), 1)

    def test_gateway_failed_row_can_be_retried_by_lambda_and_old_gateway_token_ignored(self):
        nid = self.notify()
        client = FakeGatewayClient()
        service, _ = self.gateway(client)
        claim = self.repo("g").claim("GATEWAY", T0, limit=1, stale_seconds=600)[0]
        client.send_errors = [http_error("Forbidden", 403)]
        run(service.deliver_claimed(claim))
        self.age_attempts()
        self.age_retry()
        p = self.lam()
        self.assertEqual(p.at(T0 + timedelta(seconds=61)).cycle()[0]["claimed"], 1)
        self.assertEqual((self.notif(nid)["status"], self.delivery(nid)["sender"]), ("SENT", "LAMBDA"))
        self.assertEqual(self.repo("g").gateway_sent(nid, claim["claim_token"], T0), "ignored")
        self.assertEqual(self.notif(nid)["retry_count"], 1)


# -- 결과 불명·마커 --------------------------------------------------------------------------------------------------
class UnknownTests(PgCase):
    def test_duplicate_sqs_delivery_sends_once(self):
        nid = self.notify()
        p = self.lam()
        p.relay()
        body = p.queue.bodies(SEND_Q)[0]
        p.queue.send(SEND_Q, body)
        p.run_worker()
        self.assertEqual(p.apply_results(), ["applied", "duplicate"])
        self.assertEqual(len(p.fake.bot_messages()), 1)
        self.assertEqual(self.notif(nid)["status"], "SENT")

    def test_lost_success_response_resolved_by_marker(self):
        nid = self.notify()
        p = self.lam()
        p.fake.fail_post = ["store500"]
        p.cycle()
        self.assertEqual((p.results[-1]["outcome"], self.notif(nid)["status"]), ("SENT", "SENT"))
        self.assertEqual(len(p.fake.bot_messages()), 1)

    def test_timeout_unknown_not_resent_and_late_message_found(self):
        nid = self.notify()
        p = self.lam()
        p.fake.fail_post = ["late500"]
        p.cycle()
        self.assertEqual((self.delivery(nid)["status"], self.notif(nid)["status"]), ("UNKNOWN", "PENDING"))
        self.assertEqual(p.at(T0 + timedelta(minutes=10)).cycle()[0]["recover"]["verify_jobs"], 0, "정착 대기")
        p.fake.release_delayed(T0 + timedelta(seconds=20))
        p.at(T0 + timedelta(minutes=31)).cycle()
        self.assertEqual((self.delivery(nid)["status"], self.notif(nid)["status"]), ("SENT", "SENT"))
        self.assertEqual(len(p.fake.bot_messages()), 1)

    def test_absence_proven_twice_then_reclaimed(self):
        nid = self.notify()
        p = self.lam()
        p.fake.fail_post = ["500"]
        p.cycle()
        self.assertEqual(self.delivery(nid)["status"], "UNKNOWN")
        p.at(T0 + timedelta(minutes=31)).cycle()
        self.assertEqual((self.delivery(nid)["status"], self.delivery(nid)["absent_count"]), ("UNKNOWN", 1), "한 번으론 확정 안 함")
        p.at(T0 + timedelta(minutes=42)).cycle()
        self.assertEqual((self.delivery(nid)["status"], self.notif(nid)["retry_count"]), ("FAILED", 1))
        self.age_attempts()
        out, applied = p.at(T0 + timedelta(minutes=44)).cycle()
        self.assertEqual((out["claimed"], self.notif(nid)["status"]), (1, "SENT"))
        self.assertEqual(len(p.fake.bot_messages()), 1)

    def test_page_overflow_and_lookup_failure_never_resend(self):
        nid = self.notify()
        p = self.lam()
        p.fake.fail_post = ["500"]
        p.cycle()
        p.fake.seed_user_messages(301, T0 + timedelta(seconds=5))     # 조회 범위(3페이지 x 100) 밖으로 밀림
        p.at(T0 + timedelta(minutes=31)).cycle()
        self.assertEqual((p.results[-1]["outcome"], self.delivery(nid)["status"], self.delivery(nid)["absent_count"]),
                         ("INCONCLUSIVE", "UNKNOWN", 0))
        p.fake.fail_get = 10                                             # 메시지 조회 실패
        p.at(T0 + timedelta(minutes=41)).relay()
        out = p.run_worker()
        self.assertEqual(len(out["batchItemFailures"]), 1, "판단 보류: 결과 없이 큐가 재전달")
        self.assertEqual(p.apply_results(), [])
        self.assertEqual((self.delivery(nid)["status"], len(p.fake.bot_messages())), ("UNKNOWN", 0))
        self.assertEqual(len([b for _, b in p.fake.posts if b.get("embeds")]), 1, "최초 1회 시도 외 재발송 없음")

    def test_unverifiable_closed_as_failed_without_resend(self):
        nid = self.notify()
        p = self.lam()
        p.fake.fail_post = ["store500"]
        p.fake.hide_history = True                                      # 실제로는 저장됐지만 확인할 수 없음
        p.fake.now = T0 + timedelta(seconds=5)
        p.relay()
        p.run_worker()
        p.apply_results()
        self.assertEqual(self.delivery(nid)["status"], "UNKNOWN")
        moment = T0 + timedelta(minutes=31)
        for _ in range(6):
            p.at(moment).cycle()
            moment += timedelta(minutes=10)
        self.assertEqual((self.delivery(nid)["verify_count"], self.notif(nid)["status"]), (6, "PENDING"))
        with self.assertLogs("dm_share", level="WARNING") as logs:
            out, _ = p.at(moment).cycle()
        self.assertEqual(out["recover"]["finalized_unknown"], 1)
        self.assertTrue(any("확인 한도 초과" in line for line in logs.output))
        self.assertEqual((self.notif(nid)["status"], self.notif(nid)["retry_count"]), ("FAILED", 1))
        self.assertEqual(p.at(moment + timedelta(hours=1)).cycle()[0]["claimed"], 0)
        self.assertEqual(len([b for _, b in p.fake.posts if b.get("embeds")]), 1, "재발송 없음")


# -- Discord 오류 분류 ---------------------------------------------------------------------------------------------
class ErrorTests(PgCase):
    def test_403_429_5xx_and_unknown_user(self):
        blocked, other403, gone_send, gone_open = (self.notify() for _ in range(4))
        p = self.lam(relay_limit=1)
        p.fake.fail_post = ["403:50007"]
        p.cycle()
        self.assertEqual((self.notif(blocked)["status"], self.notif(blocked)["retry_count"], self.notif(blocked)["error_message"]),
                         ("FAILED", 1, "DM 수신 차단 (403)"), "50007은 즉시 FAILED")
        p.fake.fail_post = ["403:50001"]
        p.cycle()
        self.assertEqual((self.notif(other403)["status"], self.notif(other403)["retry_count"]), ("PENDING", 1), "다른 403은 재시도")
        p.fake.fail_post = ["400:50033"]
        p.cycle()
        self.assertEqual((self.notif(gone_send)["status"], self.notif(gone_send)["error_message"]), ("SKIPPED", "Discord 사용자 없음"))
        self.admin.execute("UPDATE members SET discord_id = '999999999999999999' WHERE member_id = 3")
        self.admin.execute("UPDATE notifications SET receiver_member_id = 3 WHERE notification_id = %s", (gone_open,))
        p.fake.fail_open[999999999999999999] = (404, 10013)
        p.cycle()
        self.assertEqual((self.notif(gone_open)["status"], self.notif(gone_open)["error_message"]), ("SKIPPED", "Discord 사용자 없음"))
        self.assertEqual(p.fake.bot_messages(), [])

    def test_retry_count_three_429s_then_failed(self):
        nid = self.notify()
        p = self.lam()
        moment = T0
        for attempt in range(1, 4):
            p.fake.fail_post = ["429"]
            out, _ = p.at(moment).cycle()
            self.assertEqual(out["claimed"], 1, attempt)
            self.age_attempts()
            moment += timedelta(seconds=61)
        self.assertEqual((self.notif(nid)["status"], self.notif(nid)["retry_count"]), ("FAILED", 3))
        self.assertIsNone(self.delivery(nid)["next_retry_at"])
        self.assertEqual(p.at(moment + timedelta(hours=1)).cycle()[0]["claimed"], 0)


# -- 알림 OFF·탈퇴 -------------------------------------------------------------------------------------------------
class OptOutAndWithdrawalTests(PgCase):
    @contextmanager
    def backend_cursor(self, commit=False, **_):
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(DSN, application_name="dm_withdraw", options="-c TimeZone=Asia/Seoul")
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                yield cur
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def withdraw(self, member_id=RECEIVER, discord_id=str(RECEIVER_DISCORD)):
        sys.path.insert(0, str(REPO / "backend"))
        from app.services import member_service
        original = member_service.db_cursor
        member_service.db_cursor = self.backend_cursor
        try:
            return member_service.withdraw_member(member_id, discord_id)
        finally:
            member_service.db_cursor = original

    def test_opt_out_before_reclaim_is_skipped(self):
        nid = self.notify()
        p = self.lam()
        p.fake.fail_post = ["429"]
        p.cycle()
        self.admin.execute("UPDATE members SET external_dm_opt_in = FALSE WHERE member_id = %s", (RECEIVER,))
        self.age_attempts()
        self.assertEqual(p.at(T0 + timedelta(seconds=61)).cycle()[0]["claimed"], 0)
        self.assertEqual((self.notif(nid)["status"], self.notif(nid)["error_message"]), ("SKIPPED", "DM 알림 꺼짐"))
        self.assertEqual(p.fake.bot_messages(), [])

    def test_withdraw_sql_cascades_and_late_result_is_warned(self):
        """남은 위험 재현: 큐에 들어간 작업은 탈퇴 후에도 TTL 안에 전송될 수 있다. 결과는 경고로 남긴다."""
        nid = self.notify()
        p = self.lam()
        p.relay()
        self.assertTrue(self.withdraw(), "탈퇴가 FK 때문에 실패하지 않음")
        self.assertEqual((self.notif(nid), self.delivery(nid)), (None, None), "notifications 삭제 + CASCADE")
        p.run_worker()
        self.assertEqual(len(p.fake.bot_messages()), 1, "이미 큐에 있던 작업은 전송됨 (남은 위험)")
        with self.assertLogs("dm_share", level="WARNING") as logs:
            self.assertEqual(p.apply_results(), ["missing_notification"])
        self.assertIn("탈퇴 등으로 삭제", logs.output[0])

    def test_withdraw_racing_claim_both_succeed(self):
        n1, n2 = self.notify(), self.notify()
        holder = self.psycopg.connect(DSN)            # 선점의 INSERT를 멈춰 세워 탈퇴와 겹치게 한다
        self._extra.append(holder)
        holder.execute(f"LOCK TABLE {dmr.TABLE} IN SHARE MODE")
        repo, out = self.repo("dm_claim_race"), {}
        tc = threading.Thread(target=lambda: out.setdefault("claim", repo.claim("LAMBDA", T0, limit=10, stale_seconds=600)))
        tc.start()
        self.wait_until_waiting("dm_claim_race")      # 선점: notifications 행 잠금 후 INSERT에서 대기
        tw = threading.Thread(target=lambda: out.setdefault("withdraw", self.withdraw()))
        tw.start()
        self.wait_until_waiting("dm_withdraw")        # 탈퇴: 선점이 잡은 notifications 행을 기다림
        holder.rollback()
        tc.join(15)
        tw.join(15)
        self.assertEqual(sorted(c["notification"]["notification_id"] for c in out["claim"]), [n1, n2])
        self.assertTrue(out["withdraw"])
        self.assertEqual(self.admin.execute(f"SELECT COUNT(*) FROM {dmr.TABLE}").fetchone()[0], 0, "CASCADE")

    def test_fk_violation_skips_only_that_row(self):
        nid = self.notify()
        repo = self.repo()
        ghost = notification_row(nid=987654)
        real = notification_row(nid=nid)

        def work(cur):
            return [repo._claim_row(cur, ghost, "LAMBDA", T0, 600), repo._claim_row(cur, real, "LAMBDA", T0, 600)]
        with self.assertLogs("dm_share", level="WARNING") as logs:
            tokens = repo._db.transaction(work)
        self.assertIsNone(tokens[0])
        self.assertIsNotNone(tokens[1])
        self.assertIn("선점 중 알림이 삭제됨", logs.output[0])
        self.assertEqual(self.delivery(nid)["claim_token"], tokens[1], "같은 트랜잭션의 다른 행은 커밋됨")


# -- 컷오버·롤백 ---------------------------------------------------------------------------------------------------
class CutoverTests(PgCase):
    def test_rollback_gateway_never_sends_lambda_inflight(self):
        inflight, unknown, proven_failed = self.notify(), self.notify(), self.notify()
        p = self.lam(relay_limit=3)
        p.fake.fail_post = ["ok", "500", "429"]
        p.relay()
        jobs = p.queue.bodies(SEND_Q)
        self.assertEqual(len(jobs), 3)
        p.queue.messages = [(SEND_Q, jobs[1]), (SEND_Q, jobs[2])]  # 첫 작업은 아직 큐에 있음(진행 중)
        p.fake.fail_post = ["500", "429"]
        p.run_worker()
        p.apply_results()
        self.assertEqual([self.delivery(n)["status"] for n in (inflight, unknown, proven_failed)], ["PENDING", "UNKNOWN", "FAILED"])
        # 롤백: Lambda 신규 선점 중지, Gateway 재개 (결과 처리·복구는 계속). Gateway는 실제 시계를 쓰므로 60초 경과를 만든다.
        self.age_attempts()
        self.age_retry()
        service, client = self.gateway()
        run(service.poll_once())
        self.assertEqual(client.sent, [], "R4: Lambda 선점 후 16분 전에는 Gateway가 Lambda의 FAILED도 이어받지 않음")
        self.age_claims(16)
        self.age_attempts()
        run(service.poll_once())
        self.assertEqual([d for d, _ in client.sent], [RECEIVER_DISCORD], "16분 뒤 미전송이 확실한 FAILED만 Gateway가 이어받음")
        self.assertEqual(self.delivery(proven_failed)["sender"], "GATEWAY")
        p.queue.send(SEND_Q, jobs[0])
        p.run_worker()
        p.apply_results()
        p.at(T0 + timedelta(minutes=31)).service.recover(T0 + timedelta(minutes=31))
        p.run_worker()
        p.apply_results()
        statuses = {n: self.notif(n)["status"] for n in (inflight, unknown, proven_failed)}
        self.assertEqual(statuses[inflight], "SENT")
        self.assertEqual(statuses[proven_failed], "SENT")
        self.assertEqual(self.delivery(unknown)["status"], "UNKNOWN", "불명 건은 Gateway도 Lambda도 재발송하지 않음")
        self.assertEqual(len(p.fake.bot_messages()) + len(client.sent), 2)

    def test_recover_action_finishes_inflight_without_new_claims(self):
        """롤백 중 dm_recover: 신규 알림은 선점하지 않고, 불명 건의 마커 확인만 한다."""
        unknown = self.notify()
        p = self.lam()
        p.fake.fail_post = ["late500"]
        p.cycle()
        fresh = self.notify()                                   # 롤백 뒤 새로 생긴 알림
        p.fake.release_delayed(T0 + timedelta(seconds=10))
        p.at(T0 + timedelta(minutes=31))
        out = p.service.recover(p.clock)                         # 핸들러는 실제 시계를 쓰므로 시각은 서비스로 직접 준다
        self.assertEqual((out["verify_jobs"], self.delivery(fresh)), (1, None), "신규 선점 없음")
        calls = []
        stub = SimpleNamespace(recover=lambda now: calls.append("recover") or {}, relay=lambda now: calls.append("relay"))
        db_lambda.handler({"action": "dm_recover"}, service=stub)
        self.assertEqual(calls, ["recover"], "dm_recover는 relay(신규 선점)를 부르지 않음")
        p.run_worker()
        p.apply_results()
        self.assertEqual((self.notif(unknown)["status"], self.notif(fresh)["status"]), ("SENT", "PENDING"))
        self.assertEqual(len(p.fake.bot_messages()), 1)

    def test_summary(self):
        self.notify()
        p = self.lam()
        p.cycle()
        out = db_lambda.handler({"action": "dm_summary"}, service=p.service)
        self.assertEqual((out["LAMBDA:SENT"], out["notifications_pending"]), (1, 0))


# -- R4: Gateway·Lambda 교차 재선점 중 진행 중 요청 ---------------------------------------------------------------
class R4CrossReclaimTests(PgCase):
    """Lambda 실패(429) -> 같은 작업의 SQS 복사본이 처리되는 동안 다른 쪽이 재선점하는 상황."""

    def failed_lambda(self, ttl):
        nid = self.notify()
        p = self.lam(job_ttl_seconds=ttl)
        p.fake.fail_post = ["429"]
        p.relay()
        body = p.queue.bodies(SEND_Q)[0]
        p.run_worker()
        p.apply_results()                                     # 복사본 A: 429 -> FAILED_RETRY, next_retry = +60초
        self.assertEqual((self.delivery(nid)["status"], self.notif(nid)["retry_count"]), ("FAILED", 1))
        return nid, p, body

    def prod_worker(self, p, hook):
        """운영 _build와 같은 재시도 설정(max_retries=3)의 클라이언트. 429 대기(sleep) 중에 hook이 실행된다."""
        return DmShareWorker(DiscordRestClient(TOKEN, base_url=p.fake.url, timeout=3.0, sleep=hook), clock=lambda: p.clock)

    def gateway_text_into_channel(self, p, client, at):
        """Gateway 텍스트 DM도 같은 DM 채널에 (마커 없이) 남는다."""
        if not client.sent:
            return
        with p.fake.lock:
            p.fake.seq += 1
            p.fake.messages.setdefault(p.fake.channel_of(RECEIVER_DISCORD), []).append(
                {"id": str(cs.snowflake(at, p.fake.seq)), "timestamp": at.isoformat(), "content": client.sent[0][1],
                 "embeds": [], "author": {"id": "9", "bot": True}})

    def gateway_takes_over(self, p, takeover, at):
        self.age_attempts()
        self.age_retry()
        service, client = self.gateway(takeover=takeover)
        run(service.poll_once())
        self.gateway_text_into_channel(p, client, at)
        return client

    def embeds(self, p):
        return len([m for m in p.fake.bot_messages() if m.get("embeds")])

    def test_before_fix_ttl90_duplicate_reproduced(self):
        """수정 전 재현(16분 제한 없음 = takeover 0분, TTL 90초): 텍스트 1 + embed 1."""
        nid, p, body = self.failed_lambda(90)
        client = self.gateway_takes_over(p, 0, T0 + timedelta(seconds=61))
        p.at(T0 + timedelta(seconds=70))
        p.queue.send(SEND_Q, body)                            # TTL 안에 같은 작업의 SQS 중복 복사본
        p.run_worker(receive_count=2)
        self.assertEqual(p.apply_results(), ["ignored"], "이전 토큰 결과는 무시")
        self.assertEqual((len(client.sent), self.embeds(p)), (1, 1), "수정 전: 같은 알림 2회 (R4 재현)")

    def inflight_b(self, p, body, on_wait):
        """복사본 B가 만료 1초 전(49초)에 시작해 POST가 429를 받고, 클라이언트 대기 중 on_wait가 실행된 뒤 성공한다."""
        p.at(T0 + timedelta(seconds=49))
        p.fake.fail_post = ["429"]

        def hook(seconds):
            p.at(T0 + timedelta(seconds=75))                   # 대기 동안 시간이 흘러 TTL(50초)과 재시도 간격(60초)을 넘김
            on_wait()
        return self.prod_worker(p, hook).process(contract.loads(body), receive_count=1)

    def test_before_fix_ttl50_alone_still_duplicates_inflight(self):
        """TTL 50초만 적용(takeover 0분): 만료 직전 시작된 POST의 429 재시도가 재선점 뒤 성공 -> 중복."""
        nid, p, body = self.failed_lambda(50)
        holder = {}
        result = self.inflight_b(p, body, lambda: holder.setdefault(
            "c", self.gateway_takes_over(p, 0, T0 + timedelta(seconds=70))))
        self.assertEqual(result["outcome"], "SENT")
        self.assertEqual((len(holder["c"].sent), self.embeds(p)), (1, 1), "TTL 단독으로는 진행 중 요청을 막지 못함")

    def test_fixed_same_inflight_scenario_sends_once(self):
        nid, p, body = self.failed_lambda(50)
        holder = {}
        result = self.inflight_b(p, body, lambda: holder.setdefault("c", self.gateway_takes_over(
            p, dmr.GATEWAY_TAKEOVER_MINUTES, T0 + timedelta(seconds=70))))
        self.assertEqual(holder["c"].sent, [], "16분 전이라 Gateway가 이어받지 않음")
        self.assertEqual(result["outcome"], "SENT")
        self.assertEqual(p.service.apply_result(contract.dumps(result), p.clock), "applied", "같은 토큰이라 반영됨")
        self.assertEqual((self.notif(nid)["status"], self.embeds(p)), ("SENT", 1))

    def test_fixed_duplicate_copy_after_ttl_not_sent(self):
        """TTL 90초 재현과 같은 순서(복사본이 70초에 도착)를 수정 후 설정으로: 복사본은 만료, Gateway는 16분 대기."""
        nid, p, body = self.failed_lambda(50)
        client = self.gateway_takes_over(p, dmr.GATEWAY_TAKEOVER_MINUTES, T0 + timedelta(seconds=61))
        p.at(T0 + timedelta(seconds=70))
        p.queue.send(SEND_Q, body)
        p.run_worker(receive_count=2)
        self.assertEqual((p.results[-1]["outcome"], client.sent, self.embeds(p)), ("UNKNOWN", [], 0))
        self.assertEqual(p.apply_results(), ["duplicate"], "FAILED 행에 늦은 UNKNOWN은 반영하지 않음")
        self.assertEqual(p.at(T0 + timedelta(seconds=75)).cycle()[0]["claimed"], 1, "Lambda->Lambda 60초 재시도는 유지")
        self.assertEqual((self.notif(nid)["status"], self.embeds(p)), ("SENT", 1))

    def test_gateway_takeover_only_after_16_minutes(self):
        nid, p, body = self.failed_lambda(50)
        self.age_attempts()
        self.age_retry()
        gateway_repo = self.repo("g")
        self.assertEqual(gateway_repo.claim("GATEWAY", datetime.now(UTC), limit=5, stale_seconds=600), [])
        token = gateway_repo._db.transaction(lambda cur: gateway_repo._claim_row(
            cur, notification_row(nid=nid), "GATEWAY", datetime.now(UTC), 600))
        self.assertIsNone(token, "후보 SQL을 거치지 않아도 UPSERT가 16분 전 인수를 막음")
        self.age_claims(15)
        self.assertEqual(gateway_repo.claim("GATEWAY", datetime.now(UTC), limit=5, stale_seconds=600), [], "15분: 아직")
        self.age_claims(1)
        claims = gateway_repo.claim("GATEWAY", datetime.now(UTC), limit=5, stale_seconds=600)
        self.assertEqual([c["notification"]["notification_id"] for c in claims], [nid], "16분: 허용")
        self.assertEqual(self.delivery(nid)["sender"], "GATEWAY")

    def test_lambda_reclaim_during_inflight_is_safe_with_concurrency_1(self):
        nid, p, body = self.failed_lambda(50)
        new = {}
        p.at(T0 + timedelta(seconds=49))
        p.fake.fail_post = ["429"]

        def hook(seconds):
            p.at(T0 + timedelta(seconds=75))
            self.age_attempts()
            p.queue.messages.clear()
            p.relay()                                            # 60초 뒤 Lambda가 재선점 (새 토큰)
            new["body"] = p.queue.bodies(SEND_Q)[0]
        worker = self.prod_worker(p, hook)
        b = worker.process(contract.loads(body), receive_count=1)
        c = worker.process(contract.loads(new["body"]), receive_count=1)   # 예약 동시성 1: B가 끝난 뒤 같은 Worker가 처리
        self.assertEqual((b["outcome"], c["outcome"], self.embeds(p)), ("SENT", "SENT", 1), "새 작업은 마커로 막힘")
        self.assertEqual(p.service.apply_result(contract.dumps(b), p.clock), "ignored", "이전 토큰")
        self.assertEqual(p.service.apply_result(contract.dumps(c), p.clock), "applied")
        self.assertEqual(self.notif(nid)["status"], "SENT")

    def test_pre_post_expiry_check(self):
        """사전 조회가 429로 늦어져 POST 직전에 만료되면 보내지 않는다."""
        self.notify()
        p = self.lam()
        p.relay()
        p.fake.fail_get, p.fake.fail_get_status = 1, 429

        def hook(seconds):
            p.at(T0 + timedelta(seconds=55))                     # 조회 대기 중 TTL(50초) 경과
        result = self.prod_worker(p, hook).process(p.jobs()[0], receive_count=1)
        self.assertEqual(result["outcome"], "EXPIRED")
        self.assertEqual([b for _, b in p.fake.posts if b.get("embeds")], [], "POST 0회")


# -- R5: Discord 401 인증 차단기 ------------------------------------------------------------------------------------
class R5AuthBreakerTests(PgCase):
    def blocked(self, count=3):
        ids = [self.notify() for _ in range(count)]
        p = self.lam()
        p.fake.fail_post = ["401:0"] * count
        with self.assertLogs("dm_share", level="ERROR"):
            p.cycle()
        return ids, p

    def test_401_does_not_count_and_blocks_new_claims(self):
        ids, p = self.blocked()
        self.assertEqual({(self.notif(n)["status"], self.notif(n)["retry_count"]) for n in ids}, {("PENDING", 0)})
        self.assertEqual({self.delivery(n)["error_message"][:16] for n in ids}, {dmr.AUTH_MARK})
        fresh = self.notify()
        self.age_retry()
        with self.assertLogs("dm_share", level="ERROR"):
            out, _ = p.at(T0 + timedelta(minutes=5)).cycle()
        self.assertEqual((out["claimed"], out["auth_breaker"], out["recover"].get("paused_auth")), (0, "BLOCKED", True))
        self.assertIsNone(self.delivery(fresh), "차단 중 신규 알림도 선점하지 않음")
        self.assertEqual(len(p.fake.posts), 3, "차단 뒤 Discord 요청 없음")

    def test_probe_only_after_10_minutes_and_only_one(self):
        ids, p = self.blocked()
        self.age_retry()
        self.age_auth(9)
        self.assertEqual(p.at(T0 + timedelta(minutes=9)).relay()["claimed"], 0, "10분 전 시험 0건")
        self.age_auth(2)
        p.queue.messages.clear()
        out = p.at(T0 + timedelta(minutes=11)).relay()
        self.assertEqual((out["claimed"], out["auth_breaker"]), (1, "PROBE"))
        probe = p.jobs()[0]["unit_id"]
        self.assertEqual(self.delivery(int(probe[3:]))["error_message"], dmr.AUTH_PROBE)
        self.assertEqual(p.at(T0 + timedelta(minutes=12)).relay()["claimed"], 0, "시험 진행 중에는 추가 선점 없음")

    def test_concurrent_relays_pass_single_probe(self):
        ids, p = self.blocked()
        self.age_retry()
        self.age_auth(11)
        repos = [self.repo(f"dm_probe{i}") for i in range(4)]
        for r in repos:
            r.available()
        barrier, out = threading.Barrier(4), [None] * 4

        def go(i):
            barrier.wait()
            out[i] = repos[i].claim("LAMBDA", T0 + timedelta(minutes=11), limit=20, stale_seconds=600)
        threads = [threading.Thread(target=go, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(15)
        self.assertEqual(sum(len(o) for o in out), 1, "동시 실행에서도 시험 선점은 1건")

    def test_probe_failure_reblocks_and_recovery_sends_all_once(self):
        ids, p = self.blocked()
        self.age_retry()
        self.age_auth(11)
        p.fake.fail_post = ["401:0"]
        with self.assertLogs("dm_share", level="ERROR"):
            out, _ = p.at(T0 + timedelta(minutes=11)).cycle()   # 시험 실패
        self.assertEqual(out["claimed"], 1)
        self.age_retry()
        self.assertEqual(p.at(T0 + timedelta(minutes=12)).relay()["claimed"], 0, "시험 실패 -> 다시 차단")
        self.assertEqual({self.notif(n)["retry_count"] for n in ids}, {0})
        self.age_auth(11)
        p.queue.messages.clear()
        out, _ = p.at(T0 + timedelta(minutes=23)).cycle()      # 시험 성공 -> 인증 표시 해제
        self.assertEqual((out["claimed"], out["auth_breaker"]), (1, "PROBE"))
        self.assertFalse(p.repo.auth_open())
        self.age_retry()
        out, _ = p.at(T0 + timedelta(minutes=24)).cycle()
        self.assertEqual(out["claimed"], 2, "복구 후 나머지 대기 알림 정상 선점")
        self.assertEqual({self.notif(n)["status"] for n in ids}, {"SENT"})
        self.assertEqual(sorted(p.fake.markers()), sorted(f"ref:dm-{n}" for n in ids), "알림마다 1회")
        self.assertEqual({self.notif(n)["retry_count"] for n in ids}, {0})

    def test_unknown_verify_401_preserves_state_and_resumes_after_recovery(self):
        unknown = self.notify()
        p = self.lam()
        p.fake.fail_post = ["500"]
        p.cycle()
        p.at(T0 + timedelta(minutes=31)).cycle()                 # 확인 1회: 미전송 1회 기록
        before = self.delivery(unknown)
        self.assertEqual((before["status"], before["absent_count"], before["verify_count"]), ("UNKNOWN", 1, 1))
        p.fake.fail_open[RECEIVER_DISCORD] = (401, 0)            # 다음 확인 작업에서 401
        p.at(T0 + timedelta(minutes=42)).relay()
        out = p.run_worker()
        self.assertEqual(out["batchItemFailures"], [])
        bodies = p.queue.bodies(RESULT_Q)
        with self.assertLogs("dm_share", level="ERROR"):
            self.assertEqual(p.apply_results(), ["auth_hold"])
        for body in bodies:                                      # 같은 결과 중복 도착
            self.assertEqual(p.service.apply_result(body, p.clock), "duplicate")
        row = self.delivery(unknown)
        self.assertEqual((row["status"], row["absent_count"], row["verify_count"]), ("UNKNOWN", 1, 1),
                         "401 때문에 상태·absent_count·verify_count가 바뀌지 않음")
        self.assertEqual(self.notif(unknown)["status"], "PENDING")
        recover = p.at(T0 + timedelta(minutes=60)).service.recover(p.clock)
        self.assertTrue(recover.get("paused_auth"), "인증 장애 중 확인·마감 중지")
        # 인증 복구: 다른 알림으로 시험 발송 성공
        del p.fake.fail_open[RECEIVER_DISCORD]
        probe = self.notify()
        self.age_auth(11)
        p.queue.messages.clear()
        p.at(T0 + timedelta(minutes=61)).cycle()
        self.assertEqual(self.notif(probe)["status"], "SENT")
        self.assertFalse(p.repo.auth_open())
        out = p.at(T0 + timedelta(minutes=72)).service.recover(p.clock)
        self.assertEqual(out["verify_jobs"], 1, "복구 후 UNKNOWN 마커 확인 재개")
        p.run_worker()
        p.apply_results()
        self.assertEqual(self.delivery(unknown)["status"], "FAILED", "두 번째 미전송 증명 뒤에만 재선점 대상")

    def test_redelivered_send_with_lookup_401_becomes_unknown_not_failed(self):
        nid = self.notify()
        p = self.lam()
        p.relay()
        p.fake.fail_get, p.fake.fail_get_status = 5, 401
        p.run_worker(receive_count=2)
        with self.assertLogs("dm_share", level="ERROR"):
            self.assertEqual(p.apply_results(), ["auth_unknown"])
        self.assertEqual((self.delivery(nid)["status"], self.notif(nid)["retry_count"]), ("UNKNOWN", 0))
        self.assertEqual([b for _, b in p.fake.posts if b.get("embeds")], [], "POST 0회")

    def test_auth_outage_over_24h_never_auto_fails(self):
        ids, p = self.blocked(2)
        self.admin.execute(f"UPDATE {dmr.TABLE} SET verify_count = 6, status = 'UNKNOWN', last_verified_at = claimed_at "
                           "WHERE notification_id = %s", (ids[0],))         # 확인 한도에 이른 UNKNOWN도 있음
        self.age_auth(25 * 60)
        self.age_retry()
        p.fake.fail_post = ["401:0"]
        with self.assertLogs("dm_share", level="ERROR") as logs:
            out, _ = p.at(T0 + timedelta(hours=25)).cycle()
        self.assertTrue(any("24시간 이상" in line for line in logs.output), "24시간 경보")
        self.assertEqual(out["claimed"], 1, "시험 1건은 계속")
        self.assertTrue(out["recover"].get("paused_auth"))
        self.assertEqual({self.notif(n)["status"] for n in ids}, {"PENDING"}, "자동 FAILED·삭제 없음")
        self.assertEqual({self.notif(n)["retry_count"] for n in ids}, {0})

    def test_probe_result_lost_keeps_claims_blocked(self):
        ids, p = self.blocked()
        self.age_retry()
        self.age_auth(11)
        p.at(T0 + timedelta(minutes=11)).relay()
        p.queue.messages.clear()                                 # 시험 작업 유실
        out = p.at(T0 + timedelta(minutes=22)).service.recover(p.clock)   # 선점 만료(10분) -> UNKNOWN, 표시 유지
        self.assertTrue(out.get("paused_auth"))
        lost = [n for n in ids if self.delivery(n)["status"] == "UNKNOWN"]
        self.assertEqual(len(lost), 1)
        self.assertTrue(self.delivery(lost[0])["error_message"].startswith(dmr.AUTH_MARK))
        self.age_retry()
        with self.assertLogs("dm_share", level="ERROR"):
            self.assertEqual(p.at(T0 + timedelta(minutes=23)).relay()["claimed"], 0, "유실된 시험 직후 다시 10분 차단")


if __name__ == "__main__":
    unittest.main(verbosity=1)
