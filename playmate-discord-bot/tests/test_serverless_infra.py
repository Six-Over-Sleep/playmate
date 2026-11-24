"""Discord 서버리스 SAM 인프라(infra/discord-serverless) 테스트 — AWS 계정·SAM CLI·실제 Discord 없이 실행한다.

  1. template.yaml 정적 검증: 참조 무결성, 큐·Worker·이벤트 소스 설정, NAT/VPC 부재, IAM 최소 권한, 경보, 초기 비활성
  2. build_package.py: Worker 패키지에 필요한 모듈만 들어가고 DB·Gateway 코드가 없는지, 격리된 인터프리터에서 import되는지
  3. secret_bootstrap: 토큰을 시크릿에서 한 번만 읽고, 값을 로그·예외에 남기지 않으며, 기존 핸들러에 위임하는지
  4. SQS 이벤트 -> 기존 career_share.worker_lambda.handler -> 결과 큐 메시지 (가짜 Discord 클라이언트, 가짜 큐)
PyYAML이 없으면 1은 건너뛴다 (`.venv`(저장소 루트)에는 있다).
"""
import importlib
import importlib.util
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
INFRA = REPO / "infra" / "discord-serverless"
TEMPLATE = INFRA / "template.yaml"
sys.path.insert(0, str(ROOT))

try:
    import yaml
except ImportError:  # 봇 전용 가상환경에는 PyYAML이 없다
    yaml = None

FAKE_TOKEN = "fake-token-for-tests-0123456789"   # 실제 토큰이 아니다
SECRET_ARN = "arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:playmate/test/discord-bot-token-AbCdEf"
RESULT_Q = "https://sqs.ap-northeast-2.amazonaws.com/123456789012/playmate-test-career-share-result"
CHANNEL = 111111111111111111


# ------------------------------------------------------------------------------------------------ 템플릿 로더
def _cfn_loader():
    class Loader(yaml.SafeLoader):
        pass

    def construct(tag):
        def build(loader, node):
            if isinstance(node, yaml.ScalarNode):
                value = loader.construct_scalar(node)
                if tag == "GetAtt" and isinstance(value, str):
                    value = value.split(".", 1)
            elif isinstance(node, yaml.SequenceNode):
                value = loader.construct_sequence(node, deep=True)
            else:
                value = loader.construct_mapping(node, deep=True)
            return {("Ref" if tag == "Ref" else f"Fn::{tag}"): value}
        return build

    for tag in ("Ref", "Sub", "GetAtt", "If", "Equals", "Not", "And", "Or", "Select", "Join", "Split", "ImportValue",
                "FindInMap", "GetAZs", "Base64", "Condition"):
        Loader.add_constructor(f"!{tag}", construct(tag))
    return Loader


def load_template() -> dict:
    return yaml.load(TEMPLATE.read_text(encoding="utf-8"), Loader=_cfn_loader())


def walk(node):
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


PSEUDO = {"AWS::Region", "AWS::AccountId", "AWS::StackName", "AWS::StackId", "AWS::Partition", "AWS::URLSuffix", "AWS::NoValue"}


@unittest.skipUnless(yaml, "PyYAML 없음: 템플릿 정적 검증 미실시")
class TemplateStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = load_template()
        cls.res = cls.t["Resources"]
        cls.params = cls.t["Parameters"]
        cls.fn = cls.res["CareerShareWorkerFunction"]["Properties"]

    def test_references_resolve(self):
        known = set(self.res) | set(self.params) | PSEUDO
        for node in walk(self.t):
            if isinstance(node, dict) and "Ref" in node:
                self.assertIn(node["Ref"], known, f"Ref 대상 없음: {node['Ref']}")
            if isinstance(node, dict) and "Fn::GetAtt" in node:
                self.assertIn(node["Fn::GetAtt"][0], self.res, f"GetAtt 대상 없음: {node['Fn::GetAtt']}")
            if isinstance(node, dict) and "Fn::If" in node:
                self.assertIn(node["Fn::If"][0], self.t["Conditions"])
            if isinstance(node, dict) and "Fn::Sub" in node and isinstance(node["Fn::Sub"], str):
                import re
                for var in re.findall(r"\$\{([^}!]+)\}", node["Fn::Sub"]):
                    self.assertIn(var.split(".")[0], known, f"Sub 변수 없음: {var}")

    def test_only_expected_resource_types_and_no_network_or_scheduler(self):
        types = {r["Type"] for r in self.res.values()}
        self.assertEqual(types, {"AWS::SQS::Queue", "AWS::Logs::LogGroup", "AWS::IAM::Role", "AWS::Serverless::Function",
                                 "AWS::Lambda::EventSourceMapping", "AWS::CloudWatch::Alarm", "AWS::Logs::MetricFilter"})
        self.assertNotIn("Events", self.fn, "이벤트 소스는 명시적 EventSourceMapping 하나만 (SAM 이벤트와 중복 금지)")
        for forbidden in ("NatGateway", "EC2::", "Scheduler", "Events::Rule", "RDS", "SecretsManager::Secret", "SNS::Topic"):
            self.assertFalse(any(forbidden in t for t in types), forbidden)
        self.assertNotIn("VpcConfig", self.fn, "Worker는 고객 VPC에 연결하지 않는다")

    def test_names_are_environment_scoped(self):
        for name, resource in self.res.items():
            props = resource.get("Properties", {})
            for key in ("QueueName", "FunctionName", "LogGroupName", "AlarmName"):
                if key in props and "Ref" not in props[key]:          # Ref는 이미 환경별 이름을 가진 리소스를 가리킨다
                    self.assertIn("${EnvironmentName}", props[key]["Fn::Sub"], f"{name}.{key}")
        self.assertEqual(self.params["EnvironmentName"]["AllowedValues"], ["test", "prod"])

    def test_worker_reuses_existing_handler_through_bootstrap(self):
        env = self.fn["Environment"]["Variables"]
        self.assertEqual(self.fn["Handler"], "secret_bootstrap.handler")
        self.assertEqual(env["WORKER_TARGET_HANDLER"], "career_share.worker_lambda.handler")
        self.assertEqual(self.fn["Runtime"], "python3.13")       # 코드는 3.10+ 문법 (X | None)
        self.assertEqual(self.fn["CodeUri"], ".build/career_worker/")
        self.assertNotIn("DISCORD_BOT_TOKEN", env, "토큰 값은 환경변수·템플릿에 넣지 않는다")
        self.assertEqual(env["DISCORD_BOT_TOKEN_SECRET_ARN"], {"Ref": "DiscordBotTokenSecretArn"})
        self.assertEqual(env["CAREER_SHARE_CHANNEL_ID"], {"Ref": "CareerShareChannelId"})
        self.assertEqual(env["CAREER_SHARE_RESULT_QUEUE_URL"], {"Ref": "CareerShareResultQueue"})
        for key in env:
            self.assertFalse(key.startswith("DB_"), "Worker에 DB 설정을 주지 않는다")

    def test_channel_and_secret_have_no_defaults(self):
        for name in ("CareerShareChannelId", "DiscordBotTokenSecretArn"):
            self.assertNotIn("Default", self.params[name], f"{name}은 배포 때 외부에서 넣는다")
        self.assertEqual(self.params["AlarmTopicArn"]["Default"], "", "SNS ARN 없이도 검증·배포 가능")

    def test_event_source_and_concurrency(self):
        mapping = self.res["CareerShareWorkerSendQueueMapping"]
        self.assertEqual(mapping["Type"], "AWS::Lambda::EventSourceMapping")
        props = mapping["Properties"]
        self.assertEqual(props["BatchSize"], 1)
        self.assertEqual(props["FunctionResponseTypes"], ["ReportBatchItemFailures"])
        self.assertEqual(props["EventSourceArn"], {"Fn::GetAtt": ["CareerShareSendQueue", "Arn"]})
        self.assertEqual(props["FunctionName"], {"Ref": "CareerShareWorkerFunction"})
        maximum = props["ScalingConfig"]["MaximumConcurrency"]
        self.assertGreaterEqual(maximum, 2, "AWS 최솟값은 2 (1은 배포 실패)")
        self.assertGreaterEqual(self.fn["ReservedConcurrentExecutions"], maximum,
                                "예약 동시성 < 최대 동시성이면 스로틀이 상시 발생한다 (AWS 권장: 예약 >= 최대)")
        self.assertEqual(self.fn["ReservedConcurrentExecutions"], maximum, "동시 실행은 필요한 최소(2)로 제한")
        self.assertEqual(props["Enabled"], {"Fn::If": ["EnableCareerWorker", True, False]})
        self.assertEqual(self.params["CareerWorkerEventSourceEnabled"]["Default"], "false", "배포만으로 발송이 시작되지 않는다")
        self.assertEqual(self.t["Conditions"]["EnableCareerWorker"], {"Fn::Equals": [{"Ref": "CareerWorkerEventSourceEnabled"}, "true"]})

    def test_queue_timeouts_retention_and_redrive(self):
        send = self.res["CareerShareSendQueue"]["Properties"]
        result = self.res["CareerShareResultQueue"]["Properties"]
        self.assertGreaterEqual(send["VisibilityTimeout"], 6 * self.fn["Timeout"], "AWS 권장: 가시성 타임아웃 >= 함수 타임아웃 x 6")
        self.assertEqual(send["RedrivePolicy"]["deadLetterTargetArn"], {"Fn::GetAtt": ["CareerShareSendDLQ", "Arn"]})
        self.assertGreaterEqual(send["RedrivePolicy"]["maxReceiveCount"], 5)
        self.assertEqual(result["RedrivePolicy"]["deadLetterTargetArn"], {"Fn::GetAtt": ["CareerShareResultDLQ", "Arn"]})
        self.assertGreaterEqual(send["MessageRetentionPeriod"], 86400)
        self.assertEqual(result["MessageRetentionPeriod"], 1209600, "소비자 배포 전 결과 보존 (최대 14일)")
        for name in ("CareerShareSendQueue", "CareerShareSendDLQ", "CareerShareResultQueue", "CareerShareResultDLQ"):
            self.assertTrue(self.res[name]["Properties"]["SqsManagedSseEnabled"], name)
            self.assertNotIn("FifoQueue", self.res[name]["Properties"], "표준 큐")

    def test_iam_least_privilege(self):
        role = self.res["CareerShareWorkerRole"]["Properties"]
        self.assertNotIn("ManagedPolicyArns", role)
        statements = []
        for policy in role["Policies"]:
            for statement in policy["PolicyDocument"]["Statement"]:
                if "Fn::If" in statement:
                    statements.append(statement["Fn::If"][1])
                else:
                    statements.append(statement)
        allowed = {"logs:CreateLogStream", "logs:PutLogEvents", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes",
                   "sqs:SendMessage", "secretsmanager:GetSecretValue", "kms:Decrypt"}
        for statement in statements:
            self.assertEqual(statement["Effect"], "Allow")
            actions = statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
            self.assertTrue(set(actions) <= allowed, actions)
            self.assertNotEqual(statement["Resource"], "*")
            self.assertFalse(any("*" in a for a in actions))
        by_sid = {s["Sid"]: s for s in statements}
        self.assertEqual(by_sid["ConsumeSendQueue"]["Resource"], {"Fn::GetAtt": ["CareerShareSendQueue", "Arn"]})
        self.assertEqual(by_sid["PublishResults"]["Resource"], {"Fn::GetAtt": ["CareerShareResultQueue", "Arn"]})
        self.assertEqual(by_sid["ReadDiscordTokenSecret"]["Resource"], {"Ref": "DiscordBotTokenSecretArn"})
        self.assertIn("kms:ViaService", by_sid["DecryptTokenSecretViaSecretsManager"]["Condition"]["StringEquals"])
        kms = next(s for p in role["Policies"] for s in p["PolicyDocument"]["Statement"] if "Fn::If" in s)
        self.assertEqual(kms["Fn::If"][0], "HasSecretKmsKey")
        self.assertEqual(kms["Fn::If"][2], {"Ref": "AWS::NoValue"}, "KMS 키를 안 쓰면 kms 권한 없음")

    def test_alarms(self):
        alarms = {r["Properties"]["AlarmName"]["Fn::Sub"]: r["Properties"] for r in self.res.values()
                  if r["Type"] == "AWS::CloudWatch::Alarm"}
        names = {name.replace("playmate-${EnvironmentName}-", "") for name in alarms}
        self.assertTrue({"career-share-worker-errors", "career-share-worker-throttles", "career-share-send-dlq-not-empty",
                         "career-share-result-dlq-not-empty", "career-share-result-queue-stale"} <= names, names)
        self.assertEqual(self.params["ThrottleAlarmThreshold"]["Default"], 1, "예약 = 최대 동시성이라 스로틀은 1건이면 이상")
        stale = alarms["playmate-${EnvironmentName}-career-share-result-queue-stale"]
        self.assertLessEqual(stale["Threshold"], 86400, "결과가 14일 보존을 넘겨 사라지기 훨씬 전에 알린다")
        for props in alarms.values():
            self.assertEqual(props["AlarmActions"], {"Fn::If": ["HasAlarmTopic", [{"Ref": "AlarmTopicArn"}], {"Ref": "AWS::NoValue"}]})
            self.assertEqual(props["TreatMissingData"], "notBreaching")
        dlq = alarms["playmate-${EnvironmentName}-career-share-send-dlq-not-empty"]
        self.assertEqual((dlq["MetricName"], dlq["Threshold"], dlq["ComparisonOperator"]),
                         ("ApproximateNumberOfMessagesVisible", 1, "GreaterThanOrEqualToThreshold"))

    def test_token_version_forces_new_environments(self):
        env = self.fn["Environment"]["Variables"]
        self.assertEqual(env["DISCORD_BOT_TOKEN_VERSION"], {"Ref": "DiscordBotTokenVersion"})
        self.assertIn("Default", self.params["DiscordBotTokenVersion"])

    def test_error_log_filter_matches_lambda_text_format(self):
        """Python 런타임 텍스트 로그: "[ERROR]\\t<시각>\\t<요청 ID>\\t메시지", 처리되지 않은 예외: "[ERROR] 예외명: ..." """
        flt = self.res["CareerShareWorkerErrorLogMetric"]["Properties"]
        self.assertEqual(flt["FilterPattern"], '"[ERROR]"')
        self.assertEqual(self.fn["LoggingConfig"]["LogFormat"], "Text", "JSON 형식이면 이 필터가 맞지 않는다")
        self.assertEqual(flt["LogGroupName"], {"Ref": "CareerShareWorkerLogGroup"})
        self.assertEqual(self.fn["LoggingConfig"]["LogGroup"], {"Ref": "CareerShareWorkerLogGroup"})

    def test_no_secret_like_literals_in_template(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        for marker in ("discord.com/api/webhooks", "Bot ", "MTA", "xoxb-", "password"):
            self.assertNotIn(marker, text)


# ------------------------------------------------------------------------------------------------ 패키지
class PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "career_worker"
        spec = importlib.util.spec_from_file_location("build_package", INFRA / "build_package.py")
        cls.builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.builder)
        with redirect_stdout(io.StringIO()):
            cls.copied = cls.builder.build("career_worker", cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_contains_only_worker_modules(self):
        files = sorted(str(p.relative_to(self.out)).replace("\\", "/") for p in self.out.rglob("*") if p.is_file())
        self.assertEqual(files, sorted(self.copied + ["requirements.txt"]))
        for excluded in ("career_share/db_lambda.py", "career_share/repository.py", "career_share/service.py",
                         "career_share/settings.py", "discord_rest/reuse.py", "bot.py", "config.py"):
            self.assertNotIn(excluded, files)
        self.assertNotIn("psycopg", (self.out / "requirements.txt").read_text(encoding="utf-8").replace("psycopg 금지", ""))

    def test_imports_in_isolated_interpreter_without_db_or_discord_py(self):
        code = ("import sys, secret_bootstrap, career_share.worker_lambda;"
                "bad=[m for m in ('psycopg','psycopg2','discord','config','repositories','services','boto3') if m in sys.modules];"
                "print('BAD' if bad else 'OK', bad)")
        # -I: 사용자 site-packages·현재 폴더 무시. PYTHONPATH 대신 cwd=패키지 폴더 + -c 의 sys.path[0]=''를 쓴다.
        run = subprocess.run([sys.executable, "-I", "-B", "-c", f"import sys; sys.path.insert(0, {str(self.out)!r}); {code}"],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(run.stdout.startswith("OK"), run.stdout)

    def test_forbidden_import_is_rejected(self):
        bad = Path(self.tmp.name) / "bad.py"
        bad.write_text("import psycopg\nfrom services import web_links\n", encoding="utf-8")
        self.assertEqual(self.builder.forbidden_in(bad), ["psycopg", "services"])


# ------------------------------------------------------------------------------------------------ 부트스트랩 + 흐름
class FakeSecrets:
    def __init__(self, value):
        self.value, self.calls = value, 0

    def get_secret_value(self, SecretId):
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return {"SecretString": self.value, "ARN": SecretId}


class StubDiscord:
    """CareerShareWorker가 쓰는 메서드만 흉내 낸다 (네트워크 없음).

    send_error: 전송 시 낼 예외. store_on_error=True면 예외를 내기 전에 메시지를 저장한다 (서버는 저장했지만 응답 유실).
    lookup_errors: get_recent_messages가 차례로 낼 예외 목록.
    """

    def __init__(self, existing=None, *, send_error=None, store_on_error=False, lookup_errors=None):
        self.existing, self.sent, self.attempts = list(existing or []), [], 0
        self.send_error, self.store_on_error = send_error, store_on_error
        self.lookup_errors = list(lookup_errors or [])

    def get_recent_messages(self, channel_id, limit, before=None):
        if self.lookup_errors:
            raise self.lookup_errors.pop(0)
        return [] if before else list(reversed(self.existing))

    def get_channel(self, channel_id):
        return {"id": str(channel_id), "last_message_id": None}

    def _store(self, embeds):
        message = {"id": str(123456789012345678 + len(self.existing)), "embeds": embeds,
                   "timestamp": datetime.now(timezone.utc).isoformat()}
        self.existing.append(message)
        return message

    def send_message(self, channel_id, *, embeds, allowed_mentions, nonce):
        self.attempts += 1
        if self.send_error is not None:
            if self.store_on_error:
                self.sent.append((channel_id, embeds, nonce))
                self._store(embeds)
            raise self.send_error
        self.sent.append((channel_id, embeds, nonce))
        return {"id": self._store(embeds)["id"]}


def send_job(unit="post-42", token="tok0123456789abc"):
    from career_share import contract
    now = datetime.now(timezone.utc)
    marker = f"ref:{unit}"
    return {"v": contract.VERSION, "type": "send", "job_id": f"{unit}:{token}", "unit_id": unit, "kind": "IMMEDIATE",
            "claim_token": token, "claimed_at": contract.iso(now - timedelta(seconds=5)),
            "not_after": contract.iso(now + timedelta(minutes=10)), "marker": marker,
            "payload": {"embeds": [{"title": "면접 후기", "footer": {"text": marker}}], "allowed_mentions": {"parse": []}}}


def sqs_event(*bodies, receive_count=1):
    """Lambda SQS 이벤트 형태 (필요한 키: messageId, body, attributes.ApproximateReceiveCount)."""
    return {"Records": [{"messageId": f"m{i}", "receiptHandle": "rh", "body": body, "eventSource": "aws:sqs",
                         "attributes": {"ApproximateReceiveCount": str(receive_count)}} for i, body in enumerate(bodies)]}


class BootstrapAndFlowTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(INFRA / "src"))
        import secret_bootstrap
        from career_share import worker_lambda
        self.bootstrap = importlib.reload(secret_bootstrap)
        self.worker_lambda = worker_lambda
        self.addCleanup(setattr, worker_lambda, "_runtime", None)
        self.addCleanup(sys.path.remove, str(INFRA / "src"))
        patcher = mock.patch.dict(os.environ, {"WORKER_TARGET_HANDLER": "career_share.worker_lambda.handler",
                                               "DISCORD_BOT_TOKEN_SECRET_ARN": SECRET_ARN,
                                               "DISCORD_BOT_TOKEN_SECRET_JSON_KEY": ""}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("DISCORD_BOT_TOKEN", None)

    def runtime(self, discord=None, queue=None):
        from career_share.queues import FakeQueue
        from career_share.worker import CareerShareWorker
        discord = discord or StubDiscord()
        queue = queue or FakeQueue()
        self.worker_lambda._runtime = (CareerShareWorker(discord, CHANNEL), RESULT_Q, queue)   # _build(실제 Discord) 대신
        return discord, queue

    def test_token_loaded_once_and_never_logged(self):
        secrets = FakeSecrets(FAKE_TOKEN)
        discord, queue = self.runtime()
        logs, err = io.StringIO(), io.StringIO()
        handler = logging.StreamHandler(logs)
        logging.getLogger().addHandler(handler)
        try:
            with mock.patch.object(self.bootstrap, "_secrets_client", return_value=secrets), redirect_stderr(err):
                from career_share import contract
                for _ in range(2):
                    out = self.bootstrap.handler(sqs_event(contract.dumps(send_job())))
                    self.assertEqual(out, {"batchItemFailures": []})
        finally:
            logging.getLogger().removeHandler(handler)
        self.assertEqual(secrets.calls, 1, "콜드 스타트에 한 번만 조회")
        self.assertEqual(os.environ["DISCORD_BOT_TOKEN"], FAKE_TOKEN)
        self.assertNotIn(FAKE_TOKEN, logs.getvalue() + err.getvalue())
        self.assertNotIn(FAKE_TOKEN, "".join(queue.bodies()))

    def test_json_secret_key(self):
        os.environ["DISCORD_BOT_TOKEN_SECRET_JSON_KEY"] = "token"
        self.bootstrap.load_token(FakeSecrets(json.dumps({"token": FAKE_TOKEN, "other": "x"})))
        self.assertEqual(os.environ["DISCORD_BOT_TOKEN"], FAKE_TOKEN)

    def test_secret_failures_raise_without_value(self):
        cases = [FakeSecrets(""), FakeSecrets("   "), FakeSecrets(RuntimeError(f"AccessDenied {FAKE_TOKEN}"))]
        for secrets in cases:
            os.environ.pop("DISCORD_BOT_TOKEN", None)
            with self.assertRaises(self.bootstrap.TokenSecretError) as caught:
                self.bootstrap.load_token(secrets)
            self.assertNotIn(FAKE_TOKEN, str(caught.exception))
        os.environ["DISCORD_BOT_TOKEN_SECRET_JSON_KEY"] = "missing"
        with self.assertRaises(self.bootstrap.TokenSecretError):
            self.bootstrap.load_token(FakeSecrets(json.dumps({"token": FAKE_TOKEN})))

    def test_unknown_target_rejected_before_reading_secret(self):
        os.environ["WORKER_TARGET_HANDLER"] = "os.system"
        secrets = FakeSecrets(FAKE_TOKEN)
        with mock.patch.object(self.bootstrap, "_secrets_client", return_value=secrets):
            with self.assertRaises(self.bootstrap.TokenSecretError):
                self.bootstrap.handler(sqs_event("{}"))
        self.assertEqual(secrets.calls, 0)

    def test_send_job_produces_result_message(self):
        from career_share import contract
        os.environ["DISCORD_BOT_TOKEN"] = FAKE_TOKEN
        discord, queue = self.runtime()
        job = send_job()
        out = self.bootstrap.handler(sqs_event(contract.dumps(job)))
        self.assertEqual(out, {"batchItemFailures": []})
        self.assertEqual(len(discord.sent), 1)
        self.assertEqual(discord.sent[0][2], job["marker"], "nonce = 마커")
        [(url, body)] = queue.messages
        result = contract.validate_result(contract.loads(body))
        self.assertEqual(url, RESULT_Q)
        self.assertEqual((result["outcome"], result["claim_token"], result["unit_id"], result["message_id"], result["channel_id"]),
                         ("SENT", job["claim_token"], job["unit_id"], "123456789012345678", str(CHANNEL)))

    def test_redelivered_job_found_by_marker_is_not_resent(self):
        from career_share import contract
        os.environ["DISCORD_BOT_TOKEN"] = FAKE_TOKEN
        job = send_job()
        existing = [{"id": "999999999999999999", "timestamp": datetime.now(timezone.utc).isoformat(),
                     "embeds": [{"footer": {"text": job["marker"]}}]}]
        discord, queue = self.runtime(StubDiscord(existing))
        out = self.bootstrap.handler(sqs_event(contract.dumps(job), receive_count=2))
        self.assertEqual((out, discord.sent), ({"batchItemFailures": []}, []))
        self.assertEqual(contract.loads(queue.messages[0][1])["message_id"], "999999999999999999")

    def test_partial_failures(self):
        from career_share import contract
        os.environ["DISCORD_BOT_TOKEN"] = FAKE_TOKEN
        discord, queue = self.runtime()
        with self.assertLogs("career_share", level="WARNING"):
            out = self.bootstrap.handler(sqs_event("not json", contract.dumps(send_job("post-7")), json.dumps({"v": 1})))
        self.assertEqual(out, {"batchItemFailures": [{"itemIdentifier": "m0"}, {"itemIdentifier": "m2"}]},
                         "형식 오류만 실패로 보고 -> 재시도 후 DLQ, 정상 메시지는 삭제")
        self.assertEqual(len(queue.messages), 1)
        queue.fail_next = 1                               # 결과 큐 발행 실패 -> 그 메시지만 재전달 (재전달 시 마커로 중복 방지)
        with self.assertLogs("career_share", level="WARNING"):
            out = self.bootstrap.handler(sqs_event(contract.dumps(send_job("post-8"))))
        self.assertEqual(out, {"batchItemFailures": [{"itemIdentifier": "m0"}]})

    def test_secret_outage_fails_invocation_and_recovers_next_time(self):
        """Secrets Manager 장애: 호출 실패(SQS가 가시성 타임아웃 뒤 재전달) -> 다음 호출에서 다시 읽는다 (실패를 캐시하지 않음)."""
        from career_share import contract
        secrets = FakeSecrets(RuntimeError("ServiceUnavailable"))
        discord, queue = self.runtime()
        with mock.patch.object(self.bootstrap, "_secrets_client", return_value=secrets):
            with self.assertRaises(self.bootstrap.TokenSecretError) as caught:
                self.bootstrap.handler(sqs_event(contract.dumps(send_job())))
            self.assertNotIn(SECRET_ARN, str(caught.exception), "오류 메시지에 시크릿 ARN을 넣지 않는다")
            self.assertEqual((discord.sent, queue.messages), ([], []), "토큰 없이 아무것도 보내지 않음")
            secrets.value = FAKE_TOKEN
            out = self.bootstrap.handler(sqs_event(contract.dumps(send_job())))
        self.assertEqual((out, secrets.calls, len(discord.sent)), ({"batchItemFailures": []}, 2, 1))

    def _run(self, discord, job, receive_count=1):
        from career_share import contract
        os.environ["DISCORD_BOT_TOKEN"] = FAKE_TOKEN
        _, queue = self.runtime(discord)
        out = self.bootstrap.handler(sqs_event(contract.dumps(job), receive_count=receive_count))
        results = [contract.validate_result(contract.loads(body)) for body in queue.bodies()]
        return out, results, queue

    def test_429_is_reported_as_failed_retry_not_sqs_retry(self):
        """429(실행 안 됨)는 결과 FAILED_RETRY로 끝내고 메시지는 삭제된다. 재시도 시각은 DB 계층이 정한다."""
        from discord_rest import errors
        discord = StubDiscord(send_error=errors.DiscordRateLimited("rate limited", status=429, retry_after=1.0))
        with self.assertLogs("career_share", level="INFO"):
            out, results, _ = self._run(discord, send_job())
        self.assertEqual((out, [r["outcome"] for r in results]), ({"batchItemFailures": []}, ["FAILED_RETRY"]))

    def test_5xx_and_timeout_without_marker_are_unknown_never_resent(self):
        from discord_rest import errors
        for error in (errors.DiscordServerError("500", status=500, outcome_unknown=True),
                      errors.DiscordTimeoutError("timeout", outcome_unknown=True)):
            discord = StubDiscord(send_error=error)
            with self.assertLogs("career_share", level="INFO"):
                out, results, _ = self._run(discord, send_job())
            self.assertEqual((out, [r["outcome"] for r in results], discord.attempts),
                             ({"batchItemFailures": []}, ["UNKNOWN"], 1), f"{type(error).__name__}: POST 1회, 재전송 없음")

    def test_5xx_but_stored_is_detected_by_marker_as_sent(self):
        from discord_rest import errors
        discord = StubDiscord(send_error=errors.DiscordServerError("502", status=502, outcome_unknown=True), store_on_error=True)
        with self.assertLogs("career_share", level="INFO"):
            out, results, _ = self._run(discord, send_job())
        self.assertEqual([r["outcome"] for r in results], ["SENT"])
        self.assertEqual(results[0]["message_id"], discord.existing[0]["id"])

    def test_lookup_failure_is_retried_by_sqs_and_late_redelivery_is_unknown(self):
        """마커 조회 실패 -> batchItemFailures(가시성 540초 뒤 재전달). 그때 TTL이 지났으면 보내지 않고 UNKNOWN."""
        from career_share import contract
        from discord_rest import errors
        discord = StubDiscord(lookup_errors=[errors.DiscordServerError("503", status=503)])
        job = send_job()
        with self.assertLogs("career_share", level="WARNING"):
            out, results, _ = self._run(discord, job)
        self.assertEqual((out, results, discord.sent), ({"batchItemFailures": [{"itemIdentifier": "m0"}]}, [], []))
        job["not_after"] = contract.iso(datetime.now(timezone.utc) - timedelta(seconds=1))      # 540초 뒤 = TTL 경과
        with self.assertLogs("career_share", level="INFO"):
            out, results, _ = self._run(discord, job, receive_count=2)
        self.assertEqual((out, [r["outcome"] for r in results], discord.sent), ({"batchItemFailures": []}, ["UNKNOWN"], []))

    def test_result_publish_failure_after_send_is_not_resent_on_redelivery(self):
        """정상 발송 후 결과 큐 발행 실패 -> 메시지 재전달 -> 마커로 이미 게시됨을 확인하고 다시 보내지 않는다."""
        from career_share import contract
        from career_share.queues import FakeQueue
        os.environ["DISCORD_BOT_TOKEN"] = FAKE_TOKEN
        discord, queue = StubDiscord(), FakeQueue()
        queue.fail_next = 1
        self.runtime(discord, queue)
        job = send_job()
        with self.assertLogs("career_share", level="WARNING"):
            out = self.bootstrap.handler(sqs_event(contract.dumps(job)))
        self.assertEqual((out, len(discord.sent), queue.messages), ({"batchItemFailures": [{"itemIdentifier": "m0"}]}, 1, []))
        out = self.bootstrap.handler(sqs_event(contract.dumps(job), receive_count=2))
        result = contract.validate_result(contract.loads(queue.bodies()[0]))
        self.assertEqual((out, len(discord.sent), result["outcome"], result["message_id"]),
                         ({"batchItemFailures": []}, 1, "SENT", discord.existing[0]["id"]))

    def test_expired_job_is_not_sent(self):
        from career_share import contract
        os.environ["DISCORD_BOT_TOKEN"] = FAKE_TOKEN
        discord, queue = self.runtime()
        job = send_job()
        job["not_after"] = contract.iso(datetime.now(timezone.utc) - timedelta(seconds=1))
        self.bootstrap.handler(sqs_event(contract.dumps(job)))
        self.assertEqual(discord.sent, [])
        self.assertEqual(contract.loads(queue.messages[0][1])["outcome"], "EXPIRED")


# ================================================================================================ HOT·DM (Issue #182)
FEATURES = {
    # feature: (조건, 함수 논리 ID, 큐 접두어, 패키지, 대상 핸들러)
    "hot": ("CreateHotShare", "HotShareWorkerFunction", "HotShare", "hot_worker", "hot_share.worker_lambda.handler"),
    "dm": ("CreateDmShare", "DmShareWorkerFunction", "DmShare", "dm_worker", "dm_share.worker_lambda.handler"),
}


@unittest.skipUnless(yaml, "PyYAML 없음: 템플릿 정적 검증 미실시")
class HotDmTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = load_template()
        cls.res, cls.params, cls.conds = cls.t["Resources"], cls.t["Parameters"], cls.t["Conditions"]

    def feature_resources(self, prefix):
        return {k: v for k, v in self.res.items() if k.startswith(prefix)}

    def test_features_are_off_by_default_and_career_is_unconditional(self):
        for name in ("DeployHotShare", "DeployDmShare", "HotWorkerEventSourceEnabled", "DmWorkerEventSourceEnabled"):
            self.assertEqual(self.params[name]["Default"], "false", name)
        self.assertEqual(self.params["HotShareChannelId"]["Default"], "", "취업만 배포하는 기존 명령이 그대로 동작")
        for key, (cond, _, prefix, _, _) in FEATURES.items():
            for name, resource in self.feature_resources(prefix).items():
                self.assertEqual(resource.get("Condition"), cond, name)
            for name, output in self.t["Outputs"].items():
                if name.startswith(prefix):
                    self.assertEqual(output.get("Condition"), cond, name)
        for name, resource in self.feature_resources("CareerShare").items():
            self.assertNotIn("Condition", resource, f"기존 취업 리소스는 조건 없이 그대로: {name}")
        rule = self.t["Rules"]["HotShareNeedsChannel"]
        self.assertEqual(rule["Assertions"][0]["Assert"], {"Fn::Not": [{"Fn::Equals": [{"Ref": "HotShareChannelId"}, ""]}]})

    def test_event_sources_disabled_by_default_and_tied_to_feature(self):
        for key, cond, enable in (("HotShare", "CreateHotShare", "EnableHotWorker"), ("DmShare", "CreateDmShare", "EnableDmWorker")):
            props = self.res[f"{key}WorkerSendQueueMapping"]["Properties"]
            self.assertEqual(props["Enabled"], {"Fn::If": [enable, True, False]})
            self.assertEqual(props["BatchSize"], 1)
            self.assertEqual(props["FunctionResponseTypes"], ["ReportBatchItemFailures"])
            self.assertEqual(props["EventSourceArn"], {"Fn::GetAtt": [f"{key}SendQueue", "Arn"]})
            self.assertEqual(self.conds[enable]["Fn::And"][0], {"Fn::Condition": cond}, "기능을 만들지 않으면 켤 수 없다")

    def test_concurrency_reserved_equals_maximum_and_dm_is_fifo(self):
        """FIFO 전환 후: HOT·DM 모두 예약 = 최대 = 2 (AWS 권장 충족). DM의 같은 알림 직렬화는 FIFO 그룹이 맡는다."""
        for key in ("HotShare", "DmShare"):
            fn = self.res[f"{key}WorkerFunction"]["Properties"]
            maximum = self.res[f"{key}WorkerSendQueueMapping"]["Properties"]["ScalingConfig"]["MaximumConcurrency"]
            self.assertEqual((fn["ReservedConcurrentExecutions"], maximum), (2, 2), key)
        send = self.res["DmShareSendQueue"]["Properties"]
        dlq = self.res["DmShareSendDLQ"]["Properties"]
        self.assertTrue(send["FifoQueue"] and dlq["FifoQueue"], "FIFO 큐의 DLQ도 FIFO")
        self.assertIs(send["ContentBasedDeduplication"], False, "발행기가 job_id로 중복 제거 ID를 넘긴다")
        self.assertTrue(send["QueueName"]["Fn::Sub"].endswith("-dm-share-send.fifo"))
        self.assertTrue(dlq["QueueName"]["Fn::Sub"].endswith("-dm-share-send-dlq.fifo"))
        self.assertEqual(send["RedrivePolicy"]["maxReceiveCount"], 5, "구조적 스로틀이 없으므로 재시도 여유를 늘리지 않는다")
        result = self.res["DmShareResultQueue"]["Properties"]
        self.assertNotIn("FifoQueue", result, "결과 큐는 표준 유지 (DB 반영이 claim_token·상태 전이로 멱등)")
        for name in ("HotShareSendQueue", "CareerShareSendQueue"):
            self.assertNotIn("FifoQueue", self.res[name]["Properties"], f"{name}은 표준 큐 그대로")

    def test_queues_timeouts_retention_and_encryption(self):
        for key in ("HotShare", "DmShare"):
            fn = self.res[f"{key}WorkerFunction"]["Properties"]
            send = self.res[f"{key}SendQueue"]["Properties"]
            self.assertGreaterEqual(send["VisibilityTimeout"], 6 * fn["Timeout"], key)
            self.assertEqual(send["RedrivePolicy"]["deadLetterTargetArn"], {"Fn::GetAtt": [f"{key}SendDLQ", "Arn"]})
            self.assertEqual(self.res[f"{key}ResultQueue"]["Properties"]["RedrivePolicy"]["deadLetterTargetArn"],
                             {"Fn::GetAtt": [f"{key}ResultDLQ", "Arn"]})
            for queue in ("SendQueue", "SendDLQ", "ResultQueue", "ResultDLQ"):
                self.assertTrue(self.res[f"{key}{queue}"]["Properties"]["SqsManagedSseEnabled"], f"{key}{queue}")
        dm_send = self.res["DmShareSendQueue"]["Properties"]
        self.assertLessEqual(dm_send["MessageRetentionPeriod"], 3600, "받는 사람 정보가 든 DM 작업은 짧게 보존 (TTL 50초)")
        self.assertGreater(self.res["DmShareSendDLQ"]["Properties"]["MessageRetentionPeriod"], dm_send["MessageRetentionPeriod"])

    def test_workers_reuse_handlers_without_vpc_or_db(self):
        for key, (_, fn_id, _, package, target) in FEATURES.items():
            fn = self.res[fn_id]["Properties"]
            env = fn["Environment"]["Variables"]
            self.assertEqual((fn["Handler"], fn["CodeUri"], fn["Runtime"]), ("secret_bootstrap.handler", f".build/{package}/", "python3.13"))
            self.assertEqual(env["WORKER_TARGET_HANDLER"], target)
            self.assertEqual(env["DISCORD_BOT_TOKEN_SECRET_ARN"], {"Ref": "DiscordBotTokenSecretArn"}, "토큰 시크릿 하나를 재사용")
            self.assertEqual(env["DISCORD_BOT_TOKEN_VERSION"], {"Ref": "DiscordBotTokenVersion"})
            self.assertNotIn("VpcConfig", fn)
            self.assertNotIn("DISCORD_BOT_TOKEN", env)
            self.assertFalse(any(k.startswith("DB_") for k in env))
        hot_env = self.res["HotShareWorkerFunction"]["Properties"]["Environment"]["Variables"]
        self.assertEqual((hot_env["HOT_SHARE_CHANNEL_ID"], hot_env["HOT_SHARE_RESULT_QUEUE_URL"]),
                         ({"Ref": "HotShareChannelId"}, {"Ref": "HotShareResultQueue"}))
        dm_env = self.res["DmShareWorkerFunction"]["Properties"]["Environment"]["Variables"]
        self.assertEqual(dm_env["DM_SHARE_RESULT_QUEUE_URL"], {"Ref": "DmShareResultQueue"})
        self.assertFalse(any("CHANNEL" in k for k in dm_env), "DM은 작업의 recipient_id로 DM 채널을 연다")
        self.assertFalse(any(r["Type"] == "AWS::SecretsManager::Secret" for r in self.res.values()), "시크릿을 새로 만들지 않는다")

    def test_each_role_only_touches_its_own_queues(self):
        for key in ("CareerShare", "HotShare", "DmShare"):
            statements = {}
            for policy in self.res[f"{key}WorkerRole"]["Properties"]["Policies"]:
                for statement in policy["PolicyDocument"]["Statement"]:
                    statement = statement["Fn::If"][1] if "Fn::If" in statement else statement
                    statements[statement["Sid"]] = statement
            self.assertEqual(statements["ConsumeSendQueue"]["Resource"], {"Fn::GetAtt": [f"{key}SendQueue", "Arn"]}, key)
            self.assertEqual(statements["PublishResults"]["Resource"], {"Fn::GetAtt": [f"{key}ResultQueue", "Arn"]}, key)
            self.assertEqual(statements["WriteOwnLogs"]["Resource"], {"Fn::GetAtt": [f"{key}WorkerLogGroup", "Arn"]}, key)
            self.assertEqual(statements["ReadDiscordTokenSecret"]["Resource"], {"Ref": "DiscordBotTokenSecretArn"}, key)
            actions = [a for s in statements.values() for a in (s["Action"] if isinstance(s["Action"], list) else [s["Action"]])]
            self.assertTrue(set(actions) <= {"logs:CreateLogStream", "logs:PutLogEvents", "sqs:ReceiveMessage", "sqs:DeleteMessage",
                                             "sqs:GetQueueAttributes", "sqs:SendMessage", "secretsmanager:GetSecretValue",
                                             "kms:Decrypt"}, actions)
            self.assertNotIn("ManagedPolicyArns", self.res[f"{key}WorkerRole"]["Properties"])

    HOT_DM_QUEUES = ("HotShareSendQueue", "HotShareSendDLQ", "HotShareResultQueue", "HotShareResultDLQ",
                     "DmShareSendQueue", "DmShareSendDLQ", "DmShareResultQueue", "DmShareResultDLQ")

    def test_hot_dm_queues_are_retained_and_career_untouched(self):
        """Deploy*=false로 바꾸거나 교체가 필요한 변경이 들어와도 HOT·DM 큐와 메시지를 지우지 않는다."""
        queues = sorted(k for k, v in self.res.items() if v["Type"] == "AWS::SQS::Queue" and not k.startswith("CareerShare"))
        self.assertEqual(queues, sorted(self.HOT_DM_QUEUES))
        for name in self.HOT_DM_QUEUES:
            self.assertEqual((self.res[name].get("DeletionPolicy"), self.res[name].get("UpdateReplacePolicy")), ("Retain", "Retain"), name)
        for name, resource in self.feature_resources("CareerShare").items():
            self.assertNotIn("DeletionPolicy", resource, f"기존 취업 리소스는 바꾸지 않는다: {name}")

    def test_stack_policy_protects_exactly_the_feature_queues(self):
        policy = json.loads((INFRA / "stack-policy.json").read_text(encoding="utf-8"))
        deny = [s for s in policy["Statement"] if s["Effect"] == "Deny"]
        self.assertEqual(len(deny), 1)
        self.assertEqual(sorted(deny[0]["Action"]), ["Update:Delete", "Update:Replace"])
        self.assertEqual(sorted(r.split("/", 1)[1] for r in deny[0]["Resource"]), sorted(self.HOT_DM_QUEUES))
        for resource in deny[0]["Resource"]:
            self.assertIn(resource.split("/", 1)[1], self.res, "정책의 논리 ID가 템플릿에 있어야 한다")
        self.assertIn({"Effect": "Allow", "Action": "Update:*", "Principal": "*", "Resource": "*"}, policy["Statement"])

    def test_dm_worker_prod_activation_still_requires_approval(self):
        """FIFO 구현(1~2단계)만으로 운영 차단을 풀지 않는다: 운영에서 켜려면 7단계 승인 파라미터가 필요하다 (기본 false)."""
        self.assertNotIn("DmWorkerNotInProdUntilFifo", self.t["Rules"])
        rule = self.t["Rules"]["DmWorkerProdRequiresApproval"]
        self.assertEqual(rule["RuleCondition"], {"Fn::And": [{"Fn::Equals": [{"Ref": "EnvironmentName"}, "prod"]},
                                                             {"Fn::Equals": [{"Ref": "DmWorkerEventSourceEnabled"}, "true"]}]})
        self.assertEqual(rule["Assertions"][0]["Assert"], {"Fn::Equals": [{"Ref": "DmProdActivationApproved"}, "true"]})
        self.assertEqual(self.params["DmProdActivationApproved"]["Default"], "false")
        self.assertEqual(self.params["DmWorkerEventSourceEnabled"]["Default"], "false")

    def test_dm_error_filter_also_counts_auth_warning(self):
        dm = self.res["DmShareWorkerErrorLogMetric"]["Properties"]["FilterPattern"]
        self.assertEqual(filter_terms(dm), ["[ERROR]", "DiscordAuthError"], "DM POST 401은 ERROR 로그 없이 정상 결과로 끝난다")
        self.assertEqual(filter_terms(self.res["HotShareWorkerErrorLogMetric"]["Properties"]["FilterPattern"]), ["[ERROR]"],
                         "HOT 401은 CareerShareWorker가 ERROR 로그를 남긴다")

    def test_alarms_are_consolidated_per_feature(self):
        def alarms(prefix):
            return {k: v["Properties"] for k, v in self.res.items() if k.startswith(prefix) and v["Type"] == "AWS::CloudWatch::Alarm"}
        self.assertEqual(len(alarms("CareerShare")), 7, "기존 취업 경보는 그대로")
        for key in ("HotShare", "DmShare"):
            found = alarms(key)
            self.assertEqual(set(found), {f"{key}WorkerFailuresAlarm", f"{key}DLQAlarm", f"{key}SendQueueAgeAlarm",
                                          f"{key}ResultQueueAgeAlarm"}, "기능당 4개 (취업 7개 복제 아님)")
            for props in found.values():
                self.assertEqual(props["AlarmActions"], {"Fn::If": ["HasAlarmTopic", [{"Ref": "AlarmTopicArn"}], {"Ref": "AWS::NoValue"}]})
                self.assertEqual(props["TreatMissingData"], "notBreaching")
            dlq_ids = {m["Id"] for m in found[f"{key}DLQAlarm"]["Metrics"]}
            self.assertEqual(dlq_ids, {"senddlq", "resultdlq", "dlq"}, "발송·결과 DLQ를 한 경보로")
        hot_ids = {m["Id"] for m in alarms("HotShare")["HotShareWorkerFailuresAlarm"]["Metrics"]}
        dm_ids = {m["Id"] for m in alarms("DmShare")["DmShareWorkerFailuresAlarm"]["Metrics"]}
        self.assertIn("throttles", hot_ids, "HOT은 예약 = 최대라 스로틀이 이상 신호")
        self.assertIn("throttles", dm_ids, "DM도 FIFO 전환 후 예약 = 최대라 스로틀이 이상 신호")
        for key, ttl in (("HotShare", 180), ("DmShare", 300)):
            self.assertEqual(alarms(key)[f"{key}SendQueueAgeAlarm"]["Threshold"], ttl)


class HotDmPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        spec = importlib.util.spec_from_file_location("build_package_hd", INFRA / "build_package.py")
        cls.builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.builder)
        cls.out = {}
        with redirect_stdout(io.StringIO()):
            for name in ("career_worker", "hot_worker", "dm_worker"):
                cls.out[name] = Path(cls.tmp.name) / name
                cls.builder.build(name, cls.out[name])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def files(self, name):
        return sorted(str(p.relative_to(self.out[name])).replace("\\", "/") for p in self.out[name].rglob("*") if p.is_file())

    def test_package_contents(self):
        hot, dm = self.files("hot_worker"), self.files("dm_worker")
        self.assertTrue({"hot_share/worker_lambda.py", "hot_share/messages.py", "hot_share/policy.py"} <= set(hot))
        self.assertTrue({"dm_share/worker_lambda.py", "dm_share/units.py", "services/notification_policy.py"} <= set(dm))
        for files in (hot, dm, self.files("career_worker")):
            for bad in ("repositories/", "hot_share/repository.py", "hot_share/db_lambda.py", "hot_share/service.py",
                        "dm_share/service.py", "dm_share/db_lambda.py", "dm_share/messages.py", "services/notification_service.py",
                        "discord_rest/reuse.py", "bot.py", "config.py", "career_share/repository.py"):
                self.assertFalse(any(f.startswith(bad) for f in files), bad)
        self.assertEqual([f for f in dm if f.startswith("services/")], ["services/__init__.py", "services/notification_policy.py"])

    def test_each_package_imports_alone_without_forbidden_modules(self):
        for name, target in (("career_worker", "career_share.worker_lambda"), ("hot_worker", "hot_share.worker_lambda"),
                             ("dm_worker", "dm_share.worker_lambda")):
            code = (f"import sys; sys.path.insert(0, {str(self.out[name])!r}); import secret_bootstrap, {target} as m;"
                    "assert callable(m.handler);"
                    "bad=[x for x in sys.modules if x.split('.')[0] in ('psycopg','psycopg2','discord','config','repositories','boto3')"
                    " or x in ('services.notification_service','services.web_links','hot_share.repository','dm_share.service')];"
                    "print('BAD' if bad else 'OK', bad)")
            run = subprocess.run([sys.executable, "-I", "-B", "-c", code], capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, f"{name}: {run.stderr}")
            self.assertTrue(run.stdout.startswith("OK"), f"{name}: {run.stdout}")

    def test_db_repository_still_exports_the_same_names(self):
        """분리 후에도 Gateway·DB Lambda·테스트의 기존 import 경로(repositories.dm_delivery_repository)가 같은 객체를 준다."""
        from dm_share import units
        from repositories import dm_delivery_repository as repo
        for name in ("DM_BLOCKED_CODE", "USER_GONE_CODES", "dm_unit_id", "notification_id_of"):
            self.assertIs(getattr(repo, name), getattr(units, name), name)
        self.assertEqual((units.DM_BLOCKED_CODE, units.USER_GONE_CODES), (50007, (10013, 50033)), "값 변경 없음")
        self.assertEqual((units.dm_unit_id(7), units.notification_id_of("dm-7"), units.notification_id_of("hot-7")), ("dm-7", 7, None))


class StubDmDiscord(StubDiscord):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.dm_recipients = []

    def create_dm_channel(self, recipient_id):
        self.dm_recipients.append(recipient_id)
        return {"id": "333333333333333333", "type": 1}


RECIPIENT = 987654321098765432        # 가짜 Discord 사용자 ID (로그에 나오면 안 된다)
SECRET_TITLE = "비공개 테스트 제목 XYZ"   # 가짜 게시글 제목 (로그에 나오면 안 된다)


def kind_job(kind, unit, *, recipient=RECIPIENT, token="tok0123456789abc"):
    from career_share import contract
    now = datetime.now(timezone.utc)
    marker = f"ref:{unit}"
    job = {"v": contract.VERSION, "type": "send", "job_id": f"{unit}:{token}", "unit_id": unit, "kind": kind, "claim_token": token,
           "claimed_at": contract.iso(now - timedelta(seconds=2)), "not_after": contract.iso(now + timedelta(seconds=45)),
           "marker": marker,
           "payload": {"embeds": [{"title": "💬 내 게시글에 새 댓글이 달렸어요.", "description": f"게시글: {SECRET_TITLE}",
                                   "footer": {"text": marker}}], "allowed_mentions": {"parse": []}}}
    if kind == "DM":
        job["recipient_id"] = str(recipient)
    return job


class HotDmFlowBase(unittest.TestCase):
    """HOT·DM 흐름 테스트 공통 준비 (테스트 메서드 없음)."""

    def setUp(self):
        sys.path.insert(0, str(INFRA / "src"))
        self.addCleanup(sys.path.remove, str(INFRA / "src"))
        import secret_bootstrap
        self.bootstrap = importlib.reload(secret_bootstrap)
        from dm_share import worker_lambda as dm_lambda
        from hot_share import worker_lambda as hot_lambda
        self.hot_lambda, self.dm_lambda = hot_lambda, dm_lambda
        self.addCleanup(setattr, hot_lambda, "_runtime", None)
        self.addCleanup(setattr, dm_lambda, "_runtime", None)
        patcher = mock.patch.dict(os.environ, {"DISCORD_BOT_TOKEN": FAKE_TOKEN, "DISCORD_BOT_TOKEN_SECRET_ARN": SECRET_ARN})
        patcher.start()
        self.addCleanup(patcher.stop)

    def use(self, target, discord, queue=None):
        from career_share.queues import FakeQueue
        from dm_share.worker_lambda import DmShareWorker
        from hot_share.worker_lambda import HotShareWorker
        queue = queue or FakeQueue()
        os.environ["WORKER_TARGET_HANDLER"] = f"{target}_share.worker_lambda.handler"
        self.bootstrap._target = None
        if target == "hot":
            self.hot_lambda._runtime = (HotShareWorker(discord, CHANNEL), RESULT_Q, queue)
        else:
            self.dm_lambda._runtime = (DmShareWorker(discord), RESULT_Q, queue)
        return queue

    def call(self, job, receive_count=1):
        from career_share import contract
        return self.bootstrap.handler(sqs_event(contract.dumps(job), receive_count=receive_count))

    def results(self, queue):
        from career_share import contract
        return [contract.validate_result(contract.loads(body)) for body in queue.bodies()]


class HotDmFlowTests(HotDmFlowBase):
    # -- HOT --
    def test_hot_job_is_sent_and_reported(self):
        discord = StubDiscord()
        queue = self.use("hot", discord)
        out = self.call(kind_job("HOT", "hot-42"))
        [result] = self.results(queue)
        self.assertEqual((out, result["outcome"], result["unit_id"], discord.sent[0][0]), ({"batchItemFailures": []}, "SENT", "hot-42", CHANNEL))

    def test_hot_worker_rejects_other_kinds_before_any_discord_call(self):
        for job in (send_job("post-42"), kind_job("DM", "dm-42"), kind_job("HOT", "post-42")):
            discord = StubDiscord(lookup_errors=[AssertionError("Discord 호출 금지")])
            queue = self.use("hot", discord)
            with self.assertLogs("career_share", level="ERROR"):
                out = self.call(job)
            self.assertEqual((out, discord.sent, queue.messages, discord.lookup_errors != []),
                             ({"batchItemFailures": [{"itemIdentifier": "m0"}]}, [], [], True), job["unit_id"])

    # -- DM --
    def test_dm_job_is_sent_to_recipient_dm_channel(self):
        discord = StubDmDiscord()
        queue = self.use("dm", discord)
        out = self.call(kind_job("DM", "dm-55"))
        [result] = self.results(queue)
        self.assertEqual((out, result["outcome"], discord.dm_recipients, discord.sent[0][0]),
                         ({"batchItemFailures": []}, "SENT", [RECIPIENT], 333333333333333333))
        self.assertEqual(discord.sent[0][2], "ref:dm-55", "nonce = 마커")

    def test_dm_worker_rejects_other_kinds_and_bad_recipients(self):
        jobs = [send_job("post-42"), kind_job("HOT", "hot-42"), kind_job("DM", "dm-55", recipient="abc"),
                kind_job("DM", "dm-55", recipient="0"), kind_job("DM", "dm-55", recipient="w12")]
        for job in jobs:
            discord = StubDmDiscord()
            queue = self.use("dm", discord)
            with self.assertLogs("career_share", level="ERROR"):
                out = self.call(job)
            self.assertEqual((out, discord.dm_recipients, discord.sent, queue.messages),
                             ({"batchItemFailures": [{"itemIdentifier": "m0"}]}, [], [], []), job.get("recipient_id", job["unit_id"]))

    def test_dm_error_outcomes(self):
        from discord_rest import errors
        cases = [
            (errors.DiscordAuthError("401", status=401), "FAILED_RETRY", {"auth_error": True}),            # 인증 차단기용 표시
            (errors.DiscordForbidden("403", status=403, code=50007), "FAILED_PERMANENT", {"error_code": 50007}),  # 수신 차단
            (errors.DiscordServerError("500", status=500, outcome_unknown=True), "UNKNOWN", {}),              # 결과 불명, 재발송 없음
            (errors.DiscordTimeoutError("timeout", outcome_unknown=True), "UNKNOWN", {}),
        ]
        for error, outcome, extra in cases:
            discord = StubDmDiscord(send_error=error)
            queue = self.use("dm", discord)
            with self.assertLogs(level="INFO"):
                out = self.call(kind_job("DM", "dm-55"))
            [result] = self.results(queue)
            self.assertEqual((out, result["outcome"], discord.attempts), ({"batchItemFailures": []}, outcome, 1), type(error).__name__)
            for key, value in extra.items():
                self.assertEqual(result.get(key), value, type(error).__name__)

    def test_dm_result_publish_failure_then_redelivery_does_not_resend(self):
        discord = StubDmDiscord()
        queue = self.use("dm", discord)
        queue.fail_next = 1
        job = kind_job("DM", "dm-55")
        with self.assertLogs("career_share", level="WARNING"):
            out = self.call(job)
        self.assertEqual((out, len(discord.sent)), ({"batchItemFailures": [{"itemIdentifier": "m0"}]}, 1))
        out = self.call(job, receive_count=2)
        [result] = self.results(queue)
        self.assertEqual((out, len(discord.sent), result["outcome"]), ({"batchItemFailures": []}, 1, "SENT"))

    def test_dm_logs_contain_no_recipient_title_or_token(self):
        """DM 처리 경로 전체(성공·실패·거부)의 로그에 받는 사람 ID, 게시글 제목, 토큰이 남지 않는다."""
        from discord_rest import errors
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setLevel(logging.DEBUG)
        root = logging.getLogger()
        old_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            for discord, job in ((StubDmDiscord(), kind_job("DM", "dm-55")),
                                 (StubDmDiscord(send_error=errors.DiscordAuthError("401", status=401)), kind_job("DM", "dm-56")),
                                 (StubDmDiscord(send_error=errors.DiscordForbidden("403", status=403, code=50007)), kind_job("DM", "dm-57")),
                                 (StubDmDiscord(lookup_errors=[errors.DiscordServerError("503", status=503)]), kind_job("DM", "dm-58")),
                                 (StubDmDiscord(), kind_job("HOT", "hot-1"))):
                self.use("dm", discord)
                self.call(job)
        finally:
            root.removeHandler(handler)
            root.setLevel(old_level)
        text = stream.getvalue()
        self.assertIn("dm-55", text, "로그가 실제로 수집되었는지 확인")
        for secret in (str(RECIPIENT), SECRET_TITLE, FAKE_TOKEN):
            self.assertNotIn(secret, text)


def filter_terms(pattern: str) -> list[str]:
    """CloudWatch Logs 텍스트 필터 '"a"' 또는 '?"a" ?"b"'의 용어 목록 (이 템플릿이 쓰는 형식만)."""
    import re
    return re.findall(r'"([^"]+)"', pattern)


def cloudwatch_matches(pattern: str, line: str) -> bool:
    """따옴표 용어는 부분 문자열 일치, ?는 OR (이 템플릿이 쓰는 형식만 흉내 낸다)."""
    return any(term in line for term in filter_terms(pattern))


class ChangeSetCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("check_changeset", INFRA / "check_changeset.py")
        cls.check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.check)

    @staticmethod
    def change(logical, rtype, action, replacement=None):
        rc = {"LogicalResourceId": logical, "ResourceType": rtype, "Action": action}
        if replacement is not None:
            rc["Replacement"] = replacement
        return {"Type": "Resource", "ResourceChange": rc}

    def test_detects_queue_removal_and_replacement(self):
        data = {"Changes": [self.change("HotShareSendQueue", "AWS::SQS::Queue", "Remove"),
                            self.change("DmShareSendDLQ", "AWS::SQS::Queue", "Modify", "True"),
                            self.change("DmShareResultQueue", "AWS::SQS::Queue", "Modify", "Conditional"),
                            self.change("HotShareWorkerFunction", "AWS::Lambda::Function", "Remove"),
                            self.change("CareerShareSendQueue", "AWS::SQS::Queue", "Modify", "False"),
                            self.change("DmShareSendQueue", "AWS::SQS::Queue", "Add")]}
        found = self.check.risky_changes(data)
        self.assertEqual([f.split(":")[0] for f in found], ["HotShareSendQueue", "DmShareSendDLQ", "DmShareResultQueue"])

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            risky, safe = Path(tmp) / "risky.json", Path(tmp) / "safe.json"
            risky.write_text(json.dumps({"Changes": [self.change("DmShareSendQueue", "AWS::SQS::Queue", "Remove")]}), encoding="utf-8")
            safe.write_text(json.dumps({"Changes": [self.change("CareerShareWorkerFunction", "AWS::Serverless::Function", "Modify", "False")]}),
                            encoding="utf-8")
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(self.check.main([str(risky)]), 1)
                self.assertEqual(self.check.main([str(safe)]), 0)
                self.assertEqual(self.check.main([]), 2)
            self.assertIn("DmShareSendQueue", out.getvalue())


class DmAuthErrorAlarmTests(HotDmFlowBase):
    """실제 DiscordRestClient(가짜 transport)로 DM POST 401 경로를 돌려 로그가 경보 필터에 잡히는지 확인한다."""

    def fake_transport(self, status_for_post):
        calls = []

        def transport(method, url, headers, payload, timeout):
            calls.append((method, url))
            if method == "POST" and url.endswith("/users/@me/channels"):
                return 200, {}, json.dumps({"id": "333333333333333333", "type": 1}).encode()
            if method == "GET" and "/messages" in url:
                return 200, {}, b"[]"
            if method == "GET":
                return 200, {}, json.dumps({"id": "333333333333333333", "last_message_id": None}).encode()
            return status_for_post, {}, json.dumps({"message": "401: Unauthorized", "code": 0}).encode()
        return transport, calls

    def run_with_capture(self, job, client):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("[%(levelname)s]\t2026-11-25T00:00:00.000Z\treq-id\t%(message)s"))  # Lambda 텍스트 형식
        handler.setLevel(logging.DEBUG)
        root = logging.getLogger()
        old_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            queue = self.use("dm", client)
            out = self.call(job)
        finally:
            root.removeHandler(handler)
            root.setLevel(old_level)
        return out, self.results(queue), stream.getvalue().splitlines()

    def test_post_401_is_a_normal_result_but_matches_dm_filter(self):
        from discord_rest import DiscordRestClient
        transport, calls = self.fake_transport(401)
        client = DiscordRestClient(FAKE_TOKEN, transport=transport, max_retries=0, sleep=lambda s: None)
        out, results, lines = self.run_with_capture(kind_job("DM", "dm-77"), client)
        self.assertEqual((out, results[0]["outcome"], results[0].get("auth_error")), ({"batchItemFailures": []}, "FAILED_RETRY", True))
        self.assertEqual([m for m, _ in calls], ["POST", "GET", "GET", "POST"], "DM 채널 열기 -> 마커 조회 -> 채널 -> 전송(401)")
        self.assertFalse(any(line.startswith("[ERROR]") for line in lines), "Worker는 POST 401에 ERROR 로그를 남기지 않는다 (경보 누락 위험의 근거)")
        dm_pattern, hot_pattern = '?"[ERROR]" ?"DiscordAuthError"', '"[ERROR]"'
        self.assertTrue(any(cloudwatch_matches(dm_pattern, line) for line in lines), "DM 필터는 401 경고를 센다")
        self.assertFalse(any(cloudwatch_matches(hot_pattern, line) for line in lines), "'[ERROR]'만으로는 놓친다")
        if yaml:
            actual = load_template()["Resources"]["DmShareWorkerErrorLogMetric"]["Properties"]["FilterPattern"]
            self.assertEqual(actual, dm_pattern)
        text = "\n".join(lines)
        for secret in (str(RECIPIENT), SECRET_TITLE, FAKE_TOKEN):
            self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
