"""EC2 Gateway 실행기(runtime/start_gateway.py)와 기능 스위치 검증 (Issue #190).

AWS·Discord·PostgreSQL에 연결하지 않는다. Secrets Manager는 가짜 함수로 바꾸고, bot 설정은 하위 프로세스에서
실행기가 만든 환경 그대로 import해 실제 실행 환경에 전달되는 값을 확인한다.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_PATH = ROOT.parent / "runtime" / "start_gateway.py"
SECRET = {"DISCORD_BOT_TOKEN": "fixture-token-not-real-7c1d", "DISCORD_GUILD_ID": "123456789012345678"}
DB_PASSWORD = "fixture-db-password-9f2e"
SWITCHES = ("PLAYMATE_CAREER_NOTICE_ENABLED", "PLAYMATE_DM_POLL_ENABLED",
            "PLAYMATE_TEST_MODE", "PLAYMATE_STRAY_REVOKE_ENABLED")


def load_launcher():
    spec = importlib.util.spec_from_file_location("start_gateway", LAUNCHER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launcher = load_launcher()


class LauncherFixture(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = Path(folder.name)
        self.api_env = self.dir / "api.env"
        self.api_env.write_text(
            "DB_HOST=127.0.0.1\nDB_PORT=5432\nDB_NAME=fixture\nDB_USER=fixture\n"
            f"DB_PASSWORD={DB_PASSWORD}\nDB_SSLMODE=disable\nUNRELATED_SECRET=ignored\n", encoding="utf-8")
        self.secret_calls = 0

    def conf(self, **values):
        path = self.dir / "discord-gateway.conf"
        lines = ["PLAYMATE_SYNC_INTERVAL_SECONDS=10", "PLAYMATE_PROVISION_BATCH_LIMIT=1",
                 "PLAYMATE_CAREER_CHANNEL_ID=222222222222222222"]
        lines += [f"{key}={value}" for key, value in values.items()]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def fake_secret(self):
        self.secret_calls += 1
        return dict(SECRET)

    def build(self, **values):
        return launcher.build_env(self.api_env, self.conf(**values), fetch_secret=self.fake_secret,
                                  base_env={"PATH": os.environ.get("PATH", "")})

    def run_python(self, env, code):
        """실행기가 만든 환경으로 bot 코드를 import한다 (.env 자동 로드는 끈다)."""
        child = dict(env, PYTHON_DOTENV_DISABLED="1", PYTHONIOENCODING="utf-8")
        for name in ("SYSTEMROOT", "TEMP", "TMP"):   # Windows에서 Python 시작에 필요 (EC2와 무관)
            if name in os.environ:
                child[name] = os.environ[name]
        return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=child, capture_output=True,
                              text=True, encoding="utf-8")

    def effective(self, env):
        done = self.run_python(env, "import config; print(config.CAREER_NOTICE_ENABLED, config.DM_POLL_ENABLED, "
                                    "config.TEST_MODE, config.STRAY_REVOKE_ENABLED)")
        self.assertEqual(done.returncode, 0, done.stderr[-500:])
        return done.stdout.split()


class LauncherPassThroughTests(LauncherFixture):
    def test_explicit_false_reaches_bot_config(self):
        env = self.build(PLAYMATE_CAREER_NOTICE_ENABLED="false", PLAYMATE_DM_POLL_ENABLED="false")
        self.assertEqual((env["PLAYMATE_CAREER_NOTICE_ENABLED"], env["PLAYMATE_DM_POLL_ENABLED"]), ("false", "false"))
        self.assertEqual(self.effective(env), ["False", "False", "False", "False"])

    def test_each_switch_is_independent(self):
        env = self.build(PLAYMATE_CAREER_NOTICE_ENABLED="false", PLAYMATE_DM_POLL_ENABLED="true")
        self.assertEqual(self.effective(env)[:2], ["False", "True"])
        env = self.build(PLAYMATE_CAREER_NOTICE_ENABLED=" TRUE ", PLAYMATE_DM_POLL_ENABLED='"off"')
        self.assertEqual(self.effective(env)[:2], ["True", "False"])

    def test_explicit_true_reaches_bot_config(self):
        env = self.build(PLAYMATE_CAREER_NOTICE_ENABLED="true", PLAYMATE_DM_POLL_ENABLED="yes",
                         PLAYMATE_TEST_MODE="true", PLAYMATE_STRAY_REVOKE_ENABLED="TRUE")
        self.assertEqual(self.effective(env), ["True", "True", "True", "True"])

    def test_missing_or_empty_uses_previous_launcher_defaults(self):
        for env in (self.build(), self.build(PLAYMATE_CAREER_NOTICE_ENABLED="", PLAYMATE_DM_POLL_ENABLED="  ")):
            for name in SWITCHES:
                self.assertNotIn(name, env, "없거나 빈 값은 실행기가 채우지 않고 bot 기본값에 맡긴다")
            # 예전 실행기가 강제하던 값과 같다: 공지·DM 켜짐, 테스트 모드·자동 회수 꺼짐
            self.assertEqual(self.effective(env), ["True", "True", "False", "False"])

    def test_other_settings_and_secret_are_kept(self):
        env = self.build(PLAYMATE_DM_POLL_ENABLED="false")
        self.assertEqual((env["PLAYMATE_SYNC_INTERVAL_SECONDS"], env["PLAYMATE_PROVISION_BATCH_LIMIT"]), ("10", "1"))
        self.assertEqual(env["DB_PASSWORD"], DB_PASSWORD)
        self.assertNotIn("UNRELATED_SECRET", env)
        self.assertEqual((env["DISCORD_BOT_TOKEN"], env["DISCORD_GUILD_ID"]), tuple(SECRET.values()))
        self.assertEqual(env["PLAYMATE_LOG_DIR"], str(Path("/opt/playmate-discord/logs")))
        self.assertEqual(self.secret_calls, 1)


class LauncherRejectionTests(LauncherFixture):
    BAD = {
        "PLAYMATE_CAREER_NOTICE_ENABLED": ("fasle", "enabled", "2"),
        "PLAYMATE_DM_POLL_ENABLED": ("ture", "disable", "-1"),
        # config.py는 "true"만 켜짐으로 읽으므로 다른 표기는 조용히 꺼지지 않게 거부한다
        "PLAYMATE_TEST_MODE": ("1", "yes", "ture"),
        "PLAYMATE_STRAY_REVOKE_ENABLED": ("1", "on", "fasle"),
    }

    def test_invalid_values_stop_before_secrets_manager(self):
        for name, values in self.BAD.items():
            for value in values:
                with self.assertRaises(launcher.GatewayConfigError, msg=(name, value)) as caught:
                    self.build(**{name: value})
                message = str(caught.exception)
                self.assertIn(name, message)
                self.assertIn("true 또는 false", message)
                self.assertNotIn(value, message.replace("true", "").replace("false", "").replace("/", " ").split())
                self.assertNotIn(DB_PASSWORD, message)
        self.assertEqual(self.secret_calls, 0, "검사 실패 시 Secrets Manager를 조회하지 않는다")

    def test_main_returns_config_exit_code_without_secret_lookup(self):
        conf = self.conf(PLAYMATE_DM_POLL_ENABLED="fasle")
        out, err = StringIO(), StringIO()
        with patch.object(launcher, "API_ENV", self.api_env), patch.object(launcher, "GATEWAY_CONF", conf), \
                patch.object(launcher, "fetch_gateway_secret", side_effect=AssertionError("secret lookup")), \
                redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(launcher.main([]), 78)
            self.assertEqual(launcher.main(["--check"]), 78)
        self.assertIn("PLAYMATE_DM_POLL_ENABLED", err.getvalue())
        self.assertNotIn(DB_PASSWORD, out.getvalue() + err.getvalue())

    def test_missing_config_file_is_config_error(self):
        err = StringIO()
        with patch.object(launcher, "API_ENV", self.dir / "missing.env"), \
                patch.object(launcher, "GATEWAY_CONF", self.conf()), \
                patch.object(launcher, "fetch_gateway_secret", side_effect=AssertionError("secret lookup")), \
                redirect_stdout(StringIO()), redirect_stderr(err):
            self.assertEqual(launcher.main([]), 78, "재시작으로 고쳐지지 않는 오류는 78")
            self.assertEqual(launcher.main(["--check"]), 78)
        self.assertIn("missing.env", err.getvalue())

    def test_check_mode_reads_files_only_and_prints_no_secret(self):
        conf = self.conf(PLAYMATE_CAREER_NOTICE_ENABLED="false")
        out = StringIO()
        with patch.object(launcher, "API_ENV", self.api_env), patch.object(launcher, "GATEWAY_CONF", conf), \
                patch.object(launcher, "fetch_gateway_secret", side_effect=AssertionError("secret lookup")), \
                redirect_stdout(out):
            self.assertEqual(launcher.main(["--check"]), 0)
        text = out.getvalue()
        self.assertIn("PLAYMATE_CAREER_NOTICE_ENABLED=false", text)
        self.assertIn("PLAYMATE_DM_POLL_ENABLED=true(기본값)", text)
        for secret in (DB_PASSWORD, *SECRET.values(), "222222222222222222"):
            self.assertNotIn(secret, text)

    def test_check_mode_needs_no_aws_db_discord_or_network(self):
        """boto3·botocore·psycopg·discord import와 소켓 생성을 막아도 --check는 통과한다."""
        conf = self.conf(PLAYMATE_DM_POLL_ENABLED="false")
        code = f"""
import importlib.util, socket, sys
for name in ("boto3", "botocore", "psycopg", "psycopg2", "discord"):
    sys.modules[name] = None
def blocked(*args, **kwargs):
    raise AssertionError("network access")
socket.socket = blocked
socket.create_connection = blocked
spec = importlib.util.spec_from_file_location("start_gateway", {str(LAUNCHER_PATH)!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.API_ENV = module.Path({str(self.api_env)!r})
module.GATEWAY_CONF = module.Path({str(conf)!r})
sys.exit(module.main(["--check"]))
"""
        done = self.run_python({"PATH": os.environ.get("PATH", "")}, code)
        self.assertEqual(done.returncode, 0, done.stderr[-500:])
        self.assertIn("PLAYMATE_DM_POLL_ENABLED=false", done.stdout)
        self.assertNotIn(DB_PASSWORD, done.stdout + done.stderr)

    def test_launcher_has_no_forced_switch_overrides(self):
        source = LAUNCHER_PATH.read_text(encoding="utf-8")
        for name in SWITCHES:
            self.assertNotIn(f'env["{name}"] =', source, f"{name}를 강제로 덮어쓰지 않는다")


class BotSwitchTests(LauncherFixture):
    def test_config_rejects_invalid_switch_before_connecting(self):
        for name in ("PLAYMATE_CAREER_NOTICE_ENABLED", "PLAYMATE_DM_POLL_ENABLED"):
            env = self.build()
            env[name] = "fasle"   # 실행기를 거치지 않은 직접 실행(python bot.py)도 막는다
            done = self.run_python(env, "import config")
            self.assertNotEqual(done.returncode, 0)
            self.assertIn(name, done.stderr)
            self.assertNotIn(SECRET["DISCORD_BOT_TOKEN"], done.stdout + done.stderr)
            self.assertNotIn(DB_PASSWORD, done.stdout + done.stderr)

    def test_switch_lists_match_config(self):
        done = self.run_python(self.build(), "import config; print(config.SWITCH_TRUE, config.SWITCH_FALSE)")
        self.assertEqual(done.returncode, 0, done.stderr[-500:])
        self.assertEqual(done.stdout.strip(), f"{launcher.SWITCH_TRUE} {launcher.SWITCH_FALSE}")

    def registered(self, **values):
        """bot.py를 import만 한다 (client.run·DB 접속 없음). 등록된 작업과 명령을 돌려준다."""
        code = ("import json, bot; print(json.dumps({"
                "'tasks': [name for name, _ in bot.feature_tasks],"
                "'commands': sorted(c.name for c in bot.tree.get_commands(guild=bot.guild_object)),"
                "'sync': bot.sync_db is not None, 'lifecycle': bot.check_meeting_lifecycle is not None,"
                "'meeting_repo': type(bot.repository).__name__}))")
        done = self.run_python(self.build(**values), code)
        self.assertEqual(done.returncode, 0, done.stderr[-800:])
        self.assertNotIn(SECRET["DISCORD_BOT_TOKEN"], done.stdout + done.stderr)
        self.assertNotIn(DB_PASSWORD, done.stdout + done.stderr)
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_switches_gate_only_legacy_tasks(self):
        both_on = self.registered()
        self.assertIn("알림 polling (10초)", both_on["tasks"])
        self.assertIn("취업 신규 글 공지 (18:00)", both_on["tasks"])
        both_off = self.registered(PLAYMATE_CAREER_NOTICE_ENABLED="false", PLAYMATE_DM_POLL_ENABLED="false")
        self.assertNotIn("알림 polling (10초)", both_off["tasks"])
        self.assertNotIn("취업 신규 글 공지 (18:00)", both_off["tasks"])
        career_off = self.registered(PLAYMATE_CAREER_NOTICE_ENABLED="false")
        self.assertEqual(career_off["tasks"], ["알림 polling (10초)"])
        for state in (both_on, both_off, career_off):
            self.assertEqual(state["commands"], ["게시글추천", "알림설정"], "Slash 명령은 스위치와 무관하게 유지")
            self.assertTrue(state["sync"] and state["lifecycle"], "모임 동기화·라이프사이클 작업 유지")
            self.assertEqual(state["meeting_repo"], "PostgresMeetingRepository")


if __name__ == "__main__":
    unittest.main()
