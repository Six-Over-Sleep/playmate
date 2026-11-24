"""DM 발송 큐 FIFO 전환(Issue #182) 테스트 — AWS·실제 Discord·DB 없이 실행한다.

이 파일이 확인하는 것과 확인하지 않는 것:
  * 확인: 발행기가 넘기는 FIFO 인자(그룹·중복 제거 ID), 기존 표준 큐 호출 호환, DM 서비스 발행 경로(발송·확인 작업),
          그리고 "SQS FIFO의 그룹 규칙(같은 그룹은 앞 메시지가 삭제되기 전에는 다음을 주지 않음)이 지켜진다면" 실제 DmShareWorker가
          R4(429 대기 중 재선점)에서 DM을 한 번만 보내는지 — 로컬 FIFO 흉내(FifoSim)와 실제 스레드 2개로.
  * 확인하지 않음: AWS SQS·Lambda 이벤트 소스가 실제로 그룹 직렬화·5분 중복 제거를 지키는지 (AWS가 보장하는 동작이며 실환경 검증 필요).
"""
import json
import sys
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from career_share import contract  # noqa: E402
from career_share.queues import FakeQueue, SqsPublisher  # noqa: E402
from career_share.worker_lambda import handle_records  # noqa: E402
from dm_share import settings as dm_settings  # noqa: E402
from dm_share.fifo import DmFifoPublisher, fifo_attributes  # noqa: E402
from dm_share.service import DmShareService  # noqa: E402
from dm_share.worker_lambda import DmShareWorker  # noqa: E402

UTC = timezone.utc
FIFO_URL = "https://sqs.ap-northeast-2.amazonaws.com/123456789012/playmate-test-dm-share-send.fifo"
STD_URL = "https://sqs.ap-northeast-2.amazonaws.com/123456789012/playmate-test-dm-share-send"
RESULT_URL = "https://sqs.ap-northeast-2.amazonaws.com/123456789012/playmate-test-dm-share-result"
RECIPIENT = 987654321098765432
DM_CHANNEL = "333333333333333333"


def dm_job(nid=77, token="tok-old-0001", *, ttl=45, job_type="send", job_id=None):
    now = datetime.now(UTC)
    unit = f"dm-{nid}"
    marker = f"ref:{unit}"
    job = {"v": contract.VERSION, "type": job_type, "job_id": job_id or f"{unit}:{token}", "unit_id": unit, "kind": "DM",
           "claim_token": token, "claimed_at": contract.iso(now - timedelta(seconds=2)),
           "not_after": contract.iso(now + timedelta(seconds=ttl)), "marker": marker, "recipient_id": str(RECIPIENT)}
    if job_type == "send":
        job["payload"] = {"embeds": [{"title": "💬 내 게시글에 새 댓글이 달렸어요.", "footer": {"text": marker}}],
                          "allowed_mentions": {"parse": []}}
    return job


def settings(url=FIFO_URL):
    return dm_settings.DmSettings(send_queue_url=url, base_url="https://playmate.example.com", relay_limit=20, job_ttl_seconds=50,
                                  claim_stale_minutes=10, retry_seconds=60, max_attempts=3, verify_interval_minutes=10,
                                  max_verifies=6, verify_settle_minutes=30, absent_required=2)


# ------------------------------------------------------------------------------------------------ 발행기
class RecordingSqsClient:
    def __init__(self):
        self.calls = []

    def send_message(self, **params):
        self.calls.append(params)


class PublisherCompatibilityTests(unittest.TestCase):
    def test_standard_queue_calls_are_unchanged(self):
        """취업·HOT DB 계층과 모든 Worker의 결과 발행은 send(url, body) 그대로: FIFO 인자가 붙지 않는다."""
        client = RecordingSqsClient()
        SqsPublisher(client).send("https://sqs/career-send", "{}")
        self.assertEqual(client.calls, [{"QueueUrl": "https://sqs/career-send", "MessageBody": "{}"}])

    def test_fifo_arguments_are_passed_only_when_given(self):
        client = RecordingSqsClient()
        SqsPublisher(client).send(FIFO_URL, "{}", group_id="dm-1", dedup_id="dm-1:t")
        self.assertEqual(client.calls, [{"QueueUrl": FIFO_URL, "MessageBody": "{}", "MessageGroupId": "dm-1",
                                         "MessageDeduplicationId": "dm-1:t"}])

    def test_publish_error_policy_unchanged(self):
        class Broken:
            def send_message(self, **params):
                raise RuntimeError(f"secret {params['QueueUrl']}")
        from career_share.queues import PublishError
        with self.assertRaises(PublishError) as caught:
            SqsPublisher(Broken()).send(FIFO_URL, "{}", group_id="dm-1", dedup_id="dm-1:t")
        self.assertNotIn(FIFO_URL, str(caught.exception), "오류 메시지에 URL·본문을 넣지 않는다")

    def test_fake_queue_old_signature_and_fifo_dedup(self):
        queue = FakeQueue()
        queue.send("q", "a")
        queue.send(FIFO_URL, "b", group_id="dm-1", dedup_id="x")
        queue.send(FIFO_URL, "b-again", group_id="dm-1", dedup_id="x")      # 같은 중복 제거 ID
        queue.send(FIFO_URL, "c", group_id="dm-1", dedup_id="y")
        self.assertEqual(queue.bodies(), ["a", "b", "c"])
        self.assertEqual([r["deduplicated"] for r in queue.fifo], [False, True, False])


class DmFifoPolicyTests(unittest.TestCase):
    def test_group_is_unit_and_dedup_is_job_id(self):
        self.assertEqual(fifo_attributes(dm_job(77, "t1")), ("dm-77", "dm-77:t1"))
        verify = dm_job(77, "t1", job_type="verify", job_id="dm-77:t1:v1764000000")
        self.assertEqual(fifo_attributes(verify), ("dm-77", "dm-77:t1:v1764000000"))

    def test_reclaim_gets_new_dedup_id_but_republish_of_same_claim_is_deduplicated(self):
        """재선점(새 claim_token)은 정당한 새 작업이라 지워지면 안 되고, 같은 선점의 작업을 두 번 넣으면 하나로 본다."""
        queue = FakeQueue()
        publisher = DmFifoPublisher(queue)
        first, republished, reclaimed = dm_job(77, "t1"), dm_job(77, "t1"), dm_job(77, "t2")
        for job in (first, republished, reclaimed):
            publisher.send(FIFO_URL, contract.dumps(job))
        self.assertEqual([contract.loads(b)["claim_token"] for b in queue.bodies()], ["t1", "t2"])
        self.assertEqual({r["group_id"] for r in queue.fifo}, {"dm-77"})

    def test_only_dm_jobs_enter_the_dm_queue(self):
        publisher = DmFifoPublisher(FakeQueue())
        hot = dm_job(77) | {"kind": "HOT", "unit_id": "hot-77"}
        career = dm_job(77) | {"kind": "IMMEDIATE", "unit_id": "post-77"}
        mismatched = dm_job(77) | {"job_id": "dm-78:t1"}
        for job in (hot, career, mismatched):
            with self.assertRaises(contract.ContractError, msg=job["unit_id"]):
                publisher.send(FIFO_URL, contract.dumps(job))
        with self.assertRaises(contract.ContractError):
            publisher.send(STD_URL, contract.dumps(hot))     # 표준 큐 URL이어도 DM 작업인지는 확인한다

    def test_standard_url_gets_no_fifo_arguments(self):
        queue = FakeQueue()
        DmFifoPublisher(queue).send(STD_URL, contract.dumps(dm_job()))
        self.assertEqual((len(queue.bodies()), queue.fifo), (1, []))

    def test_settings_require_fifo_queue(self):
        self.assertEqual(dm_settings.load_dm_settings({"DM_SHARE_SEND_QUEUE_URL": FIFO_URL}).send_queue_url, FIFO_URL)
        with self.assertRaises(dm_settings.SettingsError):
            dm_settings.load_dm_settings({"DM_SHARE_SEND_QUEUE_URL": STD_URL})

    def test_standard_queue_bypass_only_in_allowed_non_prod_environments(self):
        """DM_SHARE_ALLOW_STANDARD_QUEUE=1은 PLAYMATE_ENVIRONMENT=local/test에서만 통한다. 운영·미지정·알 수 없는 환경은 거부."""
        def load(url, environment=None, allow=None):
            env = {"DM_SHARE_SEND_QUEUE_URL": url}
            if environment is not None:
                env["PLAYMATE_ENVIRONMENT"] = environment
            if allow is not None:
                env["DM_SHARE_ALLOW_STANDARD_QUEUE"] = allow
            return dm_settings.load_dm_settings(env)

        allowed = [(FIFO_URL, "prod", None), (FIFO_URL, "test", None), (FIFO_URL, "prod", "1"),
                   (STD_URL, "local", "1"), (STD_URL, "test", "1"), (STD_URL, " TEST ", "1")]
        for url, environment, allow in allowed:
            self.assertEqual(load(url, environment, allow).send_queue_url, url, (url, environment, allow))
        rejected = [(STD_URL, "prod", "1"), (STD_URL, "production", "1"), (STD_URL, "PROD", "1"), (STD_URL, None, "1"),
                    (STD_URL, "", "1"), (STD_URL, "staging", "1"), (STD_URL, "dev", "1"), (STD_URL, "test", None),
                    (STD_URL, "test", "true"), (STD_URL, "local", "0")]
        for url, environment, allow in rejected:
            with self.assertRaises(dm_settings.SettingsError, msg=(environment, allow)):
                load(url, environment, allow)


class StubRepo:
    """DmShareService.relay / recover가 부르는 메서드만 (DB 없음)."""

    def __init__(self, claims=(), tasks=()):
        self.claims, self.tasks, self.last_breaker = list(claims), list(tasks), {}

    def expire_gateway_claims(self, now):
        return []

    def claim(self, sender, now, *, limit, stale_seconds):
        return self.claims

    def auth_open(self):
        return False

    def claim_verifications(self, now, **kwargs):
        return self.tasks

    def finalize_unverifiable(self, now, **kwargs):
        return []


class DmServicePublishTests(unittest.TestCase):
    def test_relay_and_recover_publish_with_fifo_attributes(self):
        now = datetime.now(UTC)
        notification = {"notification_id": 77, "notification_type": "COMMENT", "post_title": "제목", "post_id": 5,
                        "post_type": "BOARD", "post_board_id": 1}
        claim = {"notification": notification, "claim_token": "t1", "claimed_at": now, "recipient_id": str(RECIPIENT)}
        task = {"unit_id": "dm-55", "claim_token": "t9", "claimed_at": now - timedelta(minutes=40), "recipient_id": str(RECIPIENT),
                "notification_id": 55}
        queue = FakeQueue()
        service = DmShareService(StubRepo([claim], [task]), queue, settings(), clock=lambda: now)
        self.assertIsInstance(service.publisher, DmFifoPublisher)
        out = service.relay(now)
        self.assertEqual((out["published"], out["recover"]["verify_jobs"]), (1, 1))
        send, verify = queue.fifo
        self.assertEqual((send["group_id"], send["dedup_id"]), ("dm-77", "dm-77:t1"))
        self.assertEqual(verify["group_id"], "dm-55")
        self.assertRegex(verify["dedup_id"], r"^dm-55:t9:v\d+$")
        self.assertEqual({r["url"] for r in queue.fifo}, {FIFO_URL})

    def test_wrapping_is_not_doubled(self):
        inner = FakeQueue()
        wrapped = DmFifoPublisher(inner)
        self.assertIs(DmShareService(StubRepo(), wrapped, settings()).publisher, wrapped)


# ------------------------------------------------------------------------------------------------ FIFO 흉내와 동시 처리
class FifoSim:
    """SQS FIFO 그룹 규칙 흉내: 같은 그룹은 가장 앞 메시지가 삭제되기 전에는 다음 메시지를 주지 않는다. 같은 중복 제거 ID는 한 번만.
    fifo=False면 표준 큐처럼 순서·그룹 없이 아무 메시지나 준다 (비교용)."""

    def __init__(self, fifo=True):
        self.fifo, self.lock, self.items, self.seen_dedup, self.seq = fifo, threading.Lock(), [], set(), 0

    def send(self, url, body, *, group_id=None, dedup_id=None):
        with self.lock:
            if self.fifo:
                assert group_id and dedup_id, "FIFO 큐에는 그룹·중복 제거 ID가 필요하다"
                if dedup_id in self.seen_dedup:
                    return
                self.seen_dedup.add(dedup_id)
            self.seq += 1
            self.items.append({"id": f"m{self.seq}", "body": body, "group": group_id, "inflight": False, "receives": 0})

    def receive(self):
        with self.lock:
            busy = {m["group"] for m in self.items if m["inflight"]}
            heads = set()
            for m in self.items:
                if self.fifo:
                    if m["group"] in busy or m["group"] in heads:
                        continue
                    heads.add(m["group"])
                elif m["inflight"]:
                    continue
                m["inflight"] = True
                m["receives"] += 1
                return dict(m)

    def finish(self, message, failures):
        with self.lock:
            item = next(m for m in self.items if m["id"] == message["id"])
            if failures:
                item["inflight"] = False          # 가시성 타임아웃이 지난 것으로 본다 (같은 그룹 맨 앞에서 다시 전달)
            else:
                self.items.remove(item)

    def pending(self):
        with self.lock:
            return len(self.items)


class ConcurrentDiscord:
    """여러 Worker 스레드가 함께 쓰는 가짜 Discord. gate에 등록한 마커의 첫 전송은 release 전까지 멈춘다 (429 대기 흉내)."""

    def __init__(self, gate=()):
        self.lock = threading.Lock()
        self.messages, self.posts = [], []
        self.gate = {marker: (threading.Event(), threading.Event()) for marker in gate}   # (전송 시작, 전송 허용)

    def create_dm_channel(self, recipient_id):
        return {"id": DM_CHANNEL, "type": 1}

    def get_recent_messages(self, channel_id, limit, before=None):
        with self.lock:
            return [] if before else list(reversed(self.messages))

    def get_channel(self, channel_id):
        with self.lock:
            return {"id": DM_CHANNEL, "last_message_id": self.messages[-1]["id"] if self.messages else None}

    def send_message(self, channel_id, *, embeds, allowed_mentions, nonce):
        if nonce in self.gate:
            started, allowed = self.gate.pop(nonce)
            started.set()
            assert allowed.wait(10), "시험 진행 중 전송 허용이 오지 않음"
        with self.lock:
            message = {"id": str(900000000000000000 + len(self.messages)), "embeds": embeds,
                       "timestamp": datetime.now(UTC).isoformat()}
            self.messages.append(message)
            self.posts.append(nonce)
            return {"id": message["id"]}


def run_one(queue, discord, results):
    """Worker 하나가 메시지 하나를 처리한다 (Lambda 이벤트 소스 + handle_records와 같은 흐름). 받을 메시지가 없으면 None."""
    message = queue.receive()
    if message is None:
        return None
    event = {"Records": [{"messageId": message["id"], "body": message["body"],
                          "attributes": {"ApproximateReceiveCount": str(message["receives"])}}]}
    out = handle_records(event, DmShareWorker(discord), results, RESULT_URL)
    queue.finish(message, out["batchItemFailures"])
    return out


def outcomes(results):
    return [(r["claim_token"], r["outcome"]) for r in (contract.loads(b) for b in results.bodies())]


class FifoScenarioTests(unittest.TestCase):
    def start(self, target, *args):
        thread = threading.Thread(target=target, args=args, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 10)
        return thread

    def r4_scenario(self, fifo: bool, *, new_job_ttl=45):
        """시나리오 C: 이전 작업(old)이 Discord 전송 중 429로 대기하는 동안 DB가 같은 알림을 재선점해 새 작업(new)을 넣는다.
        Worker 동시성 2: 두 번째 Worker가 바로 큐를 읽는다."""
        queue, results = FifoSim(fifo), FakeQueue()
        discord = ConcurrentDiscord(gate=["ref:dm-77"])
        started, allowed = discord.gate["ref:dm-77"]
        publisher = DmFifoPublisher(queue)
        url = FIFO_URL if fifo else STD_URL
        old = dm_job(77, "tok-old-0001")
        publisher.send(url, contract.dumps(old))
        worker_a = self.start(run_one, queue, discord, results)
        self.assertTrue(started.wait(10), "이전 작업이 전송(429 대기) 단계에 들어가지 않음")
        new = dm_job(77, "tok-new-0002", ttl=new_job_ttl)          # 60초 뒤 재선점: 새 claim_token, 새 job_id, 같은 unit_id
        publisher.send(url, contract.dumps(new))
        publisher.send(url, contract.dumps(old))                    # 같은 작업을 다시 넣은 경우 (발행 재시도·중복)
        second = run_one(queue, discord, results)                   # 두 번째 Worker
        allowed.set()                                               # 이전 작업의 429 대기가 끝나 전송 완료
        worker_a.join(10)
        rest = []
        while queue.pending():
            rest.append(run_one(queue, discord, results))
        return second, rest, discord, results

    def test_scenario_c_fifo_serializes_same_notification_and_sends_once(self):
        second, rest, discord, results = self.r4_scenario(fifo=True)
        self.assertIsNone(second, "같은 알림 그룹은 이전 작업이 끝나기 전에 두 번째 Worker에 주지 않는다")
        self.assertEqual(discord.posts, ["ref:dm-77"], "DM은 한 번만")
        self.assertEqual(outcomes(results), [("tok-old-0001", "SENT"), ("tok-new-0002", "SENT")],
                         "새 작업은 이전 작업 뒤에 처리되어 마커로 이미 보낸 것을 확인한다 (재게시 없음)")
        new_result = contract.loads(results.bodies()[1])
        self.assertEqual(new_result["message_id"], discord.messages[0]["id"])

    def test_scenario_c_standard_queue_with_concurrency_2_would_duplicate(self):
        """비교: FIFO 없이(표준 큐) 동시성 2면 두 Worker가 동시에 처리해 DM이 두 번 간다 — FIFO 전환 전 구성의 위험 재현."""
        second, rest, discord, results = self.r4_scenario(fifo=False)
        self.assertIsNotNone(second)
        self.assertEqual(len(discord.posts), 2, "표준 큐 + 동시성 2 = R4 중복 DM")

    def test_scenario_c_new_job_after_ttl_is_not_sent(self):
        """이전 작업이 오래 걸려 새 작업의 TTL(50초)이 지나면 보내지 않는다 (EXPIRED -> DB가 다시 선점, 그때 마커로 확인)."""
        second, rest, discord, results = self.r4_scenario(fifo=True, new_job_ttl=-1)
        self.assertEqual(discord.posts, ["ref:dm-77"])
        self.assertEqual(outcomes(results), [("tok-old-0001", "SENT"), ("tok-new-0002", "EXPIRED")])

    def test_scenario_a_duplicate_messages_of_same_notification(self):
        queue = FifoSim()
        publisher = DmFifoPublisher(queue)
        for _ in range(3):
            publisher.send(FIFO_URL, contract.dumps(dm_job(77, "t1")))
        publisher.send(FIFO_URL, contract.dumps(dm_job(77, "t2")))
        self.assertEqual(queue.pending(), 2, "같은 job_id는 중복 제거, 재선점 작업은 남는다")
        first = queue.receive()
        self.assertIsNone(queue.receive(), "같은 알림의 두 번째 작업은 첫 작업이 끝나기 전에 나오지 않는다")
        queue.finish(first, [])
        self.assertEqual(contract.loads(queue.receive()["body"])["claim_token"], "t2")

    def test_scenario_b_different_notifications_run_in_parallel(self):
        queue, results = FifoSim(), FakeQueue()
        discord = ConcurrentDiscord(gate=["ref:dm-1"])
        started, allowed = discord.gate["ref:dm-1"]
        publisher = DmFifoPublisher(queue)
        publisher.send(FIFO_URL, contract.dumps(dm_job(1, "a1")))
        publisher.send(FIFO_URL, contract.dumps(dm_job(2, "b1")))
        worker_a = self.start(run_one, queue, discord, results)
        self.assertTrue(started.wait(10))
        out = run_one(queue, discord, results)                       # dm-1이 전송 대기 중에도 dm-2는 처리된다
        self.assertEqual((out, discord.posts), ({"batchItemFailures": []}, ["ref:dm-2"]))
        allowed.set()
        worker_a.join(10)
        self.assertEqual(sorted(discord.posts), ["ref:dm-1", "ref:dm-2"])

    def test_scenario_d_result_publish_failure_redelivers_in_group_without_resend(self):
        queue, results = FifoSim(), FakeQueue()
        discord = ConcurrentDiscord()
        publisher = DmFifoPublisher(queue)
        publisher.send(FIFO_URL, contract.dumps(dm_job(77, "t1")))
        publisher.send(FIFO_URL, contract.dumps(dm_job(77, "t2")))  # 같은 알림의 다음 작업은 뒤에서 기다린다
        results.fail_next = 1
        with self.assertLogs("career_share", level="WARNING"):
            first = run_one(queue, discord, results)
        self.assertEqual((first["batchItemFailures"] != [], discord.posts), (True, ["ref:dm-77"]))
        again = queue.receive()
        self.assertEqual((contract.loads(again["body"])["claim_token"], again["receives"]), ("t1", 2),
                         "실패한 메시지가 그룹 맨 앞에서 다시 전달된다 (다음 작업 t2가 끼어들지 않음)")
        queue.finish(again, ["retry"])
        while queue.pending():
            run_one(queue, discord, results)
        self.assertEqual(discord.posts, ["ref:dm-77"], "재전달은 마커로 이미 보낸 것을 확인 (재게시 없음)")
        self.assertEqual(outcomes(results), [("t1", "SENT"), ("t2", "SENT")])


class GatewayPolicyUnchangedTests(unittest.TestCase):
    """시나리오 E (정적 확인): FIFO 전환은 DB 공동 선점·Gateway 인수 제한·TTL/재시도 관계를 바꾸지 않는다. DB 동작은 test_dm_share(PG)."""

    def test_gateway_takeover_16_minutes_and_ttl_rules_are_unchanged(self):
        from repositories import dm_delivery_repository as repo
        self.assertEqual(repo.GATEWAY_TAKEOVER_MINUTES, 16)
        for sql in (repo.CANDIDATES_SQL, repo.UPSERT_SQL):
            self.assertIn("make_interval(mins => %(takeover)s)", sql)
            self.assertIn("'LAMBDA'", sql)
        base = {"DM_SHARE_SEND_QUEUE_URL": FIFO_URL}
        self.assertEqual(dm_settings.load_dm_settings(base).job_ttl_seconds, 50)
        with self.assertRaises(dm_settings.SettingsError):
            dm_settings.load_dm_settings(base | {"DM_SHARE_JOB_TTL_SECONDS": "60"})     # TTL >= 재선점 간격 거부 (R4)

    def test_auth_breaker_and_skip_policy_entry_points_exist(self):
        from repositories import dm_delivery_repository as repo
        from services import notification_policy as policy
        self.assertEqual((repo.AUTH_MARK, repo.AUTH_HOLD_MINUTES), ("DISCORD_AUTH_401", 10))
        self.assertEqual(policy.skip_reason({"actor_member_id": 1, "receiver_member_id": 2, "receiver_dm_opt_in": False,
                                             "receiver_discord_id": str(RECIPIENT), "notification_type": "COMMENT"}),
                         "DM 알림 꺼짐")
        self.assertEqual(policy.to_discord_id("w12"), None, "탈퇴 회원(w<id>)은 DM 대상 아님")


if __name__ == "__main__":
    unittest.main()
