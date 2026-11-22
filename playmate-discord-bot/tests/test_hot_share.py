"""HOT 게시글 Discord 자동 공유(hot_share, Issue #165) 테스트.

실제 Discord/AWS/공용 DB에는 접속하지 않는다. #163 테스트의 상태를 가진 가짜 Discord(127.0.0.1)와 외부 접속 차단 장치를 재사용하고,
SQS는 메모리 큐(FakeQueue)를 쓴다. DB 테스트는 일회용 로컬 PostgreSQL에서만 실행한다 (public 스키마를 지우고 다시 만든다).
  docker run -d --rm -e POSTGRES_PASSWORD=test -e POSTGRES_DB=pm -p 127.0.0.1:55432:5432 postgres:16
  PLAYMATE_TEST_PG_DSN="host=127.0.0.1 port=55432 user=postgres password=test dbname=pm" python tests/test_hot_share.py
웹 일치 테스트는 backend의 실제 board_repository.list_featured_posts(psycopg2)를 같은 DB에서 실행해 비교한다.
"""
import json
import os
import sys
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import test_career_share as cs  # noqa: E402  (가짜 Discord, 외부 접속 차단, 취업 공유 설정 재사용)
from career_share import contract  # noqa: E402
from career_share.queues import FakeQueue  # noqa: E402
from career_share.repository import InMemoryCareerShareRepository  # noqa: E402
from career_share.settings import SettingsError  # noqa: E402
from career_share.worker import CareerShareWorker  # noqa: E402
from career_share.worker_lambda import handle_records  # noqa: E402
from discord_rest import DiscordRestClient  # noqa: E402
from hot_share import db_lambda, messages, policy  # noqa: E402
from hot_share import settings as hot_settings  # noqa: E402
from hot_share.repository import BASELINE_REQUIRED, PostgresHotShareRepository  # noqa: E402
from hot_share.service import HotShareService  # noqa: E402
from hot_share.worker_lambda import HotShareWorker  # noqa: E402

UTC = timezone.utc
T0 = cs.T0                       # 2026-12-01T12:00Z
CHANNEL, BASE, TOKEN = cs.CHANNEL, cs.BASE, cs.TOKEN
SEND_Q, RESULT_Q = "queue://hot-send", "queue://hot-result"
DSN = os.environ.get("PLAYMATE_TEST_PG_DSN")
SQL_DIR = REPO / "database" / "sql"


def setUpModule():
    cs.setUpModule()


def tearDownModule():
    cs.tearDownModule()


def make_settings(**over) -> hot_settings.HotSettings:
    values = dict(send_queue_url=SEND_Q, base_url=BASE, db_timezone="UTC", relay_limit=10, max_attempts=3,
                  retry_base_minutes=5, job_ttl_minutes=3, claim_stale_minutes=15, verify_interval_minutes=10,
                  max_verifies=6, verify_settle_minutes=30, absent_required=2)
    values.update(over)
    return hot_settings.HotSettings(**values)


def hot_job(post_id=7, board_id=1, title="제목", claimed_at=T0, token="tok123"):
    service = HotShareService(None, FakeQueue(), make_settings())
    claim = {"unit_id": messages.hot_unit_id(post_id), "kind": policy.KIND_HOT, "claim_token": token, "claimed_at": claimed_at,
             "posts": [{"post_id": post_id, "board_id": board_id, "title": title}]}
    return service._job(claim, claimed_at, contract.TYPE_SEND)


# =====================================================================================================================
# DB 없이 실행하는 테스트
# =====================================================================================================================
class PolicyMatchesBackend(unittest.TestCase):
    """HOT 기준을 새로 만들지 않았는지: backend 상수·SQL 문구와 비교한다."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(REPO / "backend"))
        from app.core import board_policy
        cls.bp = board_policy
        cls.repo_src = (REPO / "backend" / "app" / "repositories" / "board_repository.py").read_text(encoding="utf-8")

    def test_constants_equal_backend(self):
        self.assertEqual(policy.HOT_DAYS, self.bp.HOT_DAYS)
        self.assertEqual(policy.HOT_MIN_LIKES, self.bp.HOT_MIN_LIKES)
        self.assertEqual(policy.NOTICE_BOARD_NAME, self.bp.NOTICE_BOARD_NAME)

    def test_backend_hot_sql_still_has_the_conditions_we_copied(self):
        start = self.repo_src.index("def list_featured_posts")
        end = self.repo_src.find("\ndef ", start + 10)
        body = self.repo_src[start:end if end > 0 else None]
        for fragment in ("reaction_type = 'LIKE'", "CURRENT_TIMESTAMP - INTERVAL '{HOT_DAYS} days'",
                         "likes.recent_likes >= {HOT_MIN_LIKES}", "p.post_type = 'BOARD'", "p.post_status = 'PUBLISHED'",
                         "b.board_name <> '공지사항'", "_board_post_guard()"):
            self.assertIn(fragment, body, f"backend HOT SQL 변경 감지: {fragment}")
        guard = self.repo_src[self.repo_src.index("def _board_post_guard"):][:800]
        for fragment in ("deleted_at IS NULL", "COALESCE({alias}.post_status, 'PUBLISHED') = 'PUBLISHED'", "FROM recruits"):
            self.assertIn(fragment, guard)

    def test_shareable_board_allow_list(self):
        free = dict(board_name="자유게시판", scope_type="LEGACY", course_code=None, cohort=None, institution_id=None,
                    program_id=None, cohort_id=None)
        self.assertTrue(policy.is_shareable_board(free))
        for change in (dict(course_code="data-ml"), dict(cohort=3), dict(scope_type="NATIONAL"), dict(scope_type="COHORT", cohort_id=1),
                       dict(scope_type="INSTITUTION", institution_id=1), dict(scope_type="PROGRAM", program_id=1),
                       dict(scope_type=None), dict(scope_type="legacy"), dict(board_name="공지사항")):
            self.assertFalse(policy.is_shareable_board(free | change), change)
        self.assertFalse(policy.is_shareable_board({k: v for k, v in free.items() if k != "cohort"}), "키 누락 = 불명확 = 거부")


class MessageAndContract(unittest.TestCase):
    def test_payload_has_only_title_link_and_marker(self):
        job = hot_job(post_id=42, board_id=3, title="@everyone 공지 [링크](x)")
        embed = job["payload"]["embeds"][0]
        self.assertEqual(set(embed), {"title", "url", "color", "author", "description", "footer"})
        self.assertEqual(embed["url"], f"{BASE}/board/3/posts/42")
        self.assertEqual(embed["footer"]["text"], "ref:hot-42")
        self.assertEqual(embed["author"]["name"], messages.AUTHOR_TEXT)
        self.assertNotIn("@everyone", embed["title"])           # 멘션 무력화
        self.assertEqual(job["payload"]["allowed_mentions"], {"parse": []})
        self.assertEqual(job["unit_id"], "hot-42")
        self.assertEqual(job["kind"], "HOT")
        self.assertEqual(contract.parse_time(job["not_after"]) - T0, timedelta(minutes=3))

    def test_non_hot_claim_cannot_become_hot_job(self):
        service = HotShareService(None, FakeQueue(), make_settings())
        with self.assertRaises(ValueError):
            service._job({"unit_id": "post-1", "kind": "IMMEDIATE", "claim_token": "t", "claimed_at": T0, "posts": []},
                         T0, contract.TYPE_SEND)

    def test_existing_career_units_still_valid_and_hot_unit_added(self):
        for unit in ("post-1", "digest-2026-12-01", "hot-1"):
            contract._common({"job_id": "j", "unit_id": unit, "claim_token": "t"})
        for unit in ("hot-", "hot-x", "hot-1-2", "HOT-1"):
            with self.assertRaises(contract.ContractError):
                contract._common({"job_id": "j", "unit_id": unit, "claim_token": "t"})

    def test_career_repository_ignores_hot_results(self):
        repo = InMemoryCareerShareRepository()
        result = {"unit_id": "hot-5", "claim_token": "t", "outcome": "SENT", "message_id": "1" * 18}
        self.assertEqual(repo.apply_result(result, T0, retry_base_minutes=5), "ignored")


class SettingsTests(unittest.TestCase):
    ENV = {"HOT_SHARE_SEND_QUEUE_URL": "https://sqs/hot", "HOT_SHARE_DB_TIMEZONE": "UTC",
           "PLAYMATE_WEB_BASE_URL": "https://playmate.example.com"}

    def test_valid(self):
        s = hot_settings.load_hot_settings(dict(self.ENV))
        self.assertEqual((s.db_timezone, s.job_ttl_minutes, s.relay_limit), ("UTC", 3, 10))

    def test_timezone_required_and_dst_rejected(self):
        for tz in ("", "Mars/Base", "America/New_York", "Europe/Berlin"):
            with self.assertRaises(SettingsError, msg=tz):
                hot_settings.load_hot_settings(self.ENV | {"HOT_SHARE_DB_TIMEZONE": tz})
        self.assertEqual(hot_settings.load_hot_settings(self.ENV | {"HOT_SHARE_DB_TIMEZONE": "Asia/Seoul"}).db_timezone,
                         "Asia/Seoul")

    def test_queue_must_differ_from_career_queue(self):
        with self.assertRaises(SettingsError):
            hot_settings.load_hot_settings(self.ENV | {"CAREER_SHARE_SEND_QUEUE_URL": "https://sqs/hot"})
        with self.assertRaises(SettingsError):
            hot_settings.load_hot_settings({k: v for k, v in self.ENV.items() if k != "HOT_SHARE_SEND_QUEUE_URL"})

    def test_stale_must_exceed_ttl(self):
        with self.assertRaises(SettingsError):
            hot_settings.load_hot_settings(self.ENV | {"HOT_SHARE_JOB_TTL_MINUTES": "20"})


class WorkerGuard(unittest.TestCase):
    """HOT Worker는 HOT 작업만 처리한다 (취업 작업이 HOT 채널에 게시되지 않게). Discord에 요청하지 않는다."""

    def setUp(self):
        self.discord = cs.StatefulDiscord()
        self.client = DiscordRestClient(TOKEN, base_url=self.discord.url, timeout=3.0, max_retries=1, sleep=lambda s: None)
        self.worker = HotShareWorker(self.client, CHANNEL, clock=lambda: T0)

    def tearDown(self):
        self.discord.close()

    def test_rejects_career_job(self):
        career_job = dict(hot_job(), unit_id="post-7", kind="IMMEDIATE", marker="ref:post-7")
        career_job["payload"]["embeds"][0]["footer"]["text"] = "ref:post-7"
        with self.assertRaises(contract.ContractError):
            self.worker.process(career_job)
        queue = FakeQueue()
        out = handle_records({"Records": [{"messageId": "m1", "body": contract.dumps(career_job)}]}, self.worker, queue, RESULT_Q)
        self.assertEqual(out, {"batchItemFailures": [{"itemIdentifier": "m1"}]})
        self.assertEqual((self.discord.posts, self.discord.gets, queue.messages), ([], 0, []))

    def career_job(self, post_id=8):
        service = cs.CareerShareService(None, FakeQueue(), cs.make_settings())
        claim = {"unit_id": f"post-{post_id}", "kind": "IMMEDIATE", "claim_token": "ctok", "claimed_at": T0,
                 "posts": [{"post_id": post_id, "title": "면접 후기", "category_code": "reviews", "subcategory_code": "INTERVIEW"}]}
        return service._job(claim, T0, contract.TYPE_SEND)

    def test_career_worker_rejects_hot_send_and_verify_jobs_before_any_discord_call(self):
        """회귀: 계약이 hot-를 허용해도 취업 Worker는 HOT 작업을 취업 채널에 게시하지 않는다 (재전달 포함)."""
        career_worker = CareerShareWorker(self.client, 555555555555555555, clock=lambda: T0)
        send = hot_job()
        verify = {k: v for k, v in send.items() if k != "payload"} | {"type": contract.TYPE_VERIFY}
        for job in (send, verify):
            with self.assertRaises(contract.ContractError):
                career_worker.process(job)
        queue = FakeQueue()
        records = [{"messageId": f"m{i}", "body": contract.dumps(send), "attributes": {"ApproximateReceiveCount": str(i)}}
                   for i in (1, 2, 3)]                          # SQS 재전달이 반복돼도 매번 거부 -> DLQ
        out = handle_records({"Records": records}, career_worker, queue, RESULT_Q)
        self.assertEqual(len(out["batchItemFailures"]), 3)
        self.assertEqual((self.discord.posts, self.discord.gets, queue.messages), ([], 0, []))

    def test_hot_worker_rejects_career_verify_job_and_mislabeled_kind(self):
        verify = {k: v for k, v in self.career_job().items() if k != "payload"} | {"type": contract.TYPE_VERIFY}
        relabeled = dict(self.career_job(), kind="HOT")         # kind만 HOT으로 바꿔도 단위가 post-면 거부
        for job in (verify, relabeled):
            with self.assertRaises(contract.ContractError):
                self.worker.process(job)
        self.assertEqual((self.discord.posts, self.discord.gets), ([], 0))

    def test_career_worker_still_sends_career_job(self):
        career_worker = CareerShareWorker(self.client, 555555555555555555, clock=lambda: T0)
        job = self.career_job()
        first = career_worker.process(job)
        second = career_worker.process(job, receive_count=2)   # 마커 확인으로 중복 방지 (기존 동작)
        self.assertEqual((first["outcome"], second["outcome"]), ("SENT", "SENT"))
        self.assertEqual(first["message_id"], second["message_id"])
        self.assertEqual(len(self.discord.posts), 1)
        self.assertEqual(self.discord.posts[0]["embeds"][0]["footer"]["text"], "ref:post-8")

    def test_sends_hot_job_once(self):
        job = hot_job()
        first = self.worker.process(job)
        second = self.worker.process(job, receive_count=2)       # SQS 중복 전달
        self.assertEqual((first["outcome"], second["outcome"]), ("SENT", "SENT"))
        self.assertEqual(first["message_id"], second["message_id"])
        self.assertEqual(len(self.discord.posts), 1)


# =====================================================================================================================
# 일회용 PostgreSQL 테스트
# =====================================================================================================================
SCHEMA = """
CREATE TABLE members (member_id BIGINT PRIMARY KEY, nickname VARCHAR(50), member_status VARCHAR(20) DEFAULT 'ACTIVE');
CREATE TABLE boards (
    board_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, board_name VARCHAR(40) NOT NULL, description VARCHAR(200),
    course_code VARCHAR(30), cohort INTEGER,
    scope_type VARCHAR(20) NOT NULL DEFAULT 'LEGACY', institution_id BIGINT, program_id BIGINT, cohort_id BIGINT,
    read_policy VARCHAR(20) NOT NULL DEFAULT 'SCOPE_ONLY', write_policy VARCHAR(20) NOT NULL DEFAULT 'SCOPE_ONLY',
    is_default BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_boards_access_scope CHECK (
        (scope_type IN ('LEGACY', 'NATIONAL') AND institution_id IS NULL AND program_id IS NULL AND cohort_id IS NULL)
        OR (scope_type = 'INSTITUTION' AND institution_id IS NOT NULL AND program_id IS NULL AND cohort_id IS NULL)
        OR (scope_type = 'PROGRAM' AND institution_id IS NULL AND program_id IS NOT NULL AND cohort_id IS NULL)
        OR (scope_type = 'COHORT' AND institution_id IS NULL AND program_id IS NULL AND cohort_id IS NOT NULL)),
    CONSTRAINT ck_boards_read_policy CHECK (read_policy IN ('SCOPE_ONLY', 'ALL_VERIFIED')));
CREATE TABLE posts (
    post_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, board_id BIGINT REFERENCES boards(board_id),
    author_member_id BIGINT NOT NULL REFERENCES members(member_id), post_type VARCHAR(30), post_status VARCHAR(20),
    title VARCHAR(100) NOT NULL, body TEXT, is_anonymous BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, deleted_at TIMESTAMP);
CREATE TABLE recruits (recruit_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, post_id BIGINT REFERENCES posts(post_id));
CREATE TABLE comments (comment_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, post_id BIGINT, deleted_at TIMESTAMP);
CREATE TABLE post_attachments (attachment_id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, post_id BIGINT,
    attachment_scope VARCHAR(20), stored_path TEXT, original_filename TEXT, display_order INT DEFAULT 0);
INSERT INTO members (member_id, nickname) SELECT g, 'm' || g FROM generate_series(1, 40) AS g;
"""


@unittest.skipUnless(DSN, "PLAYMATE_TEST_PG_DSN 없음: PostgreSQL 통합 테스트 미실시")
class PgCase(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg.conninfo import conninfo_to_dict
        if conninfo_to_dict(DSN).get("host") not in ("127.0.0.1", "localhost"):
            self.fail("일회용 로컬 DB(127.0.0.1/localhost)에서만 실행합니다.")
        self.psycopg = psycopg
        self.admin = psycopg.connect(DSN, autocommit=True)
        self.admin.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        self.admin.execute(SCHEMA)
        for name in ("045_post_reactions.sql", "052_hot_discord_share.sql"):
            self.admin.execute((SQL_DIR / name).read_text(encoding="utf-8"))
        self._dbs, self._pipes, self._extra = [], [], []
        self.free = self.board("자유게시판")
        self.repo = self.make_repo()

    def tearDown(self):
        for pipe in self._pipes:
            pipe.discord.close()
        for db in self._dbs:
            db._reset()
        for conn in self._extra:
            conn.close()
        self.admin.close()

    # -- 준비 도구 ----------------------------------------------------------------------------------------------
    def make_repo(self, *, session_tz="Asia/Seoul", db_tz="UTC", app="hot_test"):
        """Lambda 연결 옵션(career_share.connect_for_lambda와 같이 세션 TimeZone 지정)으로 별도 연결을 만든다."""
        from repositories.db import Database
        db = Database(lambda: self.psycopg.connect(DSN, autocommit=True, application_name=app,
                                                   options=f"-c TimeZone={session_tz}"))
        self._dbs.append(db)
        return PostgresHotShareRepository(db, db_tz)

    def board(self, name, **cols):
        cols = {"board_name": name} | cols
        keys = ", ".join(cols)
        marks = ", ".join(["%s"] * len(cols))
        return self.admin.execute(f"INSERT INTO boards ({keys}) VALUES ({marks}) RETURNING board_id", tuple(cols.values())).fetchone()[0]

    def post(self, board_id=None, *, title=None, post_type="BOARD", status="PUBLISHED", deleted=False, created=T0 - timedelta(days=1)):
        naive = created.astimezone(UTC).replace(tzinfo=None)
        pid = self.admin.execute(
            "INSERT INTO posts (board_id, author_member_id, post_type, post_status, title, body, created_at, deleted_at) "
            "VALUES (%s, 1, %s, %s, 'tmp', '본문 비밀 내용', %s, %s) RETURNING post_id",
            (board_id or self.free, post_type, status, naive, naive if deleted else None)).fetchone()[0]
        self.admin.execute("UPDATE posts SET title = %s WHERE post_id = %s", (title or f"HOT 후보 {pid}", pid))
        return pid

    def like(self, post_id, count, at=T0 - timedelta(hours=1), *, tz="UTC", first_member=1, kind="LIKE"):
        naive = at.astimezone(ZoneInfo(tz)).replace(tzinfo=None)
        for member in range(first_member, first_member + count):
            self.admin.execute(
                "INSERT INTO post_reactions (post_id, member_id, reaction_type, reason, created_at) VALUES (%s, %s, %s, %s, %s)",
                (post_id, member, kind, "SPAM" if kind == "REPORT" else None, naive))

    def unlike(self, post_id, member):
        self.admin.execute("DELETE FROM post_reactions WHERE post_id = %s AND member_id = %s AND reaction_type = 'LIKE'",
                           (post_id, member))

    def row(self, post_id):
        cur = self.admin.cursor(row_factory=self.psycopg.rows.dict_row)
        cur.execute("SELECT * FROM hot_discord_shares WHERE post_id = %s", (post_id,))
        return cur.fetchone()

    def rows(self):
        cur = self.admin.cursor(row_factory=self.psycopg.rows.dict_row)
        cur.execute("SELECT post_id, status, attempt_count FROM hot_discord_shares ORDER BY post_id")
        return cur.fetchall()

    def pipe(self, repo=None, **over):
        pipe = Pipe(repo or self.repo, **over)
        self._pipes.append(pipe)
        return pipe

    def baseline_empty(self):
        """HOT 글이 없을 때 baseline을 끝낸다 (이후 HOT이 되는 글은 신규)."""
        out = self.repo.baseline(T0 - timedelta(days=30))
        self.assertEqual(out["baseline_rows"], 0)

    def mark_baseline_done(self):
        """좋아요가 이미 들어간 뒤 '그 전에 baseline이 끝난 상태'를 만든다 (완료 표시만, BASELINE 행 없음)."""
        self.admin.execute("INSERT INTO hot_discord_share_state (singleton, baseline_completed_at) VALUES (TRUE, LOCALTIMESTAMP)")

    def claimed_ids(self, result_claims):
        return sorted(c["posts"][0]["post_id"] for c in result_claims)

    def web_ids(self, now=T0, repo=None):
        return sorted(r["post_id"] for r in (repo or self.repo).web_hot_posts(now))


class Pipe:
    """HOT DB Lambda 서비스 + 메모리 SQS + HOT Worker(가짜 Discord)."""

    def __init__(self, repo, **over):
        self.discord = cs.StatefulDiscord()
        self.queue = FakeQueue()
        self.clock = T0
        self.settings = make_settings(**over)
        self.service = HotShareService(repo, self.queue, self.settings, clock=lambda: self.clock)
        self.client = DiscordRestClient(TOKEN, base_url=self.discord.url, timeout=3.0, max_retries=1, sleep=lambda s: None)
        self.worker = HotShareWorker(self.client, CHANNEL, clock=lambda: self.clock)
        self.results: list[dict] = []

    def at(self, moment):
        self.clock = moment
        self.discord.now = moment
        return self

    def relay(self):
        return self.service.relay(self.clock)

    def send_jobs(self):
        return [contract.loads(b) for b in self.queue.bodies(SEND_Q)]

    def run_worker(self, *, receive_count=1):
        bodies = self.queue.bodies(SEND_Q)
        self.queue.messages = [m for m in self.queue.messages if m[0] != SEND_Q]
        for body in bodies:
            result = self.worker.process(contract.loads(body), receive_count=receive_count)
            self.results.append(result)
            self.queue.send(RESULT_Q, contract.dumps(result))
        return len(bodies)

    def apply_results(self):
        bodies = self.queue.bodies(RESULT_Q)
        self.queue.messages = [m for m in self.queue.messages if m[0] != RESULT_Q]
        return [self.service.apply_result(body, self.clock) for body in bodies]

    def cycle(self):
        relay = self.relay()
        self.run_worker()
        return relay, self.apply_results()

    def hot_messages(self):
        return [m for m in self.discord.messages
                if str(((m.get("embeds") or [{}])[0].get("footer") or {}).get("text", "")).startswith("ref:hot-")]


# -- HOT 판정 ---------------------------------------------------------------------------------------------------------
class HotSelectionTests(PgCase):
    def test_likes_9_10_9_10_shares_once(self):
        self.baseline_empty()
        p = self.pipe()
        pid = self.post()
        self.like(pid, 9)
        self.assertEqual(p.relay()["claimed"], 0, "9개는 HOT 아님")
        self.like(pid, 1, first_member=10)
        relay, applied = p.cycle()
        self.assertEqual((relay["claimed"], applied), (1, ["applied"]))
        self.assertEqual(self.row(pid)["status"], "SENT")
        self.unlike(pid, 10)                                      # 9개로 HOT 이탈
        self.assertEqual(p.at(T0 + timedelta(minutes=5)).relay()["claimed"], 0)
        self.like(pid, 1, first_member=11)                        # 다시 10개 = HOT 재진입
        self.assertEqual(p.at(T0 + timedelta(minutes=10)).relay()["claimed"], 0, "재진입 재공유 금지")
        self.assertEqual(len(p.hot_messages()), 1)
        self.assertEqual(self.row(pid)["attempt_count"], 1)

    def test_likes_10_to_11_no_second_share(self):
        self.baseline_empty()
        p = self.pipe()
        pid = self.post()
        self.like(pid, 10)
        self.assertEqual(p.cycle()[0]["claimed"], 1)
        self.like(pid, 1, first_member=11)
        self.assertEqual(p.at(T0 + timedelta(minutes=5)).cycle()[0]["claimed"], 0)
        self.assertEqual(len(p.hot_messages()), 1)

    def test_seven_day_boundary(self):
        edge = T0 - timedelta(days=7)
        inside, outside, old = self.post(), self.post(), self.post()
        for pid, last in ((inside, edge), (outside, edge - timedelta(seconds=1))):
            self.like(pid, 9)
            self.like(pid, 1, last, first_member=20)
        self.like(old, 9)
        self.like(old, 20, T0 - timedelta(days=8), first_member=10)   # 누적 29개라도 최근 7일 9개면 HOT 아님
        self.assertEqual(self.web_ids(T0), [inside], "경계 시각(정확히 7일 전)은 포함(>=), 1초 전은 제외")
        self.mark_baseline_done()
        self.assertEqual(self.claimed_ids(self.repo.claim_hot(T0, limit=10, max_attempts=3, stale_minutes=15)), [inside])

    def test_lambda_session_timezone_does_not_shift_boundary(self):
        """웹 세션 UTC(운영 backend 기본값으로 가정)로 저장된 좋아요: Lambda 세션이 서울이든 UTC든 결과가 같다."""
        near_in, near_out = self.post(), self.post()
        self.like(near_in, 9)
        self.like(near_in, 1, T0 - timedelta(days=7) + timedelta(hours=2), first_member=20)
        self.like(near_out, 9)
        self.like(near_out, 1, T0 - timedelta(days=7) - timedelta(hours=2), first_member=20)
        seoul = self.make_repo(session_tz="Asia/Seoul", db_tz="UTC")
        utc = self.make_repo(session_tz="UTC", db_tz="UTC")
        self.assertEqual(self.web_ids(T0, seoul), [near_in])
        self.assertEqual(self.web_ids(T0, utc), [near_in])
        # 웹 SQL을 그대로(세션 시간대에 의존) Lambda 서울 세션에서 실행하면 9시간 어긋난다: db_tz 변환이 필요한 이유
        naive_web = """SELECT p.post_id FROM post_reactions l JOIN posts p ON p.post_id = l.post_id
                       WHERE l.reaction_type = 'LIKE' AND l.created_at >= %s::timestamptz - INTERVAL '7 days'
                       GROUP BY p.post_id HAVING COUNT(*) >= 10 ORDER BY 1"""
        with self.psycopg.connect(DSN, autocommit=True, options="-c TimeZone=UTC") as conn:
            self.assertEqual([r[0] for r in conn.execute(naive_web, (T0,))], [near_in], "웹 세션(UTC) 기준 정답")
        with self.psycopg.connect(DSN, autocommit=True, options="-c TimeZone=Asia/Seoul") as conn:
            self.assertEqual([r[0] for r in conn.execute(naive_web, (T0,))], [], "변환 없이 서울 세션에서 비교하면 경계가 어긋남")

    def test_db_timezone_setting_follows_web_session(self):
        """웹 세션이 Asia/Seoul(계정 기본값 등)이면 좋아요가 서울 naive로 저장된다. HOT_SHARE_DB_TIMEZONE도 같아야 맞는다."""
        inside, outside = self.post(), self.post()
        for pid, delta in ((inside, timedelta(hours=2)), (outside, -timedelta(hours=2))):
            self.like(pid, 9, tz="Asia/Seoul")
            self.like(pid, 1, T0 - timedelta(days=7) + delta, tz="Asia/Seoul", first_member=20)
        self.assertEqual(self.web_ids(T0, self.make_repo(db_tz="Asia/Seoul")), [inside])
        # 서울 naive 값을 UTC로 해석하면 9시간 더 최근으로 보여 7일이 지난 좋아요까지 센다: 설정 불일치 = 웹과 다른 결과
        self.assertEqual(self.web_ids(T0, self.make_repo(db_tz="UTC")), [inside, outside],
                         "설정이 웹 세션과 다르면 결과가 달라진다 (운영 확인 필수)")

    def test_public_board_filter(self):
        self.baseline_empty()
        boards = {
            "free": self.free,
            "course": self.board("데이터 3기", course_code="data-ml", cohort=3),
            "cohort_only": self.board("기수만", cohort=4),
            "national": self.board("전국", scope_type="NATIONAL"),
            "national_all": self.board("전국 인증", scope_type="NATIONAL", read_policy="ALL_VERIFIED"),
            "institution": self.board("기관", scope_type="INSTITUTION", institution_id=1),
            "program": self.board("과정", scope_type="PROGRAM", program_id=1),
            "cohort": self.board("기수", scope_type="COHORT", cohort_id=1),
            "notice": self.board("공지사항"),
            "user_made": self.board("회원이 만든 게시판", read_policy="ALL_VERIFIED"),
        }
        posts = {}
        for key, bid in boards.items():
            posts[key] = self.post(bid)
            self.like(posts[key], 10)
        web = set(self.web_ids())
        self.assertEqual(web, {v for k, v in posts.items() if k != "notice"}, "웹 HOT은 범위 제한 게시판도 포함(회원별 권한으로 거름)")
        claims = self.repo.claim_hot(T0, limit=50, max_attempts=3, stale_minutes=15)
        self.assertEqual(self.claimed_ids(claims), sorted([posts["free"], posts["user_made"]]))

    def test_excluded_posts(self):
        self.baseline_empty()
        ok = self.post()
        excluded = [self.post(deleted=True), self.post(status="HIDDEN"), self.post(status="DRAFT"), self.post(status=None),
                    self.post(post_type="RECRUIT"), self.post(post_type="CAREER")]
        recruit_linked = self.post()
        self.admin.execute("INSERT INTO recruits (post_id) VALUES (%s)", (recruit_linked,))
        excluded.append(recruit_linked)
        for pid in [ok, *excluded]:
            self.like(pid, 10)
        mixed = self.post()                                   # 좋아요 9 + 스크랩/신고는 HOT 집계에 포함되지 않는다
        self.like(mixed, 9)
        self.like(mixed, 5, kind="SCRAP", first_member=20)
        self.like(mixed, 3, kind="REPORT", first_member=30)
        self.assertEqual(self.web_ids(), [ok])
        self.assertEqual(self.claimed_ids(self.repo.claim_hot(T0, limit=50, max_attempts=3, stale_minutes=15)), [ok])


class WebParityTests(PgCase):
    """backend의 실제 list_featured_posts(kind='hot')와 같은 DB에서 결과를 비교한다."""

    def backend_hot(self, *, session_tz=None, limit=None, allowed=None):
        import psycopg2
        from psycopg2.extras import RealDictCursor
        sys.path.insert(0, str(REPO / "backend"))
        from app.repositories import board_repository
        kwargs = {"options": f"-c TimeZone={session_tz}"} if session_tz else {}
        conn = psycopg2.connect(DSN, **kwargs)
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                extra = {"limit": limit} if limit is not None else {}
                rows = board_repository.list_featured_posts(cur, "hot", "", 1, allowed_board_ids=allowed, **extra)
            return [r["id"] for r in rows]
        finally:
            conn.close()

    def seed_relative_to_db_now(self, web_tz):
        """웹 세션 시간대 web_tz에서 DEFAULT CURRENT_TIMESTAMP로 저장되는 것과 같은 naive 값으로 좋아요를 넣는다."""
        db_now = self.admin.execute("SELECT now()").fetchone()[0]
        restricted = self.board("기수 게시판", course_code="data-ml", cohort=2)
        cohort = self.board("COHORT 게시판", scope_type="COHORT", cohort_id=9)
        notice = self.board("공지사항")
        cases = []
        for i, (board, recent, older, kind) in enumerate([
                (self.free, 10, 0, "ok"), (self.free, 12, 3, "ok"), (self.free, 9, 30, "no"), (restricted, 10, 0, "ok"),
                (cohort, 11, 0, "ok"), (notice, 15, 0, "no"), (self.free, 10, 0, "deleted"), (self.free, 10, 0, "hidden"),
                (self.free, 10, 0, "recruit"), (self.free, 10, 0, "career")]):
            pid = self.post(board, deleted=kind == "deleted", status="HIDDEN" if kind == "hidden" else "PUBLISHED",
                            post_type="CAREER" if kind == "career" else "BOARD")
            if kind == "recruit":
                self.admin.execute("INSERT INTO recruits (post_id) VALUES (%s)", (pid,))
            self.like(pid, recent, db_now - timedelta(days=7) + timedelta(hours=1), tz=web_tz)
            self.like(pid, older, db_now - timedelta(days=7) - timedelta(hours=1), tz=web_tz, first_member=recent + 1)
            cases.append(pid)
        return db_now, {restricted, cohort}

    def _parity(self, web_tz):
        db_now, restricted_boards = self.seed_relative_to_db_now(web_tz)
        backend = sorted(self.backend_hot(session_tz=web_tz, limit=10_000))
        ours = self.web_ids(db_now, self.make_repo(session_tz="Asia/Seoul", db_tz=web_tz))
        self.assertEqual(ours, backend)
        self.assertEqual(len(backend), 4)
        # Discord 후보 = 웹 HOT 중 공개 게시판(backend 결과를 테스트가 독립적으로 거른 값)과 같다
        board_of = dict(self.admin.execute("SELECT post_id, board_id FROM posts").fetchall())
        expected = sorted(pid for pid in backend if board_of[pid] not in restricted_boards)
        self.mark_baseline_done()
        claims = self.make_repo(db_tz=web_tz).claim_hot(db_now, limit=100, max_attempts=3, stale_minutes=15)
        self.assertEqual(self.claimed_ids(claims), expected)

    def test_same_result_as_backend_web_session_utc(self):
        self._parity("UTC")

    def test_same_result_as_backend_web_session_seoul(self):
        self._parity("Asia/Seoul")

    def test_web_limit_100_does_not_drop_candidates(self):
        db_now = self.admin.execute("SELECT now()").fetchone()[0]
        self.admin.execute("""
            INSERT INTO posts (board_id, author_member_id, post_type, post_status, title, created_at)
            SELECT %s, 1, 'BOARD', 'PUBLISHED', 'bulk ' || g, LOCALTIMESTAMP FROM generate_series(1, 105) AS g""", (self.free,))
        self.admin.execute("""
            INSERT INTO post_reactions (post_id, member_id, reaction_type, created_at)
            SELECT p.post_id, m, 'LIKE', LOCALTIMESTAMP - INTERVAL '1 hour' FROM posts p CROSS JOIN generate_series(1, 10) AS m""")
        self.assertEqual(len(self.backend_hot()), 100, "웹 화면은 100개까지만 보여 준다")
        self.assertEqual(len(self.backend_hot(limit=10_000)), 105)
        self.mark_baseline_done()
        claimed = []
        for _ in range(4):
            out = self.repo.claim_hot(db_now, limit=50, max_attempts=3, stale_minutes=15)
            claimed += self.claimed_ids(out)
        self.assertEqual(len(claimed), 105)
        self.assertEqual(len(set(claimed)), 105)


# -- BASELINE ---------------------------------------------------------------------------------------------------------
class BaselineTests(PgCase):
    def test_relay_blocked_before_baseline(self):
        pid = self.post()
        self.like(pid, 10)
        p = self.pipe()
        self.assertEqual(db_lambda.handler({"action": "hot_relay"}, service=p.service), {"skipped": BASELINE_REQUIRED})
        self.assertEqual((self.rows(), p.queue.messages), ([], []))

    def test_baseline_marks_existing_hot_and_is_idempotent(self):
        restricted = self.board("기수", scope_type="COHORT", cohort_id=3)
        a, b, c = self.post(), self.post(restricted), self.post()
        self.like(a, 10)
        self.like(b, 12)
        self.like(c, 9)
        p = self.pipe()
        first = db_lambda.handler({"action": "hot_baseline"}, service=p.service)
        self.assertEqual((first["already_completed"], first["baseline_rows"]), (False, 2))
        self.assertEqual(self.rows(), [{"post_id": a, "status": "BASELINE", "attempt_count": 0},
                                       {"post_id": b, "status": "BASELINE", "attempt_count": 0}])
        second = p.service.baseline(T0 + timedelta(hours=1))
        self.assertEqual((second["already_completed"], second["baseline_rows"]), (True, 0))
        self.like(a, 5, first_member=20)                       # baseline 글은 좋아요가 늘어도 공유하지 않는다
        self.assertEqual(p.cycle()[0]["claimed"], 0)
        self.like(c, 1, first_member=20)                       # baseline 이후 HOT 진입 = 신규
        relay, applied = p.at(T0 + timedelta(minutes=5)).cycle()
        self.assertEqual((relay["claimed"], applied), (1, ["applied"]))
        self.assertEqual([m["embeds"][0]["footer"]["text"] for m in p.hot_messages()], [f"ref:hot-{c}"])
        summary = db_lambda.handler({"action": "hot_summary"}, service=p.service)
        self.assertEqual((summary["BASELINE"], summary["SENT"], summary["SENT_POST_NOT_SHAREABLE"]), (2, 1, []))
        self.assertIsNotNone(summary["baseline_completed_at"])

    def wait_until_waiting(self, app):
        for _ in range(200):
            n = self.admin.execute("SELECT COUNT(*) FROM pg_stat_activity WHERE application_name = %s AND wait_event_type = 'Lock'",
                                   (app,)).fetchone()[0]
            if n:
                return
            time.sleep(0.05)
        self.fail(f"{app} 연결이 잠금 대기에 들어가지 않았습니다.")

    def test_like_arriving_during_baseline_is_shared_once_and_relay_waits(self):
        """baseline 문장의 스냅샷 이후, 커밋 전에 HOT이 된 글: BASELINE이 아니고 relay가 정확히 1번 선점한다."""
        e, d = self.post(), self.post()
        self.like(e, 10)
        self.like(d, 9)
        holder = self.psycopg.connect(DSN)                     # baseline의 INSERT가 e에서 멈추도록 같은 PK를 미커밋으로 잡는다
        self._extra.append(holder)
        holder.execute("INSERT INTO hot_discord_shares (post_id, status) VALUES (%s, 'SKIPPED')", (e,))
        base_repo = self.make_repo(app="hot_baseline_t")
        relay_repo = self.make_repo(app="hot_relay_t")
        out = {}
        tb = threading.Thread(target=lambda: out.setdefault("baseline", base_repo.baseline(T0)))
        tb.start()
        self.wait_until_waiting("hot_baseline_t")              # baseline: lock 획득 + 스냅샷 후 e 충돌로 대기 중
        tr = threading.Thread(target=lambda: out.setdefault(
            "relay", relay_repo.claim_hot(T0, limit=10, max_attempts=3, stale_minutes=15)))
        tr.start()
        self.wait_until_waiting("hot_relay_t")                 # relay: 같은 advisory lock 대기 (Scheduler 동시 실행)
        self.like(d, 1, first_member=20)                       # baseline 도중 d가 HOT이 된다 (커밋)
        holder.rollback()
        tb.join(10)
        tr.join(10)
        self.assertEqual(out["baseline"]["baseline_rows"], 1)
        self.assertEqual(self.claimed_ids(out["relay"]), [d])
        self.assertEqual({r["post_id"]: r["status"] for r in self.rows()}, {e: "BASELINE", d: "PENDING"})
        self.assertEqual(self.repo.claim_hot(T0, limit=10, max_attempts=3, stale_minutes=15), [])

    def test_concurrent_baselines_and_relays(self):
        a, b = self.post(), self.post()
        self.like(a, 10)
        self.like(b, 10)
        repos = [self.make_repo(app=f"hot_c{i}") for i in range(6)]
        for r in repos:
            r.baseline_completed_at()                          # 연결을 미리 열어 동시에 출발하게 한다
        barrier = threading.Barrier(6)
        results = [None] * 6

        def run(i):
            barrier.wait()
            results[i] = (repos[i].baseline(T0) if i < 2 else
                          repos[i].claim_hot(T0, limit=10, max_attempts=3, stale_minutes=15))
        threads = [threading.Thread(target=run, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(15)
        self.assertEqual(sorted(r["baseline_rows"] for r in results[:2]), [0, 2])
        self.assertEqual(sorted(r["already_completed"] for r in results[:2]), [False, True])
        for relay in results[2:]:
            self.assertIn(relay, (BASELINE_REQUIRED, []))
        self.assertEqual([r["status"] for r in self.rows()], ["BASELINE", "BASELINE"])


# -- 발송·중복·복구 ----------------------------------------------------------------------------------------------------
class DeliveryTests(PgCase):
    def setUp(self):
        super().setUp()
        self.baseline_empty()

    def test_concurrent_relays_claim_each_post_once(self):
        pids = [self.post() for _ in range(3)]
        for pid in pids:
            self.like(pid, 10)
        pipes = [self.pipe(self.make_repo(app=f"hot_r{i}")) for i in range(4)]
        for p in pipes:
            p.service.repo.baseline_completed_at()
        barrier = threading.Barrier(4)
        outs = [None] * 4

        def run(i):
            barrier.wait()
            outs[i] = pipes[i].relay()
        threads = [threading.Thread(target=run, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(15)
        self.assertEqual(sum(o["claimed"] for o in outs), 3)
        units = [j["unit_id"] for p in pipes for j in p.send_jobs()]
        self.assertEqual(sorted(units), sorted(f"hot-{pid}" for pid in pids))

    def test_duplicate_sqs_delivery_sends_once(self):
        pid = self.post(title="중복 전달")
        self.like(pid, 10)
        p = self.pipe()
        p.relay()
        body = p.queue.bodies(SEND_Q)[0]
        p.queue.send(SEND_Q, body)                             # 같은 작업이 두 번 전달됨
        first = p.worker.process(contract.loads(body))
        second = p.worker.process(contract.loads(body), receive_count=2)
        self.assertEqual(len(p.hot_messages()), 1)
        self.assertEqual(first["message_id"], second["message_id"])
        for r in (first, second, second):
            p.queue.send(RESULT_Q, contract.dumps(r))
        self.assertEqual(p.apply_results(), ["applied", "duplicate", "duplicate"])
        self.assertEqual(self.row(pid)["discord_message_id"], first["message_id"])

    def test_timeout_unknown_is_not_resent_until_absence_is_proven(self):
        pid = self.post()
        self.like(pid, 10)
        p = self.pipe()
        p.discord.seed(T0 - timedelta(days=1))                # 확인 조회가 선점 시각 이전까지 닿게 하는 이전 메시지
        p.discord.fail_post = ["500"]                          # 5xx: 전송됐는지 알 수 없음
        relay, applied = p.cycle()
        self.assertEqual((p.results[-1]["outcome"], self.row(pid)["status"]), ("UNKNOWN", "UNKNOWN"))
        self.assertEqual(p.at(T0 + timedelta(minutes=10)).cycle()[0]["recover"]["verify_jobs"], 0, "정착 대기 중엔 확인도 안 함")
        out, applied = p.at(T0 + timedelta(minutes=31)).cycle()
        self.assertEqual((out["claimed"], out["recover"]["verify_jobs"], p.results[-1]["outcome"]), (0, 1, "ABSENT_PROVEN"))
        self.assertEqual((self.row(pid)["status"], self.row(pid)["absent_count"]), ("UNKNOWN", 1), "한 번의 '없음'으로는 확정하지 않음")
        out, applied = p.at(T0 + timedelta(minutes=42)).cycle()
        self.assertEqual(self.row(pid)["status"], "FAILED")
        out, applied = p.at(T0 + timedelta(minutes=43)).cycle()   # 미전송 증명 후 재선점 (여전히 HOT·공개·미삭제)
        self.assertEqual((out["claimed"], applied, self.row(pid)["status"]), (1, ["applied"], "SENT"))
        self.assertEqual((len(p.hot_messages()), self.row(pid)["attempt_count"]), (1, 2))

    def test_server_stored_despite_error_is_detected_by_marker(self):
        pid = self.post()
        self.like(pid, 10)
        p = self.pipe()
        p.discord.fail_post = ["store500"]
        p.cycle()
        self.assertEqual((self.row(pid)["status"], len(p.hot_messages())), ("SENT", 1))

    def test_late_store_after_timeout_found_by_verify_not_resent(self):
        pid = self.post()
        self.like(pid, 10)
        p = self.pipe()
        p.discord.fail_post = ["late500"]
        p.cycle()
        self.assertEqual(self.row(pid)["status"], "UNKNOWN")
        p.discord.release_delayed(T0 + timedelta(seconds=30))
        p.at(T0 + timedelta(minutes=31)).cycle()
        self.assertEqual((self.row(pid)["status"], len(p.hot_messages())), ("SENT", 1))

    def test_expired_job_not_sent_and_reclaimed(self):
        pid = self.post()
        self.like(pid, 10)
        p = self.pipe()
        p.relay()
        p.at(T0 + timedelta(minutes=4)).run_worker()           # not_after(3분) 경과
        p.apply_results()
        self.assertEqual((p.results[-1]["outcome"], self.row(pid)["status"], len(p.hot_messages())), ("EXPIRED", "FAILED", 0))
        self.assertEqual(p.cycle()[0]["claimed"], 1)
        self.assertEqual(self.row(pid)["status"], "SENT")

    def test_failed_retry_reclaim_rechecks_post_and_board(self):
        boards = [self.board(f"b{i}") for i in range(4)]
        deleted, hidden, scoped, control = [self.post(b) for b in boards]
        for pid in (deleted, hidden, scoped, control):
            self.like(pid, 10)
        p = self.pipe()
        p.discord.fail_post = ["429"] * 8                      # 4건 x (최초 + 재시도 1회): 실행되지 않았음이 확실한 실패
        p.cycle()
        self.assertEqual({r["status"] for r in self.rows()}, {"FAILED"})
        self.admin.execute("UPDATE posts SET deleted_at = LOCALTIMESTAMP WHERE post_id = %s", (deleted,))
        self.admin.execute("UPDATE posts SET post_status = 'HIDDEN' WHERE post_id = %s", (hidden,))
        self.admin.execute("UPDATE boards SET scope_type = 'COHORT', cohort_id = 1 WHERE board_id = %s", (boards[2],))
        out, _ = p.at(T0 + timedelta(minutes=6)).cycle()
        self.assertEqual(out["claimed"], 1)
        self.assertEqual({r["post_id"]: r["status"] for r in self.rows()},
                         {deleted: "FAILED", hidden: "FAILED", scoped: "FAILED", control: "SENT"})
        self.assertEqual([m["embeds"][0]["footer"]["text"] for m in p.hot_messages()], [f"ref:hot-{control}"])

    def test_deleted_after_claim_before_send_is_flagged_not_silent(self):
        """남은 위험 재현: Worker는 DB를 보지 않으므로 선점 후 삭제된 글을 게시할 수 있다. 정상 처리로 넘기지 않고 표시한다."""
        pid = self.post(title="곧 삭제될 글")
        self.like(pid, 10)
        p = self.pipe()
        p.relay()
        self.admin.execute("UPDATE posts SET deleted_at = LOCALTIMESTAMP WHERE post_id = %s", (pid,))
        p.run_worker()
        with self.assertLogs("hot_share", level="ERROR") as logs:
            self.assertEqual(p.apply_results(), ["applied_post_not_shareable"])
        self.assertIn("수동 삭제 필요", logs.output[0])
        self.assertEqual(len(p.hot_messages()), 1, "이미 게시됨 (이번 Issue는 Discord 메시지를 지우지 않는다)")
        gone = p.service.summary(T0)["SENT_POST_NOT_SHAREABLE"]
        self.assertEqual(gone, [{"post_id": pid, "discord_message_id": self.row(pid)["discord_message_id"]}])

    def test_message_contains_no_author_or_body(self):
        pid = self.post(title="좋은 글")
        self.like(pid, 10)
        p = self.pipe()
        p.cycle()
        sent = json.dumps(p.discord.posts[-1], ensure_ascii=False)
        self.assertIn("좋은 글", sent)
        self.assertIn(f"{BASE}/board/{self.free}/posts/{pid}", sent)
        for leaked in ("본문 비밀 내용", "m1", "nickname", "익명"):
            self.assertNotIn(leaked, sent)
        self.assertEqual(p.discord.posts[-1]["allowed_mentions"], {"parse": []})

    def test_no_base_url_claims_nothing(self):
        pid = self.post()
        self.like(pid, 10)
        p = self.pipe(base_url="")
        self.assertEqual(p.relay(), {"skipped": "no_base_url"})
        self.assertEqual(self.rows(), [])


# -- 취업 공유(#163)와 상호 간섭 없음 ------------------------------------------------------------------------------------
class CareerIsolationTests(PgCase):
    def setUp(self):
        super().setUp()
        self.admin.execute("""
            CREATE TABLE career (post_id BIGINT PRIMARY KEY REFERENCES posts(post_id) ON DELETE CASCADE,
                                 category_code VARCHAR(20) NOT NULL, subcategory_code VARCHAR(50) NOT NULL,
                                 details JSONB NOT NULL DEFAULT '{}'::jsonb);
            CREATE VIEW career_posts AS SELECT post_id, category_code, subcategory_code FROM career;""")
        for name in ("013_career_discord_announcements.sql", "048_career_discord_share.sql"):
            self.admin.execute((SQL_DIR / name).read_text(encoding="utf-8"))
        from career_share.repository import PostgresCareerShareRepository
        from career_share.service import CareerShareService
        from repositories.db import Database
        db = Database(lambda: self.psycopg.connect(DSN, autocommit=True))
        self._dbs.append(db)
        self.career_queue = FakeQueue()
        self.career = CareerShareService(PostgresCareerShareRepository(db), self.career_queue, cs.make_settings(),
                                         clock=lambda: T0)
        self.baseline_empty()

    def test_results_and_recovery_stay_in_their_own_table(self):
        cpid = self.post(None, post_type="CAREER", created=T0)
        self.admin.execute("UPDATE posts SET board_id = NULL WHERE post_id = %s", (cpid,))
        self.admin.execute("INSERT INTO career VALUES (%s, 'reviews', 'INTERVIEW', '{}')", (cpid,))
        hpid = self.post()
        self.like(hpid, 10)
        hot = self.pipe()
        self.assertEqual(self.career.relay(T0)["claimed"], 1)
        self.assertEqual(hot.relay()["claimed"], 1)
        cjob = contract.loads(self.career_queue.bodies(cs.SEND_Q)[0])
        hjob = hot.send_jobs()[0]
        self.assertEqual((cjob["unit_id"], hjob["unit_id"]), (f"post-{cpid}", f"hot-{hpid}"))

        def result(job, outcome, **extra):
            return contract.dumps({"v": 1, "type": "result", "job_id": job["job_id"], "unit_id": job["unit_id"], "kind": job["kind"],
                                   "claim_token": job["claim_token"], "outcome": outcome, "completed_at": contract.iso(T0)} | extra)
        sent = {"message_id": "1" * 18, "channel_id": str(CHANNEL)}
        # 결과가 다른 쪽 결과 큐로 잘못 들어와도 반영되지 않는다
        self.assertEqual(self.career.apply_result(result(hjob, "SENT", **sent), T0), "ignored")
        self.assertEqual(hot.service.apply_result(result(cjob, "SENT", **sent), T0), "ignored")
        self.assertEqual(self.row(hpid)["status"], "PENDING")
        self.assertEqual(self.admin.execute("SELECT status FROM career_discord_announcements WHERE post_id = %s",
                                            (cpid,)).fetchone()[0], "PENDING")
        # 둘 다 UNKNOWN이 되어도 각자의 복구 작업은 자기 행만 다룬다
        self.assertEqual(self.career.apply_result(result(cjob, "UNKNOWN"), T0), "applied")
        self.assertEqual(hot.service.apply_result(result(hjob, "UNKNOWN"), T0), "applied")
        later = T0 + timedelta(minutes=31)
        career_tasks = self.career.repo.claim_verifications(later, max_verifies=6, interval_minutes=10, settle_minutes=30)
        hot_tasks = hot.service.repo.claim_verifications(later, max_verifies=6, interval_minutes=10, settle_minutes=30)
        self.assertEqual([t["unit_id"] for t in career_tasks], [f"post-{cpid}"])
        self.assertEqual([t["unit_id"] for t in hot_tasks], [f"hot-{hpid}"])
        career_summary = self.career.summary(later)
        self.assertEqual(career_summary.get("UNKNOWN"), 1)
        self.assertNotIn("BASELINE", career_summary)
        self.assertEqual(hot.service.summary(later)["UNKNOWN"], 1)
        # 취업 작업은 HOT Worker가 처리하지 않는다
        with self.assertRaises(contract.ContractError):
            hot.worker.process(cjob)
        self.assertEqual(hot.discord.posts, [])

    def test_misrouted_jobs_change_no_messages_and_no_rows(self):
        """큐가 뒤바뀌어 연결돼도: 양쪽 Worker 모두 거부, 기존 메시지·두 이력 테이블 상태가 그대로다."""
        cpid = self.post(None, post_type="CAREER", created=T0)
        self.admin.execute("UPDATE posts SET board_id = NULL WHERE post_id = %s", (cpid,))
        self.admin.execute("INSERT INTO career VALUES (%s, 'reviews', 'INTERVIEW', '{}')", (cpid,))
        hpid = self.post()
        self.like(hpid, 10)
        hot = self.pipe()
        self.career.relay(T0)
        hot.relay()
        cjob = contract.loads(self.career_queue.bodies(cs.SEND_Q)[0])
        hjob = hot.send_jobs()[0]
        hot.discord.seed(T0 - timedelta(hours=1), footer="ref:post-999")   # 채널에 이미 있던 메시지
        before_messages = list(hot.discord.messages)
        career_worker = CareerShareWorker(hot.client, 555555555555555555, clock=lambda: T0)
        snapshot = lambda: (self.admin.execute("SELECT * FROM career_discord_announcements ORDER BY post_id").fetchall(),  # noqa: E731
                            self.admin.execute("SELECT * FROM hot_discord_shares ORDER BY post_id").fetchall())
        rows_before = snapshot()
        for worker, job in ((career_worker, hjob), (hot.worker, cjob)):
            out = handle_records({"Records": [{"messageId": "x", "body": contract.dumps(job)}]}, worker, hot.queue, RESULT_Q)
            self.assertEqual(out, {"batchItemFailures": [{"itemIdentifier": "x"}]})
        self.assertEqual(hot.queue.bodies(RESULT_Q), [], "결과를 만들지 않으므로 DB에 반영될 것도 없다")
        self.assertEqual((hot.discord.posts, hot.discord.gets), ([], 0))
        self.assertEqual(hot.discord.messages, before_messages)
        self.assertEqual(snapshot(), rows_before)
        self.assertEqual(self.row(hpid)["status"], "PENDING")


if __name__ == "__main__":
    unittest.main(verbosity=1)
