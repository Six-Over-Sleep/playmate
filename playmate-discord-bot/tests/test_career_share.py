"""취업 게시글 Discord 공유(career_share, Issue #163) 테스트.

실제 Discord/AWS/공용 DB에는 접속하지 않는다. 127.0.0.1의 상태를 가진 가짜 Discord HTTP 서버와 메모리 SQS를 쓴다.
같은 시나리오를 메모리 저장소로 항상 실행하고, 일회용 PostgreSQL이 있을 때(PLAYMATE_TEST_PG_DSN, localhost만)는
실제 SQL(013 + 048 마이그레이션)로도 실행한다 (없으면 해당 클래스는 SKIP = 미실시).
실행: python -m pytest tests/test_career_share.py
"""
import json
import os
import socket
import subprocess
import sys
import threading
import unittest
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from career_share import contract, db_lambda, messages, policy, settings, state, worker_lambda  # noqa: E402
from career_share.queues import FakeQueue  # noqa: E402
from career_share.repository import InMemoryCareerShareRepository  # noqa: E402
from career_share.service import CareerShareService, digest_date  # noqa: E402
from career_share.worker import CareerShareWorker  # noqa: E402
from discord_rest import DiscordRestClient  # noqa: E402

UTC, KST = timezone.utc, timezone(timedelta(hours=9))
TOKEN = "SECRET-TOKEN-do-not-log.abc123"
CHANNEL = 444444444444444444
BASE = "https://playmate.example.com"
SEND_Q, RESULT_Q = "queue://send", "queue://result"
CUTOVER = datetime(2026, 12, 1, 0, 0, tzinfo=KST)          # = 2026-11-30T15:00Z
T0 = datetime(2026, 12, 1, 12, 0, tzinfo=UTC)               # 컷오버 이후
DSN = os.environ.get("PLAYMATE_TEST_PG_DSN")

# -- 외부 접속 차단: loopback 외 호스트로 이름 조회/연결을 시도하면 즉시 실패 ---------------------------------------
_LOOPBACK, _BLOCKED, _patches = {"127.0.0.1", "localhost", "::1"}, [], []
_real_getaddrinfo, _real_connect = socket.getaddrinfo, socket.socket.connect


def _guard_getaddrinfo(host, *a, **k):
    if str(host).strip("[]") not in _LOOPBACK:
        _BLOCKED.append(str(host))
        raise AssertionError(f"외부 호스트 이름 조회 차단: {host}")
    return _real_getaddrinfo(host, *a, **k)


def _guard_connect(self, address):
    host = address[0] if isinstance(address, tuple) else address
    if str(host).strip("[]") not in _LOOPBACK:
        _BLOCKED.append(str(host))
        raise AssertionError(f"외부 호스트 연결 차단: {host}")
    return _real_connect(self, address)


def setUpModule():
    for patcher in (mock.patch("socket.getaddrinfo", _guard_getaddrinfo), mock.patch("socket.socket.connect", _guard_connect)):
        patcher.start()
        _patches.append(patcher)


def tearDownModule():
    while _patches:
        _patches.pop().stop()
    assert not _BLOCKED, f"외부 호스트 접속 시도: {_BLOCKED}"


# -- 상태를 가진 가짜 Discord ---------------------------------------------------------------------------------------
def snowflake(moment: datetime, seq: int) -> int:
    return (int(moment.timestamp() * 1000) - 1420070400000) << 22 | (seq & 0x3FFFFF)


class StatefulDiscord:
    """POST로 메시지를 저장하고 GET으로 최신순 목록을 돌려준다. fail_post: 다음 POST들의 동작 ('500', 'store500', '401', ...)."""

    def __init__(self):
        self.messages, self.posts, self.gets, self.fail_post = [], [], 0, []
        self.delayed = []   # late500: 클라이언트에는 5xx를 줬지만 서버가 뒤늦게 저장할 메시지
        self.hide_history = False
        self.seeded_markers = 0
        self.now = T0
        self.seq = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                with outer.lock:
                    outer.posts.append(body)
                    mode = outer.fail_post.pop(0) if outer.fail_post else "ok"
                    if mode in ("ok", "store500", "storetimeout", "late500"):
                        outer.seq += 1
                        message = dict(body, id=str(snowflake(outer.now, outer.seq)), timestamp=outer.now.isoformat(),
                                       author={"id": "9", "bot": True})
                        (outer.delayed if mode == "late500" else outer.messages).append(message)
                    if mode == "ok":
                        return self._send(200, message)
                    if mode in ("500", "store500", "late500"):
                        return self._send(500, {"message": "boom"})
                    if mode == "429":
                        self.send_response(429)
                        data = json.dumps({"message": "rate", "retry_after": 0.01, "global": False}).encode()
                        self.send_header("Content-Length", str(len(data)))
                        self.send_header("Retry-After", "0.01")
                        self.end_headers()
                        return self.wfile.write(data)
                    return self._send(int(mode), {"message": "err", "code": 50013})

            def do_GET(self):
                path, _, query = self.path.partition("?")
                params = dict(p.split("=") for p in query.split("&") if p)
                with outer.lock:
                    outer.gets += 1
                    if path.endswith("/messages"):
                        items = [] if outer.hide_history else sorted(outer.messages, key=lambda m: int(m["id"]), reverse=True)
                        if "before" in params:
                            items = [m for m in items if int(m["id"]) < int(params["before"])]
                        return self._send(200, items[:int(params.get("limit", 50))])
                    last = max((int(m["id"]) for m in outer.messages), default=None)
                    return self._send(200, {"id": str(CHANNEL), "last_message_id": None if last is None else str(last)})

        self.lock = threading.RLock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_port}/api/v10"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def release_delayed(self, moment: datetime):
        """클라이언트 타임아웃/5xx 뒤에 서버가 뒤늦게 메시지를 저장한 상황 (저장 시각 = moment)."""
        with self.lock:
            for message in self.delayed:
                self.seq += 1
                message.update(id=str(snowflake(moment, self.seq)), timestamp=moment.isoformat())
                self.messages.append(message)
            self.delayed = []

    def seed(self, moment: datetime, footer=None):
        """과거 메시지를 심는다 (미전송 증명이 닿아야 할 '이전 메시지')."""
        with self.lock:
            self.seeded_markers += 1 if footer else 0
            self.seq += 1
            self.messages.append({"id": str(snowflake(moment, self.seq)), "timestamp": moment.isoformat(),
                                  "content": "old", "embeds": [{"footer": {"text": footer}}] if footer else [], "author": {"id": "1"}})

    def count_posts(self):
        """우리가 보낸 메시지 수 (심어 둔 이전 메시지는 제외)."""
        return sum(1 for m in self.messages if str(((m.get("embeds") or [{}])[0].get("footer") or {}).get("text", "")).startswith("ref:post-")
                   or str(((m.get("embeds") or [{}])[0].get("footer") or {}).get("text", "")).startswith("ref:digest-")) - self.seeded_markers

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def make_settings(**over) -> settings.DbSettings:
    values = dict(send_queue_url=SEND_Q, base_url=BASE, cutover_at=CUTOVER.astimezone(UTC), relay_limit=20, digest_limit=5,
                  max_attempts=3, retry_base_minutes=5, job_ttl_minutes=10, claim_stale_minutes=30,
                  verify_interval_minutes=10, max_verifies=6, verify_settle_minutes=30, absent_required=2)
    values.update(over)
    return settings.DbSettings(**values)


# -- 저장소 하네스 (메모리 / PostgreSQL 공통) ---------------------------------------------------------------------------
class MemoryBackend:
    name = "memory"

    def __init__(self):
        self.repo = InMemoryCareerShareRepository()

    def add_post(self, pid, *, category="reviews", sub="INTERVIEW", created_at=None, title=None, process_result=None,
                 post_status="PUBLISHED", deleted=False):
        self.repo.add_post(pid, title=title or f"제목 {pid}", category=category, sub=sub, created_at=created_at or T0,
                           process_result=process_result, post_status=post_status, deleted=deleted)

    def delete_post(self, pid):
        self.repo.posts[pid]["deleted_at"] = T0

    def row(self, pid):
        return self.repo.rows.get(pid)

    def add_legacy(self, pid, status, next_retry_at=None, attempts=1):
        post = self.repo.posts[pid]
        row = self.repo._row(post, "LEGACY", status)
        row.update(attempt_count=attempts, next_retry_at=next_retry_at)
        self.repo.rows[pid] = row

    def batch_count(self):
        return len(self.repo.batches)

    def legacy_take(self, pid, now):
        """기존 18:00 공지(claim_due)가 신규 기능의 FAILED 행을 선점한 상태를 흉내 낸다 (announce_date를 채움)."""
        row = self.repo.rows[pid]
        assert row["status"] == "FAILED" and row["attempt_count"] < 3
        row.update(status="PENDING", attempt_count=row["attempt_count"] + 1, announce_date=now.astimezone(KST).date(), claimed_at=now)

    def legacy_mark_sent(self, pid):
        self.repo.rows[pid].update(status="SENT", discord_message_id="111111111111111111")

    def legacy_fail(self, pid):
        self.repo.rows[pid].update(status="FAILED")

    def close(self):
        pass


class PostgresBackend:
    name = "postgres"

    def __init__(self):
        import psycopg
        from repositories.db import Database
        from career_share.repository import PostgresCareerShareRepository
        self.psycopg = psycopg
        self.admin = psycopg.connect(DSN, autocommit=True)
        sql_dir = ROOT.parent / "database" / "sql"
        self.admin.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        self.admin.execute("""
            CREATE TABLE posts (post_id BIGINT PRIMARY KEY, post_type VARCHAR(20), post_status VARCHAR(20), title TEXT,
                                created_at TIMESTAMP NOT NULL, deleted_at TIMESTAMP);
            CREATE TABLE career (post_id BIGINT PRIMARY KEY REFERENCES posts(post_id) ON DELETE CASCADE,
                                 category_code VARCHAR(20) NOT NULL, subcategory_code VARCHAR(50) NOT NULL,
                                 details JSONB NOT NULL DEFAULT '{}'::jsonb);
            CREATE VIEW career_posts AS SELECT post_id, category_code, subcategory_code FROM career;""")
        for name in ("013_career_discord_announcements.sql", "048_career_discord_share.sql"):
            self.admin.execute((sql_dir / name).read_text(encoding="utf-8"))
        self.repo = PostgresCareerShareRepository(Database(lambda: psycopg.connect(DSN, autocommit=True)))
        self.repo_b = PostgresCareerShareRepository(Database(lambda: psycopg.connect(DSN, autocommit=True)))

    def add_post(self, pid, *, category="reviews", sub="INTERVIEW", created_at=None, title=None, process_result=None,
                 post_status="PUBLISHED", deleted=False):
        created = (created_at or T0).astimezone(UTC).replace(tzinfo=None)
        self.admin.execute("INSERT INTO posts VALUES (%s,'CAREER',%s,%s,%s,%s)",
                           (pid, post_status, title or f"제목 {pid}", created, created if deleted else None))
        self.admin.execute("INSERT INTO career VALUES (%s,%s,%s,%s)",
                           (pid, category, sub, json.dumps({"process_result": process_result} if process_result else {})))

    def delete_post(self, pid):
        self.admin.execute("UPDATE posts SET deleted_at = %s WHERE post_id = %s", (T0.replace(tzinfo=None), pid))

    def row(self, pid):
        cur = self.admin.cursor(row_factory=self.psycopg.rows.dict_row)
        cur.execute("SELECT * FROM career_discord_announcements WHERE post_id = %s", (pid,))
        row = cur.fetchone()
        if row and row["next_retry_at"] is not None:
            row["next_retry_at"] = row["next_retry_at"].replace(tzinfo=UTC)
        return row

    def add_legacy(self, pid, status, next_retry_at=None, attempts=1):
        self.admin.execute(
            "INSERT INTO career_discord_announcements (post_id, category_code, status, attempt_count, next_retry_at) "
            "SELECT post_id, category_code, %s, %s, %s FROM career WHERE post_id = %s",
            (status, attempts, next_retry_at.replace(tzinfo=None) if next_retry_at else None, pid))

    def batch_count(self):
        return self.admin.execute("SELECT COUNT(*) FROM career_discord_share_batches").fetchone()[0]

    def _legacy_repo(self):
        if getattr(self, "_legacy", None) is None:
            from repositories.career_notice_repository import PostgresCareerNoticeRepository
            from repositories.db import Database
            self._legacy = PostgresCareerNoticeRepository(Database(lambda: self.psycopg.connect(DSN, autocommit=True)))
        return self._legacy

    def legacy_take(self, pid, now):
        """실제 기존 18:00 공지 저장소(PostgresCareerNoticeRepository.claim_due)가 행을 선점한다."""
        got = self._legacy_repo().claim_due(now.astimezone(KST).date(), 5, 3, ("reviews", "lab"))
        assert [g["post_id"] for g in got] == [pid], got

    def legacy_mark_sent(self, pid):
        assert self._legacy_repo().mark_sent(pid, CHANNEL, 111111111111111111)

    def legacy_fail(self, pid):
        assert self._legacy_repo().mark_failed(pid, "legacy failure")

    def close(self):
        for repo in (self.repo, self.repo_b):
            repo._db._reset()
        if getattr(self, "_legacy", None) is not None:
            self._legacy._db._reset()
        self.admin.close()


class Pipeline:
    """DB Lambda + 메모리 SQS + Worker(가짜 Discord)를 한 곳에 묶은 시험 장치."""

    def __init__(self, backend, **settings_over):
        self.backend = backend
        self.discord = StatefulDiscord()
        self.queue = FakeQueue()
        self.settings = make_settings(**settings_over)
        self.clock = T0
        self.service = CareerShareService(backend.repo, self.queue, self.settings, clock=lambda: self.clock)
        self.sleeps = []
        self.client = DiscordRestClient(TOKEN, base_url=self.discord.url, timeout=3.0, max_retries=1,
                                        sleep=self.sleeps.append)
        self.worker = CareerShareWorker(self.client, CHANNEL, clock=lambda: self.clock)
        self.worker_results: list[dict] = []

    def at(self, moment):
        self.clock = moment
        self.discord.now = moment
        return self

    def run_worker(self, *, receive_count=1):
        """발송 큐의 작업을 모두 Worker로 처리해 결과 큐에 넣는다."""
        bodies = self.queue.bodies(SEND_Q)
        self.queue.messages = [m for m in self.queue.messages if m[0] != SEND_Q]
        for body in bodies:
            result = self.worker.process(contract.loads(body), receive_count=receive_count)
            self.worker_results.append(result)
            self.queue.send(RESULT_Q, contract.dumps(result))
        return len(bodies)

    def apply_results(self):
        outcomes = []
        bodies = self.queue.bodies(RESULT_Q)
        self.queue.messages = [m for m in self.queue.messages if m[0] != RESULT_Q]
        for body in bodies:
            outcomes.append(self.service.apply_result(body, self.clock))
        return outcomes

    def pump(self):
        self.run_worker()
        return self.apply_results()

    def close(self):
        self.discord.close()
        self.backend.close()


# ====================================================================================================================
class PolicyTests(unittest.TestCase):
    def test_allow_list_only(self):
        allowed = [("reviews", "INTERVIEW"), ("reviews", "SUCCESS"), ("reviews", "FINAL"), ("lab", "JOB_STRATEGY"),
                   ("lab", "CERTIFICATION"), ("lab", "JOB_COMPARISON")]
        for category, sub in allowed:
            self.assertIsNotNone(policy.classify(category, sub), (category, sub))
        for category, sub in [("talk", "INTERVIEW"), ("lounge", "FINAL"), ("reviews", "DOCUMENT"),
                              ("reviews", "CODING_ASSIGNMENT"), ("lab", "PORTFOLIO_FEEDBACK"), ("lab", "RESUME"),
                              ("lab", "TECH_INTERVIEW"), ("reviews", "NEW_FUTURE_CODE"), ("reviews", "interview"),
                              ("lab", None), (None, "FINAL"), ("insights", "JOB_STRATEGY")]:
            self.assertIsNone(policy.classify(category, sub), (category, sub))
        self.assertEqual(policy.kind_of("reviews", "FINAL"), policy.KIND_IMMEDIATE)
        self.assertEqual(policy.kind_of("lab", "CERTIFICATION"), policy.KIND_DIGEST)

    def test_labels_success_is_not_always_pass(self):
        self.assertEqual(policy.classify("reviews", "INTERVIEW").label, "면접 후기")
        self.assertEqual(policy.classify("reviews", "FINAL", "PASS").label, "최종 결과 후기")
        self.assertEqual(policy.classify("reviews", "SUCCESS", "PASS").label, "합격 후기")
        for result in ("FAIL", "PENDING", None, "pass", ""):
            self.assertEqual(policy.classify("reviews", "SUCCESS", result).label, "최종 결과 후기", result)


class MessageTests(unittest.TestCase):
    def test_immediate_message_shape_and_limits(self):
        payload = messages.immediate_payload({"post_id": 7, "title": "@everyone @here <@123456789012345678> " + "가" * 400},
                                             f"{BASE}/career/reviews/7", "면접 후기")
        embed = payload["embeds"][0]
        self.assertEqual(payload["allowed_mentions"], {"parse": []})
        self.assertNotIn("@everyone", embed["title"])
        self.assertNotIn("@here", embed["title"])
        self.assertLessEqual(len(embed["title"]), 256)
        self.assertEqual(embed["footer"]["text"], "ref:post-7")
        self.assertEqual(set(embed) - {"title", "url", "color", "author", "description", "footer"}, set())
        self.assertNotIn("content", payload)  # 본문/작성자 없음

    def test_digest_message_five_posts_and_markdown_safety(self):
        entries = [({"post_id": i, "title": "x" * 300 + "[evil](http://evil.example) *b* `c` @everyone"},
                    f"{BASE}/career/lab/{i}", "취업 전략") for i in range(1, 6)]
        payload = messages.digest_payload(entries, date(2026, 12, 1))
        embed = payload["embeds"][0]
        self.assertEqual(embed["title"], "오늘의 취업 준비 정보")
        self.assertEqual(len(embed["description"].splitlines()), 5)
        self.assertLessEqual(len(embed["description"]), 4096)
        self.assertLessEqual(messages._embed_size(embed), 6000)
        self.assertNotIn("](http://evil", embed["description"])  # 링크 문법이 이스케이프됨
        self.assertNotIn("@everyone", embed["description"])
        self.assertEqual(embed["footer"]["text"], "ref:digest-2026-12-01")
        self.assertEqual(payload["allowed_mentions"], {"parse": []})

    def test_title_cleaning_and_unsafe_url(self):
        self.assertEqual(messages.clean_title("a\nb\x00c\t d", 50), "a b c d")
        self.assertEqual(messages.clean_title("   ", 10), "(제목 없음)")
        self.assertEqual(messages.clean_title(None, 10), "(제목 없음)")
        self.assertEqual(len(messages.clean_title("x" * 500, 100)), 100)
        for bad in ("javascript:alert(1)", "https://a.b/c d", "https://a.b/c)x", "", None, BASE + "/" + "x" * 500):
            with self.assertRaises(ValueError):
                messages.safe_url(bad)

    def test_marker_matching_is_exact(self):
        message = {"embeds": [{"footer": {"text": "ref:post-123"}}]}
        self.assertTrue(messages.message_has_marker(message, "ref:post-123"))
        self.assertFalse(messages.message_has_marker(message, "ref:post-12"))
        self.assertFalse(messages.message_has_marker({"content": "ref:post-123"}, "ref:post-123"))


class SettingsAndContractTests(unittest.TestCase):
    ENV = {"CAREER_SHARE_CUTOVER_AT": "2026-12-01T00:00:00+09:00", "CAREER_SHARE_SEND_QUEUE_URL": "q",
           "PLAYMATE_WEB_BASE_URL": BASE}

    def test_cutover_required_and_timezone_aware(self):
        loaded = settings.load_db_settings(self.ENV)
        self.assertEqual(loaded.cutover_at, datetime(2026, 11, 30, 15, 0, tzinfo=UTC))
        for bad in ({}, {**self.ENV, "CAREER_SHARE_CUTOVER_AT": "2026-12-01T00:00:00"},
                    {**self.ENV, "CAREER_SHARE_CUTOVER_AT": "nope"}, {**self.ENV, "CAREER_SHARE_SEND_QUEUE_URL": ""},
                    {**self.ENV, "CAREER_SHARE_DIGEST_LIMIT": "6"},
                    {**self.ENV, "CAREER_SHARE_CLAIM_STALE_MINUTES": "5"},
                    {**self.ENV, "CAREER_SHARE_MAX_VERIFIES": "2"}):
            with self.assertRaises(settings.SettingsError, msg=str(bad)):
                settings.load_db_settings(bad)

    def test_web_base_url_rules(self):
        self.assertEqual(settings.web_base_url(BASE + "/"), BASE)
        for bad in ("", None, "ftp://x.y", "http://localhost:3000", "https://user:pw@x.y", BASE + "?a=1", "not a url"):
            self.assertIsNone(settings.web_base_url(bad), bad)
        self.assertEqual(settings.web_base_url("http://localhost:3000", allow_local=True), "http://localhost:3000")
        self.assertEqual(settings.load_db_settings({**self.ENV, "PLAYMATE_WEB_BASE_URL": ""}).base_url, "")

    def test_contract_validation(self):
        good = {"v": 1, "type": "send", "job_id": "post-1:t", "unit_id": "post-1", "kind": "IMMEDIATE", "claim_token": "t",
                "claimed_at": contract.iso(T0), "not_after": contract.iso(T0 + timedelta(minutes=10)), "marker": "ref:post-1",
                "payload": {"embeds": [{"footer": {"text": "ref:post-1"}}]}}
        contract.validate_job(good)
        for key, value in [("marker", "ref:post-2"), ("unit_id", "x-1"), ("type", "other"), ("not_after", "bad"),
                           ("payload", {"embeds": [{"footer": {"text": "ref:post-9"}}]}),
                           ("payload", {"embeds": [{"footer": {"text": "ref:post-1"}}], "content": "x"}),
                           ("claim_token", "")]:
            with self.assertRaises(contract.ContractError, msg=key):
                contract.validate_job({**good, key: value})
        with self.assertRaises(contract.ContractError):
            contract.loads('{"v": 2}')
        with self.assertRaises(contract.ContractError):
            contract.loads("not json")
        base = {"v": 1, "type": "result", "job_id": "j", "unit_id": "post-1", "claim_token": "t", "outcome": "SENT"}
        with self.assertRaises(contract.ContractError):
            contract.validate_result(base)  # SENT에 message_id 없음
        with self.assertRaises(contract.ContractError):
            contract.validate_result({**base, "outcome": "MAYBE"})
        contract.validate_result({**base, "message_id": "123456789012345678"})

    def test_state_machine(self):
        self.assertEqual(state.next_state("SENT", "UNKNOWN"), None)       # 끝 상태는 되돌리지 않는다
        self.assertEqual(state.next_state("SENT", "FAILED_RETRY"), None)
        self.assertEqual(state.next_state("UNKNOWN", "FAILED_RETRY"), None)  # UNKNOWN은 미전송 증명 없이 FAILED가 되지 않는다
        self.assertEqual(state.next_state("UNKNOWN", "ABSENT_PROVEN"), "FAILED")
        self.assertEqual(state.next_state("UNKNOWN", "SENT"), "SENT")
        self.assertIsNone(state.next_state("PENDING", "ABSENT_PROVEN"))   # 확인 없이 PENDING을 미전송으로 바꾸지 않는다
        self.assertIsNone(state.retry_at("FAILED_PERMANENT", T0, 1, 5))
        self.assertEqual(state.retry_at("FAILED_RETRY", T0, 2, 5), T0 + timedelta(minutes=10))

    def test_digest_date_is_kst_calendar_date(self):
        self.assertEqual(digest_date(datetime(2026, 12, 1, 11, 0, tzinfo=UTC)), date(2026, 12, 1))   # 20:00 KST
        self.assertEqual(digest_date(datetime(2026, 11, 30, 15, 0, tzinfo=UTC)), date(2026, 12, 1))  # 00:00 KST
        self.assertEqual(digest_date(datetime(2026, 11, 30, 14, 59, tzinfo=UTC)), date(2026, 11, 30))


# ====================================================================================================================
class ShareFlow:
    """메모리/PostgreSQL 공통 시나리오. backend_class만 다르다."""
    backend_class = MemoryBackend

    def setUp(self):
        self.p = Pipeline(self.backend_class())
        self.b = self.p.backend
        self.addCleanup(self.p.close)

    def drive(self, start, *, step=10, steps=14, until=None):
        """start부터 step분 간격으로 recover(확인 작업 발행) + Worker 처리를 반복한다. until()이 참이면 멈춘다."""
        moment = start
        for _ in range(steps):
            moment += timedelta(minutes=step)
            self.p.at(moment)
            self.p.service.recover(moment)
            self.p.pump()
            if until and until():
                break
        return moment

    def status(self, pid):
        return self.b.row(pid)["status"]

    def test_worker_rejects_unit_of_other_feature_before_discord(self):
        """회귀(#165): 계약은 hot-<id>도 허용하지만 취업 Worker는 보내지 않는다 (조회·전송 0회, 상태 불변)."""
        self.b.add_post(1, sub="INTERVIEW")
        self.p.service.relay(T0)
        job = contract.loads(self.p.queue.bodies(SEND_Q)[0])
        foreign = dict(job, unit_id="hot-1", marker="ref:hot-1", job_id="hot-1:" + job["claim_token"])
        foreign["payload"] = {**job["payload"], "embeds": [dict(job["payload"]["embeds"][0], footer={"text": "ref:hot-1"})]}
        contract.validate_job(foreign)                                   # 계약 자체는 통과한다
        for candidate in (foreign, {k: v for k, v in foreign.items() if k != "payload"} | {"type": contract.TYPE_VERIFY}):
            with self.assertRaises(contract.ContractError):
                self.p.worker.process(candidate)
        self.assertEqual((self.p.discord.posts, self.p.discord.gets), ([], 0))
        self.assertEqual(self.status(1), "PENDING")
        self.p.run_worker()                                              # 원래 작업은 그대로 처리된다
        self.assertEqual(self.p.discord.count_posts(), 1)

    # -- 대상 판정과 컷오버 ------------------------------------------------------------
    def test_immediate_targets_labels_and_exclusions(self):
        b = self.b
        b.add_post(1, sub="INTERVIEW")
        b.add_post(2, sub="SUCCESS", process_result="PASS")
        b.add_post(3, sub="SUCCESS", process_result="FAIL")
        b.add_post(4, sub="FINAL")
        for pid, (category, sub) in enumerate([("reviews", "DOCUMENT"), ("reviews", "CODING_ASSIGNMENT"), ("talk", "INTERVIEW"),
                                               ("lounge", "FINAL"), ("lab", "RESUME"), ("lab", "JOB_STRATEGY")], start=10):
            b.add_post(pid, category=category, sub=sub)
        b.add_post(20, sub="INTERVIEW", post_status="DRAFT")
        b.add_post(21, sub="INTERVIEW", deleted=True)
        result = self.p.service.relay(T0)
        self.assertEqual(result["claimed"], 4)
        jobs = [contract.loads(body) for body in self.p.queue.bodies(SEND_Q)]
        self.assertEqual(sorted(j["unit_id"] for j in jobs), ["post-1", "post-2", "post-3", "post-4"])
        authors = {j["unit_id"]: j["payload"]["embeds"][0]["author"]["name"] for j in jobs}
        self.assertTrue(authors["post-1"].endswith("면접 후기"))
        self.assertTrue(authors["post-2"].endswith("합격 후기"))
        self.assertTrue(authors["post-3"].endswith("최종 결과 후기"))   # SUCCESS지만 PASS 아님
        self.assertTrue(authors["post-4"].endswith("최종 결과 후기"))
        for pid in (10, 11, 12, 13, 14, 15, 20, 21):
            self.assertIsNone(b.row(pid), pid)

    def test_cutover_boundary_and_timezone(self):
        b = self.b
        b.add_post(1, created_at=CUTOVER - timedelta(seconds=1))   # 컷오버 1초 전 (KST 자정 직전): 제외
        b.add_post(2, created_at=CUTOVER)                           # 경계: 포함
        b.add_post(3, created_at=CUTOVER + timedelta(seconds=1))
        b.add_post(4, created_at=datetime(2026, 11, 30, 14, 59, 59, tzinfo=UTC))  # UTC 11/30 14:59:59 = KST 11/30 23:59:59: 제외
        b.add_post(5, created_at=datetime(2026, 11, 30, 15, 0, 0, tzinfo=UTC))    # = KST 12/01 00:00:00: 포함
        self.p.service.relay(T0)
        self.assertEqual(sorted(j["unit_id"] for j in map(contract.loads, self.p.queue.bodies(SEND_Q))),
                         ["post-2", "post-3", "post-5"])

    def test_baseline_marks_old_posts_and_never_shares_them(self):
        b = self.b
        b.add_post(1, created_at=CUTOVER - timedelta(days=30))
        b.add_post(2, category="lab", sub="CERTIFICATION", created_at=CUTOVER - timedelta(days=1))
        b.add_post(3)
        self.assertEqual(self.p.service.baseline()["baseline_rows"], 2)
        self.assertEqual(self.p.service.baseline()["baseline_rows"], 0)   # 멱등
        self.assertEqual(b.row(1)["status"], "BASELINE")
        self.p.service.relay(T0)
        self.assertEqual([contract.loads(x)["unit_id"] for x in self.p.queue.bodies(SEND_Q)], ["post-3"])

    def test_db_failure_never_skips_posts(self):
        """조회가 한 번 실패해도 커서/범위를 앞으로 옮기지 않으므로 글이 누락되지 않는다."""
        self.b.add_post(1)
        original = self.p.service.repo.claim_immediate
        calls = []

        def flaky(*a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("db down")
            return original(*a, **k)
        with mock.patch.object(self.p.service.repo, "claim_immediate", flaky):
            with self.assertRaises(RuntimeError):
                self.p.service.relay(T0)
            self.b.add_post(2, created_at=T0 + timedelta(seconds=30))   # 실패 사이에 새 글
            self.p.service.relay(T0 + timedelta(minutes=1))
        self.assertEqual(sorted(contract.loads(x)["unit_id"] for x in self.p.queue.bodies(SEND_Q)), ["post-1", "post-2"])

    def test_missing_base_url_claims_nothing(self):
        self.p.service.s = make_settings(base_url="")
        self.b.add_post(1)
        self.assertEqual(self.p.service.relay(T0), {"skipped": "no_base_url"})
        self.assertEqual(self.p.service.digest(T0), {"skipped": "no_base_url"})
        self.assertIsNone(self.b.row(1))
        self.assertEqual(self.p.queue.messages, [])

    # -- 중복 선점 / 이벤트·SQS 중복 -------------------------------------------------------
    def test_concurrent_claims_pick_each_post_once(self):
        for pid in range(1, 31):
            self.b.add_post(pid)
        repos = [self.b.repo, getattr(self.b, "repo_b", self.b.repo)]
        results, barrier = [[], []], threading.Barrier(2)

        def run(index):
            barrier.wait()
            results[index] = repos[index].claim_immediate(T0, cutover=CUTOVER, limit=30, max_attempts=3, stale_minutes=30)
        threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        claimed = [c["posts"][0]["post_id"] for group in results for c in group]
        self.assertEqual(sorted(claimed), list(range(1, 31)))   # 모두 선점되고 겹치지 않는다

    def test_same_scheduler_event_twice(self):
        self.b.add_post(1)
        self.p.service.relay(T0)
        self.p.service.relay(T0)
        self.assertEqual(len(self.p.queue.bodies(SEND_Q)), 1)
        self.assertEqual(self.b.row(1)["attempt_count"], 1)

    def test_duplicate_sqs_delivery_sends_one_discord_message(self):
        self.b.add_post(1)
        self.p.service.relay(T0)
        body = self.p.queue.bodies(SEND_Q)[0]
        self.p.queue.send(SEND_Q, body)    # SQS가 같은 메시지를 두 번 전달
        self.p.run_worker()
        self.assertEqual(self.p.discord.count_posts(), 1)
        self.assertEqual([r["outcome"] for r in self.p.worker_results], ["SENT", "SENT"])
        self.assertEqual(len({r["message_id"] for r in self.p.worker_results}), 1)
        self.assertEqual(self.p.apply_results(), ["applied", "duplicate"])
        self.assertEqual(self.b.row(1)["status"], "SENT")
        self.assertTrue(self.b.row(1)["discord_message_id"])

    def test_discord_sent_but_db_record_fails_then_recovers(self):
        self.b.add_post(1)
        self.p.service.relay(T0)
        self.p.run_worker()
        with mock.patch.object(self.p.service.repo, "apply_result", side_effect=RuntimeError("db down")):
            with self.assertRaises(RuntimeError):
                self.p.apply_results()
        self.assertEqual(self.b.row(1)["status"], "PENDING")        # SENT로 기록되지 않았다 (성공으로 오기록 없음)
        self.assertEqual(self.p.discord.count_posts(), 1)
        # 결과 큐가 재전달하면 반영된다 (큐에서 지우지 못했다고 가정)
        self.p.queue.send(RESULT_Q, contract.dumps(self.p.worker_results[0]))
        self.assertEqual(self.p.apply_results(), ["applied"])
        self.assertEqual(self.b.row(1)["status"], "SENT")

    def test_lost_result_is_reconciled_by_marker_without_resend(self):
        self.b.add_post(1)
        self.p.service.relay(T0)
        self.p.run_worker()
        self.p.queue.messages = []                                   # 결과가 영영 사라졌다 (DLQ 등)
        self.p.at(T0 + timedelta(minutes=31))
        report = self.p.service.recover(self.p.clock)
        self.assertEqual(report["verify_jobs"], 0)                   # 만료 직후에는 확인하지 않는다 (정착 대기)
        self.assertEqual(self.status(1), "UNKNOWN")
        self.drive(T0 + timedelta(minutes=31), until=lambda: self.status(1) == "SENT")
        self.assertEqual(self.status(1), "SENT")
        self.assertEqual(self.p.discord.count_posts(), 1)

    # -- Discord 오류 -------------------------------------------------------------------------------------------
    def test_5xx_after_message_was_stored_resolves_to_sent_without_resend(self):
        self.b.add_post(1)
        self.p.discord.fail_post = ["store500"]
        self.p.service.relay(T0)
        self.p.pump()
        self.assertEqual(self.b.row(1)["status"], "SENT")
        self.assertEqual(len(self.p.discord.posts), 1)               # 재전송 없음 (POST 1회)
        self.assertEqual(self.p.discord.count_posts(), 1)

    def test_5xx_without_marker_is_unknown_and_never_resent(self):
        """UNKNOWN 직후에는 relay/recover/Worker(verify 경로 포함)를 계속 돌려도 정착 대기 동안 재발송이 없다."""
        self.b.add_post(1)
        self.p.discord.seed(T0 - timedelta(hours=2))                   # 이전 메시지가 있어 '미전송 증명'이 가능한 정상 채널
        self.p.discord.fail_post = ["500"]
        self.p.service.relay(T0)
        self.p.pump()
        self.assertEqual(self.status(1), "UNKNOWN")
        for minute in range(1, 30):                                    # 정착 대기(30분) 동안
            self.p.at(T0 + timedelta(minutes=minute))
            self.p.service.relay(self.p.clock)                         # relay 안의 recover 포함
            self.p.pump()                                              # 발행된 verify가 있다면 Worker가 실제로 처리
            self.assertEqual(self.status(1), "UNKNOWN", minute)
        self.assertEqual(len(self.p.discord.posts), 1)                 # POST는 처음 1회뿐
        self.assertEqual(len(self.p.worker_results), 1)                # verify 작업 자체가 아직 발행되지 않았다
        self.assertEqual(self.b.row(1)["verify_count"], 0)

    def test_unknown_stays_unknown_when_history_is_hidden_and_resolves_when_proven_absent(self):
        self.b.add_post(1)
        self.p.discord.fail_post = ["500"]
        self.p.service.relay(T0)
        self.p.pump()
        self.assertEqual(self.status(1), "UNKNOWN")
        # 1) 권한 문제로 목록이 비어 보임 -> 마커를 못 찾아도 미전송이라고 단정하지 않는다 (확인을 여러 번 해도 UNKNOWN 유지)
        self.p.discord.seed(T0 - timedelta(hours=1))
        self.p.discord.seed(T0 + timedelta(minutes=5))       # claimed_at 이후의 다른 메시지: 숨겨진 목록과 last_message_id가 어긋난다
        self.p.discord.hide_history = True
        last = self.drive(T0, steps=5)    # 확인 3회(30,40,50분): max_verifies(6)를 소진하지 않는다
        self.assertEqual(self.status(1), "UNKNOWN")
        self.assertEqual(self.b.row(1)["absent_count"], 0)
        self.assertEqual(len(self.p.discord.posts), 1)
        # 2) 조회가 정상이고 claimed_at 이전 메시지까지 닿았는데 마커가 없다 -> 서로 다른 확인 2회 -> 재시도 가능
        self.p.discord.hide_history = False
        self.drive(last, until=lambda: self.status(1) == "FAILED")
        self.assertEqual(self.status(1), "FAILED")
        self.p.service.relay(self.p.clock)                              # 증명되었으므로 다시 선점해 보낸다
        self.p.pump()
        self.assertEqual(self.status(1), "SENT")
        self.assertEqual(self.b.row(1)["attempt_count"], 2)
        self.assertEqual(self.p.discord.count_posts(), 1)

    def test_unknown_is_resent_only_after_two_separated_absence_proofs(self):
        self.b.add_post(1)
        self.p.discord.seed(T0 - timedelta(hours=2))
        self.p.discord.fail_post = ["500"]                             # 서버가 저장하지 않은 5xx
        self.p.service.relay(T0)
        self.p.pump()
        self.p.at(T0 + timedelta(minutes=31))
        self.assertEqual(self.p.service.recover(self.p.clock)["verify_jobs"], 1)
        self.p.pump()                                                  # 첫 증명: 마커 없음 + claimed_at 이전까지 조회됨
        self.assertEqual(self.status(1), "UNKNOWN")                    # 한 번으로는 미전송을 확정하지 않는다
        self.assertEqual(self.b.row(1)["absent_count"], 1)
        self.p.at(T0 + timedelta(minutes=35))
        self.assertEqual(self.p.service.recover(self.p.clock)["verify_jobs"], 0)   # 확인 간격(10분) 전
        self.p.at(T0 + timedelta(minutes=42))
        self.assertEqual(self.p.service.recover(self.p.clock)["verify_jobs"], 1)
        self.p.pump()                                                  # 두 번째 증명
        self.assertEqual(self.status(1), "FAILED")
        self.assertEqual(len(self.p.discord.posts), 1)                 # 지금까지 재발송 없음
        self.p.service.relay(self.p.clock)
        self.p.pump()
        self.assertEqual(self.status(1), "SENT")
        self.assertEqual(self.p.discord.count_posts(), 1)

    def test_server_storing_message_late_is_recovered_as_sent_not_resent(self):
        """클라이언트는 5xx를 받았지만 Discord 서버가 뒤늦게 메시지를 저장한 경우: 정착 대기 후 확인으로 SENT가 된다."""
        self.b.add_post(1)
        self.p.discord.seed(T0 - timedelta(hours=2))
        self.p.discord.fail_post = ["late500"]
        self.p.service.relay(T0)
        self.p.pump()
        self.assertEqual(self.status(1), "UNKNOWN")
        self.assertEqual(self.p.discord.count_posts(), 0)              # 아직 저장 전
        self.p.at(T0 + timedelta(minutes=31))
        self.p.service.recover(self.p.clock)
        self.p.pump()                                                  # 첫 확인은 '없음' (지연 중)
        self.assertEqual(self.status(1), "UNKNOWN")
        self.p.discord.release_delayed(T0 + timedelta(minutes=35))     # 서버가 뒤늦게 저장
        self.p.at(T0 + timedelta(minutes=42))
        self.p.service.recover(self.p.clock)
        self.p.pump()
        self.assertEqual(self.status(1), "SENT")
        self.assertEqual(len(self.p.discord.posts), 1)                 # 재발송 없음
        self.assertEqual(self.p.discord.count_posts(), 1)

    def test_absent_proofs_must_come_from_distinct_verify_jobs(self):
        self.b.add_post(1)
        self.p.discord.fail_post = ["500"]
        self.p.service.relay(T0)
        self.p.pump()
        token = self.b.row(1)["claim_token"]
        result = {"unit_id": "post-1", "claim_token": token, "outcome": "ABSENT_PROVEN", "job_id": "post-1:t:v1"}
        repo = self.b.repo
        kwargs = dict(retry_base_minutes=5, absent_required=2)
        self.assertEqual(repo.apply_result(result, T0, **kwargs), "applied")
        self.assertEqual(repo.apply_result(result, T0, **kwargs), "duplicate")     # 같은 확인 작업 결과의 중복 도착
        self.assertEqual(self.status(1), "UNKNOWN")
        inconclusive = {**result, "outcome": "INCONCLUSIVE", "job_id": "post-1:t:v2"}
        repo.apply_result(inconclusive, T0, **kwargs)
        self.assertEqual(self.b.row(1)["absent_count"], 0)             # 불확실한 확인이 끼면 증명 횟수를 처음부터 센다
        repo.apply_result({**result, "job_id": "post-1:t:v3"}, T0, **kwargs)
        self.assertEqual(self.status(1), "UNKNOWN")
        repo.apply_result({**result, "job_id": "post-1:t:v4"}, T0, **kwargs)
        self.assertEqual(self.status(1), "FAILED")

    def test_expired_redelivered_job_is_unknown_not_expired(self):
        self.b.add_post(1)
        self.p.service.relay(T0)
        job = contract.loads(self.p.queue.bodies(SEND_Q)[0])
        self.p.at(T0 + timedelta(minutes=11))
        self.assertEqual(self.p.worker.process(job, receive_count=2)["outcome"], "UNKNOWN")   # 앞선 전달이 보냈을 수 있다
        self.assertEqual(self.p.worker.process(job, receive_count=1)["outcome"], "EXPIRED")
        self.assertEqual(len(self.p.discord.posts), 0)

    def test_wrong_token_or_state_never_changes_unknown_row(self):
        self.b.add_post(1)
        self.p.discord.fail_post = ["500"]
        self.p.service.relay(T0)
        self.p.pump()
        token = self.b.row(1)["claim_token"]
        base = {"unit_id": "post-1", "claim_token": "someone-else", "job_id": "j"}
        for outcome in ("SENT", "ABSENT_PROVEN", "FAILED_RETRY", "FAILED_PERMANENT", "EXPIRED"):
            extra = {"message_id": "123456789012345678"} if outcome == "SENT" else {}
            self.assertEqual(self.b.repo.apply_result({**base, "outcome": outcome, **extra}, T0, retry_base_minutes=5), "ignored")
        for outcome in ("FAILED_RETRY", "FAILED_PERMANENT", "EXPIRED"):    # 올바른 토큰이어도 UNKNOWN을 이 결과들로 바꾸지 않는다
            self.b.repo.apply_result({**base, "claim_token": token, "outcome": outcome}, T0, retry_base_minutes=5)
            self.assertEqual(self.status(1), "UNKNOWN", outcome)

    # -- 기존 18:00 공지와의 상태 충돌 (M1) ---------------------------------------------------------------------------
    def _failed_row_taken_by_legacy_notice(self):
        self.b.add_post(1)
        self.p.service.relay(T0)
        self.p.discord.fail_post = ["429", "429"]
        self.p.pump()                                                  # 신규 기능이 FAILED(재시도 대기)로 둔다
        self.assertEqual(self.status(1), "FAILED")
        stale_result = dict(self.p.worker_results[-1])
        self.b.legacy_take(1, T0 + timedelta(minutes=10))              # 18:00 공지(claim_due)가 그 행을 선점
        self.assertEqual(self.status(1), "PENDING")
        self.assertIsNotNone(self.b.row(1)["announce_date"])
        return stale_result

    def test_legacy_notice_claiming_failed_row_is_not_modified_by_recovery(self):
        stale = self._failed_row_taken_by_legacy_notice()
        self.p.at(T0 + timedelta(minutes=45))                          # 선점 만료 시각(claim_expires_at)이 지난 뒤
        for _ in range(3):
            self.assertEqual(self.p.service.recover(self.p.clock), {"verify_jobs": 0, "verify_due": 0})
        report = self.p.service.relay(self.p.clock)
        self.assertEqual(report["claimed"], 0)                         # 신규 기능은 이 행을 다시 선점하지 않는다
        self.assertEqual(self.status(1), "PENDING")                    # UNKNOWN으로 바뀌지 않았다
        self.assertEqual(self.p.queue.bodies(SEND_Q), [])
        late_sent = {**stale, "outcome": "SENT", "message_id": "123456789012345678"}
        self.assertEqual(self.p.service.apply_result(contract.dumps(late_sent), self.p.clock), "ignored")
        self.b.legacy_mark_sent(1)                                     # 기존 공지가 정상적으로 SENT를 기록할 수 있다
        self.assertEqual(self.status(1), "SENT")
        self.assertEqual(self.p.discord.count_posts(), 0)              # 저장된(게시된) 메시지 없음: 429 시도 2건은 실행되지 않았다
        self.assertEqual(self.p.service.summary(self.p.clock)["CLAIMED_BY_LEGACY_NOTICE"], 1)

    def test_row_touched_by_legacy_notice_is_never_reclaimed(self):
        self._failed_row_taken_by_legacy_notice()
        self.b.legacy_fail(1)                                          # 기존 공지도 실패 -> FAILED
        self.p.at(T0 + timedelta(days=2))
        self.assertEqual(self.p.service.relay(self.p.clock)["claimed"], 0)
        self.assertEqual(self.p.queue.bodies(SEND_Q), [])
        self.assertEqual(self.status(1), "FAILED")

    def test_permanent_errors_not_retried(self):
        for index, code in enumerate(("401", "403", "404", "400"), start=1):
            self.b.add_post(index)
            self.p.discord.fail_post = [code]
            self.p.service.relay(T0)
            self.p.pump()
            row = self.b.row(index)
            self.assertEqual(row["status"], "FAILED", code)
            self.assertIsNone(row["next_retry_at"], code)
        posts_before = len(self.p.discord.posts)
        self.p.at(T0 + timedelta(days=3))
        self.p.service.relay(self.p.clock)
        self.assertEqual(len(self.p.discord.posts), posts_before)    # 영구 오류는 자동 재시도 없음

    def test_rate_limit_retried_later_then_gives_up(self):
        self.b.add_post(1)
        for attempt in range(1, 4):
            self.p.at(T0 + timedelta(hours=attempt))
            self.p.discord.fail_post = ["429", "429"]                 # 클라이언트 재시도(max_retries=1)까지 모두 429
            self.p.service.relay(self.p.clock)
            self.p.pump()
            row = self.b.row(1)
            self.assertEqual(row["status"], "FAILED", attempt)
            self.assertEqual(row["attempt_count"], attempt)
            if attempt == 1:  # 재시도 시각 전에는 다시 집지 않는다
                self.p.service.relay(self.p.clock)
                self.assertEqual(self.b.row(1)["attempt_count"], 1)
        self.assertEqual(self.p.discord.count_posts(), 0)             # 429는 실행되지 않았다
        self.p.at(T0 + timedelta(days=2))
        self.p.service.relay(self.p.clock)
        self.assertEqual(self.b.row(1)["attempt_count"], 3)           # 한도 초과 후 자동 재시도 없음
        self.assertEqual(self.p.service.summary()["FAILED_NO_AUTO_RETRY"], 1)

    def test_sqs_publish_failure_keeps_pending_and_recovers_safely(self):
        self.b.add_post(1)
        self.p.queue.fail_next = 1
        report = self.p.service.relay(T0)
        self.assertEqual(report["publish_failed"], 1)
        self.assertEqual(self.status(1), "PENDING")                   # FAILED로 단정하지 않는다
        self.p.service.relay(T0 + timedelta(minutes=1))
        self.assertEqual(self.p.queue.bodies(SEND_Q), [])             # 중복 선점 없음
        self.p.discord.seed(T0 - timedelta(hours=1))                  # 이전 메시지가 있어야 미전송이 증명된다
        self.p.at(T0 + timedelta(minutes=31))
        self.p.service.recover(self.p.clock)                          # 만료 -> UNKNOWN (확인은 정착 대기 뒤)
        self.assertEqual(self.status(1), "UNKNOWN")
        self.drive(T0 + timedelta(minutes=31), until=lambda: self.status(1) == "FAILED")
        self.assertEqual(self.status(1), "FAILED")
        self.p.service.relay(self.p.clock)
        self.p.pump()
        self.assertEqual(self.status(1), "SENT")
        self.assertEqual(sum(1 for m in self.p.discord.messages if m.get("embeds") and m["embeds"][0].get("title")), 1)

    def test_old_job_after_not_after_is_expired_not_sent(self):
        self.b.add_post(1)
        self.p.service.relay(T0)
        self.p.at(T0 + timedelta(minutes=11))                         # 큐에서 11분 대기 (job_ttl 10분)
        self.p.pump()
        self.assertEqual(self.p.discord.count_posts(), 0)
        self.assertEqual(self.p.worker_results[0]["outcome"], "EXPIRED")
        row = self.b.row(1)
        self.assertEqual(row["status"], "FAILED")
        self.p.service.relay(self.p.clock)                              # 미전송이 확실하므로 바로 재선점 가능
        self.p.pump()
        self.assertEqual(self.b.row(1)["status"], "SENT")

    def test_worker_redelivery_after_result_publish_failure_does_not_duplicate(self):
        self.b.add_post(1)
        self.p.service.relay(T0)
        job_body = self.p.queue.bodies(SEND_Q)[0]
        broken = FakeQueue()
        broken.fail_next = 1
        record = {"messageId": "m1", "body": job_body, "attributes": {"ApproximateReceiveCount": "1"}}
        out = worker_lambda.handle_records({"Records": [record]}, self.p.worker, broken, RESULT_Q)
        self.assertEqual(out, {"batchItemFailures": [{"itemIdentifier": "m1"}]})   # 결과 발행 실패 -> 큐가 재전달
        self.assertEqual(self.p.discord.count_posts(), 1)
        record["attributes"]["ApproximateReceiveCount"] = "2"
        out = worker_lambda.handle_records({"Records": [record]}, self.p.worker, broken, RESULT_Q)
        self.assertEqual(out, {"batchItemFailures": []})
        self.assertEqual(self.p.discord.count_posts(), 1)               # 마커 발견 -> 재전송 없음
        self.assertEqual(json.loads(broken.bodies(RESULT_Q)[0])["outcome"], "SENT")

    def test_redelivered_job_with_unverifiable_history_is_unknown_not_resent(self):
        self.b.add_post(1)
        self.p.service.relay(T0)
        self.p.discord.seed(T0 - timedelta(hours=1))
        self.p.discord.seed(T0 + timedelta(minutes=1))       # 선점 이후 메시지가 있는데 목록에서는 숨겨진다
        self.p.discord.hide_history = True
        result = self.p.worker.process(contract.loads(self.p.queue.bodies(SEND_Q)[0]), receive_count=2)
        self.assertEqual(result["outcome"], "UNKNOWN")
        self.assertEqual(len(self.p.discord.posts), 0)

    # -- 20시 묶음 ------------------------------------------------------------------------------------------------
    def _digest_posts(self, count, start=100):
        for index in range(count):
            self.b.add_post(start + index, category="lab", sub=("JOB_STRATEGY", "CERTIFICATION", "JOB_COMPARISON")[index % 3],
                            created_at=T0 - timedelta(hours=count - index), title=f"연구소 {index}")

    def test_digest_twelve_posts_over_three_days(self):
        self._digest_posts(12)
        self.b.add_post(500, category="lab", sub="RESUME", created_at=T0 - timedelta(days=1))   # 제외
        self.b.add_post(501, category="lab", sub="CERTIFICATION", created_at=T0 - timedelta(days=1), deleted=True)
        sent_per_day = []
        for day in range(3):
            moment = datetime(2026, 12, 1 + day, 11, 0, tzinfo=UTC)    # 20:00 KST
            self.p.at(moment)
            self.p.discord.now = moment
            report = self.p.service.digest(moment, scheduled_at=moment)
            self.p.pump()
            embeds = [m for m in self.p.discord.messages if m["embeds"][0]["footer"]["text"] == f"ref:digest-{moment.date().isoformat()}"]
            self.assertEqual(len(embeds), 1, day)
            sent_per_day.append(len(embeds[0]["embeds"][0]["description"].splitlines()))
            self.assertEqual(report["published"], 1)
        self.assertEqual(sent_per_day, [5, 5, 2])
        self.assertEqual(self.b.batch_count(), 3)
        # 오래된 글 먼저: 1일차 5건은 가장 오래된 100~104
        self.assertEqual([self.b.row(pid)["batch_id"] for pid in range(100, 105)], ["digest-2026-12-01"] * 5)
        self.assertEqual([self.b.row(pid)["batch_id"] for pid in range(110, 112)], ["digest-2026-12-03"] * 2)
        self.assertIsNone(self.b.row(500))
        self.assertIsNone(self.b.row(501))
        self.p.at(datetime(2026, 12, 4, 11, 0, tzinfo=UTC))
        self.assertEqual(self.p.service.digest(self.p.clock, self.p.clock), {"claimed": 0})   # 더 보낼 글이 없으면 보내지 않는다
        self.assertTrue(all(self.b.row(pid)["status"] == "SENT" for pid in range(100, 112)))

    def test_digest_twice_same_date_sends_once(self):
        self._digest_posts(8)   # 후보가 남아 있어도 같은 날짜에는 두 번째 묶음을 만들지 않는다 (날짜당 1건 제한 자체를 검증)
        moment = datetime(2026, 12, 1, 11, 0, tzinfo=UTC)
        self.p.at(moment)
        self.p.service.digest(moment, moment)
        again = self.p.service.digest(moment + timedelta(minutes=1), moment)
        self.assertEqual(again, {"claimed": 0})
        self.p.pump()
        self.assertEqual(self.p.discord.count_posts(), 1)
        self.assertEqual(self.b.batch_count(), 1)
        self.assertEqual([self.b.row(pid) for pid in (105, 106, 107)], [None, None, None])

    def test_carried_over_posts_precede_new_posts_and_deleted_waiting_post_is_skipped(self):
        self._digest_posts(7)
        d1 = datetime(2026, 12, 1, 11, 0, tzinfo=UTC)
        self.p.at(d1)
        self.p.service.digest(d1, d1)
        self.p.pump()
        self.b.add_post(900, category="lab", sub="CERTIFICATION", created_at=T0 + timedelta(hours=1))   # 새 글
        self.b.delete_post(105)                                       # 이월 대기 중 삭제된 글
        d2 = datetime(2026, 12, 2, 11, 0, tzinfo=UTC)
        self.p.at(d2)
        self.p.service.digest(d2, d2)
        self.p.pump()
        self.assertEqual(self.b.row(106)["batch_id"], "digest-2026-12-02")   # 이월 글 우선
        self.assertEqual(self.b.row(900)["batch_id"], "digest-2026-12-02")
        self.assertIsNone(self.b.row(105))                                    # 삭제된 글은 공유되지 않음

    def test_unknown_or_failed_previous_batch_does_not_collide_with_next_day(self):
        self._digest_posts(10)
        d1 = datetime(2026, 12, 1, 11, 0, tzinfo=UTC)
        self.p.at(d1)
        self.p.discord.fail_post = ["500"]                            # 1일차 배치: 결과 불명
        self.p.service.digest(d1, d1)
        self.p.pump()
        self.assertEqual({self.b.row(pid)["status"] for pid in range(100, 105)}, {"UNKNOWN"})
        d2 = datetime(2026, 12, 2, 11, 0, tzinfo=UTC)
        self.p.at(d2)
        self.p.service.digest(d2, d2)
        self.p.pump()
        # 2일차는 UNKNOWN 글을 다시 집지 않고 나머지 5건만 보낸다
        self.assertEqual({self.b.row(pid)["batch_id"] for pid in range(105, 110)}, {"digest-2026-12-02"})
        self.assertEqual({self.b.row(pid)["batch_id"] for pid in range(100, 105)}, {"digest-2026-12-01"})
        self.assertEqual(len(self.p.discord.posts), 2)                # 1일차 POST 1 + 2일차 POST 1 (재발송 없음)
        # 영구 실패한 배치도 다음 날 다시 집히지 않는다
        for job in ("v1", "v2"):   # 서로 다른 확인 작업 2회로 미전송이 증명됨
            self.p.backend.repo.apply_result({"unit_id": "digest-2026-12-01", "claim_token": self._token(100),
                                              "outcome": "ABSENT_PROVEN", "job_id": job}, d2, retry_base_minutes=5)
        # ABSENT_PROVEN(미전송 증명)된 1일차 글은 이월 후보가 되어 3일차에 보내진다 (중복이 아니라 재시도)
        d3 = datetime(2026, 12, 3, 11, 0, tzinfo=UTC)
        self.p.at(d3)
        self.p.service.digest(d3, d3)
        self.p.pump()
        self.assertEqual({self.b.row(pid)["batch_id"] for pid in range(100, 105)}, {"digest-2026-12-03"})
        self.assertEqual(self.b.row(100)["attempt_count"], 2)

    def _token(self, pid):
        return self.b.row(pid)["claim_token"] if self.b.name == "postgres" else self.b.repo.rows[pid]["claim_token"]

    def test_digest_rejects_immediate_categories_and_vice_versa(self):
        self.b.add_post(1, category="reviews", sub="INTERVIEW")
        self.b.add_post(2, category="lab", sub="JOB_STRATEGY")
        self.p.service.digest(T0, T0)
        self.assertIsNone(self.b.row(1))
        self.assertEqual(self.b.row(2)["share_kind"], "DIGEST")
        self.p.service.relay(T0)
        self.assertEqual(self.b.row(1)["share_kind"], "IMMEDIATE")
        self.assertEqual(self.b.row(2)["share_kind"], "DIGEST")

    # -- 기존 18시 공지 이력과의 공존 -------------------------------------------------------------------------------
    def test_existing_legacy_history_prevents_duplicates(self):
        b = self.b
        for pid in (1, 2, 3, 4):
            b.add_post(pid)
        b.add_legacy(1, "SENT")
        b.add_legacy(2, "PENDING")
        b.add_legacy(3, "FAILED", next_retry_at=None, attempts=1)    # 기존 FAILED는 next_retry_at이 없어 이 기능이 집지 않는다
        b.add_legacy(4, "BASELINE", attempts=0)
        self.p.service.relay(T0 + timedelta(days=1))
        self.assertEqual(self.p.queue.bodies(SEND_Q), [])
        for pid, status in ((1, "SENT"), (2, "PENDING"), (3, "FAILED"), (4, "BASELINE")):
            self.assertEqual(b.row(pid)["status"], status)

    def test_late_or_foreign_results_are_ignored(self):
        self.b.add_post(1)
        self.p.service.relay(T0)
        self.p.run_worker()
        result = dict(self.p.worker_results[0])
        for bad in ({**result, "claim_token": "other"}, {**result, "unit_id": "post-999"}):
            self.assertEqual(self.p.service.apply_result(contract.dumps(bad), T0), "ignored")
        self.assertEqual(self.b.row(1)["status"], "PENDING")
        self.p.apply_results()
        late_failure = {**result, "outcome": "FAILED_RETRY", "message_id": None}
        self.assertEqual(self.p.service.apply_result(contract.dumps(late_failure), T0), "duplicate")
        self.assertEqual(self.b.row(1)["status"], "SENT")                # SENT는 뒤늦은 실패 결과로 바뀌지 않는다


class MemoryShareFlow(ShareFlow, unittest.TestCase):
    backend_class = MemoryBackend


@unittest.skipUnless(DSN, "PLAYMATE_TEST_PG_DSN 없음: PostgreSQL 통합 테스트 미실시")
class PostgresShareFlow(ShareFlow, unittest.TestCase):
    backend_class = PostgresBackend

    @classmethod
    def setUpClass(cls):
        from psycopg.conninfo import conninfo_to_dict
        if conninfo_to_dict(DSN).get("host") not in ("127.0.0.1", "localhost"):
            raise unittest.SkipTest("일회용 로컬 DB(127.0.0.1/localhost)에서만 실행합니다.")


@unittest.skipUnless(DSN, "PLAYMATE_TEST_PG_DSN 없음: PostgreSQL 통합 테스트 미실시")
class PostsCreatedAtTimeZoneFacts(unittest.TestCase):
    """M2: posts.created_at(timestamp without time zone DEFAULT CURRENT_TIMESTAMP)의 기준은 '입력한 세션의 시간대'다.
    이 기능은 컷오버를 UTC naive로 비교하므로 운영 DB가 UTC 기준인지 먼저 확인해야 한다 (DEPLOY.md 확인 항목)."""

    def setUp(self):
        self.backend = PostgresBackend()
        self.addCleanup(self.backend.close)

    def test_default_timestamp_follows_session_time_zone(self):
        conn = self.backend.admin
        conn.execute("CREATE TEMP TABLE tz_probe (tag TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("SET TIME ZONE 'UTC'")
        conn.execute("INSERT INTO tz_probe (tag) VALUES ('utc')")
        conn.execute("SET TIME ZONE 'Asia/Seoul'")
        conn.execute("INSERT INTO tz_probe (tag) VALUES ('seoul')")
        conn.execute("SET TIME ZONE 'UTC'")
        rows = dict(conn.execute("SELECT tag, created_at FROM tz_probe").fetchall())
        gap = rows["seoul"] - rows["utc"]
        self.assertAlmostEqual(gap.total_seconds(), 9 * 3600, delta=60)

    def test_kst_naive_posts_would_be_misjudged_by_utc_cutover(self):
        """운영 DB 기본 시간대가 KST라면: 컷오버(KST 12/01 00:00) 1시간 전(11/30 23:00 KST)에 쓴 글이 '컷오버 이후'로 잘못 선점된다."""
        conn = self.backend.admin
        conn.execute("INSERT INTO posts VALUES (1,'CAREER','PUBLISHED','kst naive','2026-11-30 23:00:00',NULL)")
        conn.execute("INSERT INTO career VALUES (1,'reviews','INTERVIEW','{}')")
        claims = self.backend.repo.claim_immediate(T0, cutover=CUTOVER, limit=5, max_attempts=3, stale_minutes=30)
        self.assertEqual([c["unit_id"] for c in claims], ["post-1"])   # UTC 가정이 틀리면 이렇게 된다 (확인 필요 항목)


@unittest.skipUnless(DSN, "PLAYMATE_TEST_PG_DSN 없음: PostgreSQL 통합 테스트 미실시")
class PostgresMinimalSchemaTests(unittest.TestCase):
    """DB 구조 최소화: 배치 테이블은 2컬럼, 공유 이력 테이블의 추가 컬럼은 9개, 날짜 보장과 원자성은 DB에서 확인한다."""
    ADDED = {"share_kind", "batch_id", "claim_token", "claim_expires_at", "next_retry_at", "verify_count",
             "last_verified_at", "absent_count", "last_absent_job_id"}
    BASE_013 = {"post_id", "category_code", "status", "announce_date", "attempt_count", "discord_channel_id",
                "discord_message_id", "error_message", "claimed_at", "sent_at", "created_at", "updated_at"}

    def setUp(self):
        self.backend = PostgresBackend()
        self.addCleanup(self.backend.close)
        self.conn = self.backend.admin

    def columns(self, table):
        rows = self.conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' "
                                 "AND table_name = %s", (table,)).fetchall()
        return {row[0] for row in rows}

    def test_table_shapes(self):
        self.assertEqual(self.columns("career_discord_announcements"), self.BASE_013 | self.ADDED)
        self.assertNotIn("subcategory_code", self.columns("career_discord_announcements"))
        self.assertIn("claim_expires_at", self.columns("career_discord_announcements"))   # 선점 시점의 만료 기준 보존
        self.assertEqual(self.columns("career_discord_share_batches"), {"batch_date", "created_at"})
        pk = self.conn.execute("SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                               "WHERE i.indrelid = 'career_discord_share_batches'::regclass AND i.indisprimary").fetchall()
        self.assertEqual([row[0] for row in pk], ["batch_date"])

    def test_database_rejects_second_batch_for_same_date(self):
        import psycopg
        self.conn.execute("INSERT INTO career_discord_share_batches (batch_date) VALUES ('2026-12-01')")
        with self.assertRaises(psycopg.errors.UniqueViolation):
            self.conn.execute("INSERT INTO career_discord_share_batches (batch_date) VALUES ('2026-12-01')")

    def test_batch_insert_and_claims_are_atomic(self):
        """배치 INSERT가 실패하면 같은 트랜잭션의 글 선점도 롤백된다 (PENDING 행도, 배치 행도 남지 않는다)."""
        for pid in range(1, 4):
            self.backend.add_post(pid, category="lab", sub="CERTIFICATION", created_at=T0 - timedelta(hours=pid))
        self.conn.execute("ALTER TABLE career_discord_share_batches ADD CONSTRAINT ck_forced_failure CHECK (false)")
        with self.assertRaises(Exception):
            self.backend.repo.claim_digest(T0, date(2026, 12, 1), cutover=CUTOVER, limit=5, max_attempts=3, stale_minutes=30)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM career_discord_announcements").fetchone()[0], 0)
        self.assertEqual(self.backend.batch_count(), 0)
        self.conn.execute("ALTER TABLE career_discord_share_batches DROP CONSTRAINT ck_forced_failure")
        claim = self.backend.repo.claim_digest(T0, date(2026, 12, 1), cutover=CUTOVER, limit=5, max_attempts=3, stale_minutes=30)
        self.assertEqual(len(claim["posts"]), 3)                       # 같은 날짜가 막히지 않고 정상 선점된다
        self.assertEqual(self.backend.batch_count(), 1)

    def test_claim_expires_at_is_kept_per_claim_and_unaffected_by_later_setting_change(self):
        self.backend.add_post(1)
        self.backend.repo.claim_immediate(T0, cutover=CUTOVER, limit=5, max_attempts=3, stale_minutes=30)
        first = self.conn.execute("SELECT claim_expires_at FROM career_discord_announcements WHERE post_id = 1").fetchone()[0]
        self.assertEqual(first, (T0 + timedelta(minutes=30)).replace(tzinfo=None))
        # 설정(stale_minutes)을 바꿔도 이미 선점한 행의 만료 시각은 그대로이고, 복구는 저장된 값을 기준으로 한다
        self.assertEqual(self.backend.repo.claim_verifications(T0 + timedelta(minutes=20), max_verifies=6,
                                                               interval_minutes=10, settle_minutes=30), [])
        self.assertEqual(self.backend.row(1)["status"], "PENDING")
        self.backend.repo.claim_verifications(T0 + timedelta(minutes=31), max_verifies=6, interval_minutes=10, settle_minutes=30)
        self.assertEqual(self.backend.row(1)["status"], "UNKNOWN")

    def test_upgrade_from_013_with_existing_rows_twice(self):
        sql_dir = ROOT.parent / "database" / "sql"
        self.conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        self.conn.execute("""
            CREATE TABLE posts (post_id BIGINT PRIMARY KEY, post_type VARCHAR(20), post_status VARCHAR(20), title TEXT,
                                created_at TIMESTAMP NOT NULL, deleted_at TIMESTAMP);
            CREATE TABLE career (post_id BIGINT PRIMARY KEY REFERENCES posts(post_id), category_code VARCHAR(20),
                                 subcategory_code VARCHAR(50), details JSONB DEFAULT '{}');
            CREATE VIEW career_posts AS SELECT post_id, category_code, subcategory_code FROM career;
            INSERT INTO posts SELECT g, 'CAREER', 'PUBLISHED', 't' || g, '2026-10-01', NULL FROM generate_series(1, 6) g;
            INSERT INTO career SELECT g, CASE WHEN g <= 3 THEN 'reviews' ELSE 'lab' END, 'INTERVIEW' FROM generate_series(1, 6) g;""")
        self.conn.execute((sql_dir / "013_career_discord_announcements.sql").read_text(encoding="utf-8"))
        self.conn.execute("UPDATE career_discord_announcements SET status='SENT', discord_message_id='42', attempt_count=1 WHERE post_id=1")
        self.conn.execute("UPDATE career_discord_announcements SET status='FAILED', attempt_count=2 WHERE post_id=2")
        legacy_columns = "post_id, category_code, status, announce_date, attempt_count, discord_channel_id, discord_message_id, "                          "error_message, claimed_at, sent_at, created_at, updated_at"
        before = self.conn.execute(f"SELECT {legacy_columns} FROM career_discord_announcements ORDER BY post_id").fetchall()
        for _ in range(2):
            self.conn.execute((sql_dir / "048_career_discord_share.sql").read_text(encoding="utf-8"))
        after = self.conn.execute(f"SELECT {legacy_columns} FROM career_discord_announcements ORDER BY post_id").fetchall()
        self.assertEqual(after, before)                                 # 기존 013 컬럼 값이 그대로 보존된다
        kinds = {row[0] for row in self.conn.execute("SELECT share_kind FROM career_discord_announcements").fetchall()}
        self.assertEqual(kinds, {"LEGACY"})
        self.assertEqual(self.columns("career_discord_announcements"), self.BASE_013 | self.ADDED)
        self.assertEqual(self.columns("career_discord_share_batches"), {"batch_date", "created_at"})


# ====================================================================================================================
class LambdaInterfaceTests(unittest.TestCase):
    def setUp(self):
        self.backend = MemoryBackend()
        self.queue = FakeQueue()
        self.service = CareerShareService(self.backend.repo, self.queue, make_settings(), clock=lambda: T0)

    def test_db_lambda_event_routing(self):
        self.backend.add_post(1)
        with mock.patch("career_share.db_lambda.datetime") as fake_dt:
            fake_dt.now.return_value = T0
            fake_dt.side_effect = datetime
            out = db_lambda.handler({"action": "relay"}, None, service=self.service)
        self.assertEqual(out["claimed"], 1)
        self.assertEqual(db_lambda.handler({"action": "summary"}, None, service=self.service)["PENDING"], 1)
        self.assertEqual(db_lambda.handler({"action": "baseline"}, None, service=self.service), {"baseline_rows": 0})
        with self.assertRaises(ValueError):
            db_lambda.handler({"action": "nope"}, None, service=self.service)

    def test_db_lambda_digest_uses_scheduled_time_date(self):
        self.backend.add_post(1, category="lab", sub="CERTIFICATION")
        out = db_lambda.handler({"action": "digest", "scheduled_at": "2026-12-01T11:00:00Z"}, None, service=self.service)
        self.assertEqual(out["claimed"], 1)
        self.assertIn(date(2026, 12, 1), self.backend.repo.batches)
        bad = db_lambda.handler({"action": "digest", "scheduled_at": "garbage"}, None, service=self.service)
        self.assertIn("claimed", bad)   # 형식이 틀려도 현재 시각의 날짜로 진행한다 (실행이 막히지 않는다)

    def test_db_lambda_sqs_result_records(self):
        self.backend.add_post(1)
        self.service.relay(T0)
        token = self.backend.row(1)["claim_token"]
        ok = {"v": 1, "type": "result", "job_id": "j", "unit_id": "post-1", "claim_token": token, "outcome": "SENT",
              "message_id": "123456789012345678", "channel_id": str(CHANNEL)}
        out = db_lambda.handler({"Records": [{"messageId": "a", "body": contract.dumps(ok)},
                                              {"messageId": "b", "body": "not json"},
                                              {"messageId": "c", "body": contract.dumps({**ok, "outcome": "MAYBE"})}]},
                                None, service=self.service)
        self.assertEqual(out, {"batchItemFailures": [{"itemIdentifier": "b"}, {"itemIdentifier": "c"}]})
        self.assertEqual(self.backend.row(1)["status"], "SENT")

    def test_db_lambda_db_error_reports_item_failure_for_redelivery(self):
        ok = {"v": 1, "type": "result", "job_id": "j", "unit_id": "post-1", "claim_token": "t", "outcome": "UNKNOWN"}
        with mock.patch.object(self.service.repo, "apply_result", side_effect=RuntimeError("db down")):
            out = db_lambda.handler({"Records": [{"messageId": "a", "body": contract.dumps(ok)}]}, None, service=self.service)
        self.assertEqual(out["batchItemFailures"], [{"itemIdentifier": "a"}])

    def test_worker_lambda_bad_job_goes_to_failure_list(self):
        discord = StatefulDiscord()
        self.addCleanup(discord.close)
        worker = CareerShareWorker(DiscordRestClient(TOKEN, base_url=discord.url, sleep=lambda s: None), CHANNEL,
                                   clock=lambda: T0)
        out = worker_lambda.handle_records({"Records": [{"messageId": "x", "body": "{}"}]}, worker, FakeQueue(), RESULT_Q)
        self.assertEqual(out, {"batchItemFailures": [{"itemIdentifier": "x"}]})
        self.assertEqual(discord.posts, [])

    def test_worker_ignores_mentions_from_payload_and_never_leaks_token(self):
        self.backend.add_post(1, title="@everyone 공지")
        self.service.relay(T0)
        job = contract.loads(self.queue.bodies(SEND_Q)[0])
        job["payload"]["allowed_mentions"] = {"parse": ["everyone"]}   # 변조된 작업
        discord = StatefulDiscord()
        self.addCleanup(discord.close)
        discord.now = T0
        worker = CareerShareWorker(DiscordRestClient(TOKEN, base_url=discord.url, sleep=lambda s: None), CHANNEL, clock=lambda: T0)
        result = worker.process(job)
        self.assertEqual(result["outcome"], "SENT")
        self.assertEqual(discord.posts[0]["allowed_mentions"], {"parse": []})
        self.assertNotIn(TOKEN, json.dumps(result))

    def test_runtime_modules_do_not_pull_gateway_config_or_db_driver(self):
        code = ("import sys; import career_share.worker_lambda, career_share.db_lambda;"
                "bad=[m for m in ('discord','config','psycopg','boto3','bot','aiohttp') if m in sys.modules];"
                "print(bad); sys.exit(1 if bad else 0)")
        env = {k: v for k, v in os.environ.items() if not k.startswith(("DB_", "DISCORD"))}
        done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_worker_module_has_no_database_dependency(self):
        for name in ("worker.py", "worker_lambda.py"):
            source = (ROOT / "career_share" / name).read_text(encoding="utf-8")
            for forbidden in ("psycopg", "repositories", "repository", "import discord\n"):
                self.assertNotIn(forbidden, source.replace("DB 접근", ""), (name, forbidden)) if forbidden != "repository" else None


class LegacyNoticeSwitchTests(unittest.TestCase):
    """기존 18:00 공지 스위치 (config.CAREER_NOTICE_ENABLED): 기본값은 기존 동작(켜짐) 유지."""

    def _run(self, value):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("DB_", "PLAYMATE_"))}
        env.update(DISCORD_BOT_TOKEN="x", DISCORD_GUILD_ID="1", PLAYMATE_CAREER_CHANNEL_ID="222222222222222222")
        if value is not None:
            env["PLAYMATE_CAREER_NOTICE_ENABLED"] = value
        return subprocess.run([sys.executable, "-c", "import config; print(config.CAREER_NOTICE_ENABLED, config.CAREER_CHANNEL_ID)"],
                              cwd=ROOT, env=env, capture_output=True, text=True)

    def _enabled(self, value):
        done = self._run(value)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.split()

    def test_default_keeps_existing_behavior_and_channel_id_is_untouched(self):
        for value in (None, "", "true", "TRUE", "1", "yes", "on"):
            self.assertEqual(self._enabled(value), ["True", "222222222222222222"], value)
        for value in ("false", "FALSE", "0", "no", "off", " False "):
            self.assertEqual(self._enabled(value), ["False", "222222222222222222"], value)   # 채널 ID(보호 목록용)는 그대로

    def test_invalid_value_stops_instead_of_enabling(self):
        """Issue #190: 오타를 켜짐으로 보면 서버리스 전환 뒤 18:00 공지가 중복될 수 있어 시작을 거부한다."""
        for value in ("garbage", "fasle", "2"):
            done = self._run(value)
            self.assertNotEqual(done.returncode, 0, value)
            self.assertIn("PLAYMATE_CAREER_NOTICE_ENABLED", done.stderr)

    def test_bot_gates_only_the_career_notice_task(self):
        source = (ROOT / "bot.py").read_text(encoding="utf-8")
        self.assertIn("if not CAREER_NOTICE_ENABLED:", source)
        self.assertIn("elif CAREER_CHANNEL_ID is not None:", source)
        self.assertIn('feature_tasks.append(("알림 polling (10초)"', source)   # 다른 기능은 그대로


class SqlMigrationStaticTests(unittest.TestCase):
    SQL = (ROOT.parent / "database" / "sql" / "048_career_discord_share.sql").read_text(encoding="utf-8")

    def test_incremental_and_idempotent_and_013_untouched(self):
        self.assertNotIn("CREATE TABLE career_discord_announcements", self.SQL)
        self.assertNotIn("ADD COLUMN IF NOT EXISTS subcategory_code", self.SQL)   # 읽는 곳이 없어 제거했다
        for removed in ("post_count", "discord_message_id VARCHAR(32),\n    created_at", "sent_at TIMESTAMP,\n    CONSTRAINT"):
            self.assertNotIn(removed, self.SQL.split("CREATE TABLE IF NOT EXISTS career_discord_share_batches")[1].split(");")[0])
        for needle in ("ADD COLUMN IF NOT EXISTS share_kind", "'UNKNOWN'", "'SKIPPED'", "claim_token", "claim_expires_at",
                        "next_retry_at", "batch_id", "CREATE TABLE IF NOT EXISTS career_discord_share_batches",
                        "batch_date DATE PRIMARY KEY", "DROP CONSTRAINT IF EXISTS"):
            self.assertIn(needle, self.SQL)
        self.assertEqual(subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "database/sql/013_career_discord_announcements.sql"],
                                        cwd=ROOT.parent).returncode, 0)


if __name__ == "__main__":
    unittest.main()
