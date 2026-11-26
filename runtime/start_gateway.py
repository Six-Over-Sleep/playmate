"""EC2 Discord Gateway 실행기 (/opt/playmate-discord/runtime/start_gateway.py).

순서: /etc/playmate/api.env(DB 설정) -> /etc/playmate/discord-gateway.conf(Gateway 설정) -> 설정 검증
-> Secrets Manager(Discord 인증정보) -> ubuntu 권한으로 내려 bot.py 실행.

discord-gateway.conf에 적은 값은 덮어쓰지 않는다. 기능 스위치가 없거나 비어 있으면 bot의 config.py 기본값을 쓴다
(PLAYMATE_TEST_MODE=false, PLAYMATE_CAREER_NOTICE_ENABLED=true, PLAYMATE_DM_POLL_ENABLED=true,
PLAYMATE_STRAY_REVOKE_ENABLED=false: 예전에 이 스크립트가 강제로 넣던 값과 같다).
스위치 값이 잘못되면 Secrets Manager 조회·Discord 연결·DB 접속 전에 종료 코드 78로 멈춘다.
`--check`는 두 설정 파일만 읽어 검사하고 AWS를 호출하지 않는다.

이 파일은 root로 실행되므로 bot 디렉터리의 모듈을 import하지 않는다 (허용 값 목록은 config.py와 같게 유지한다).
"""
import json
import os
import sys
from pathlib import Path

BASE = Path("/opt/playmate-discord")
BOT = BASE / "playmate-discord-bot"
API_ENV = Path("/etc/playmate/api.env")
GATEWAY_CONF = Path("/etc/playmate/discord-gateway.conf")
SECRET_ID = "playmate/beta/discord-gateway"
REGION = "ap-northeast-2"
EXIT_CONFIG = 78  # 설정 오류: systemd에서 RestartPreventExitStatus=78로 재시작 반복을 막을 수 있다

DB_KEYS = {
    "DB_HOST",
    "DB_PORT",
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "DB_SSLMODE",
    "PGSSLROOTCERT",
}

GATEWAY_KEYS = {
    "PLAYMATE_TEST_MODE",
    "PLAYMATE_CAREER_NOTICE_ENABLED",
    "PLAYMATE_DM_POLL_ENABLED",
    "PLAYMATE_STRAY_REVOKE_ENABLED",
    "PLAYMATE_SYNC_INTERVAL_SECONDS",
    "PLAYMATE_PROVISION_BATCH_LIMIT",
    "PLAYMATE_CATCHUP_DAYS",
    "PLAYMATE_WEB_BASE_URL",
    "PLAYMATE_CAREER_CHANNEL_ID",
    "PLAYMATE_HOT_CHANNEL_ID",
    "PLAYMATE_ADMIN_ROLE_ID",
}

# config.py SWITCH_TRUE / SWITCH_FALSE와 같은 목록 (테스트가 일치를 확인한다).
SWITCH_TRUE = ("true", "1", "yes", "on")
SWITCH_FALSE = ("false", "0", "no", "off")
# 이 두 스위치는 config.py가 "true"만 켜짐으로 본다. 다른 표기는 조용히 꺼짐이 되므로 true/false만 받는다.
STRICT_TRUE_FALSE = ("PLAYMATE_TEST_MODE", "PLAYMATE_STRAY_REVOKE_ENABLED")
SWITCHES = ("PLAYMATE_CAREER_NOTICE_ENABLED", "PLAYMATE_DM_POLL_ENABLED") + STRICT_TRUE_FALSE
DEFAULTS = {
    "PLAYMATE_TEST_MODE": "false",
    "PLAYMATE_CAREER_NOTICE_ENABLED": "true",
    "PLAYMATE_DM_POLL_ENABLED": "true",
    "PLAYMATE_STRAY_REVOKE_ENABLED": "false",
}


class GatewayConfigError(Exception):
    """설정 파일 값 오류. 메시지에는 설정 이름과 허용 값만 넣는다."""


def _load(path, keys):
    try:
        text = path.read_text()
    except OSError:
        # 없거나 읽을 수 없는 설정 파일도 재시작으로 고쳐지지 않으므로 설정 오류(78)다. 경로만 알린다.
        raise GatewayConfigError(f"설정 파일을 읽을 수 없습니다: {path}") from None
    settings = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in keys:
            settings[key] = value.strip().strip('"').strip("'")
    return settings


def load_db_settings(path):
    return _load(path, DB_KEYS)


def load_gateway_settings(path):
    return _load(path, GATEWAY_KEYS)


def validate_switches(settings):
    """기능 스위치를 검사한다. 빈 값은 '설정 없음'으로 보고 환경에서 뺀다 (bot 기본값 적용)."""
    for name in SWITCHES:
        value = settings.get(name)
        if value is None:
            continue
        normalized = value.strip().lower()
        if not normalized:
            del settings[name]
            continue
        allowed = ("true", "false") if name in STRICT_TRUE_FALSE else SWITCH_TRUE + SWITCH_FALSE
        if normalized not in allowed:
            raise GatewayConfigError(
                f"{name} 설정값이 올바르지 않습니다. true 또는 false로 지정하세요 (허용: {'/'.join(allowed)})."
            )
        settings[name] = normalized
    return settings


def describe_switches(settings):
    """실행 로그용 요약: 스위치 이름과 적용 값만 (다른 설정 값·비밀값은 출력하지 않는다)."""
    return ", ".join(
        f"{name}={settings[name]}" if name in settings else f"{name}={DEFAULTS[name]}(기본값)"
        for name in SWITCHES
    )


def fetch_gateway_secret():
    import boto3  # 설정 검사(--check)와 테스트는 boto3 없이 실행된다

    secret = boto3.client("secretsmanager", region_name=REGION).get_secret_value(SecretId=SECRET_ID)
    return json.loads(secret["SecretString"])


def load_settings(api_env=None, gateway_conf=None):
    """두 설정 파일을 읽고 검사한다. 외부 호출이 없다."""
    return (load_db_settings(api_env or API_ENV),
            validate_switches(load_gateway_settings(gateway_conf or GATEWAY_CONF)))


def build_env(api_env=None, gateway_conf=None, fetch_secret=None, base_env=None):
    """bot.py에 넘길 환경. 설정 검사가 끝난 뒤에만 Secrets Manager를 조회한다."""
    db_settings, gateway_settings = load_settings(api_env, gateway_conf)
    fetch_secret = fetch_secret or fetch_gateway_secret
    base_env = os.environ if base_env is None else base_env
    env = {
        "PATH": base_env.get("PATH", "/usr/bin:/bin"),
        "HOME": "/home/ubuntu",
        "PYTHONUNBUFFERED": "1",
        **db_settings,
        **gateway_settings,
    }
    data = fetch_secret()
    env["DISCORD_BOT_TOKEN"] = data["DISCORD_BOT_TOKEN"]
    env["DISCORD_GUILD_ID"] = data["DISCORD_GUILD_ID"]
    env["PLAYMATE_LOG_DIR"] = str(BASE / "logs")
    return env


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv == ["--check"]:
            _, gateway_settings = load_settings()
            print(f"Gateway 설정 검사 통과: {describe_switches(gateway_settings)}")
            return 0
        if argv:
            raise GatewayConfigError("사용법: start_gateway.py [--check]")
        env = build_env()
    except GatewayConfigError as error:
        print(f"Gateway 설정 오류: {error}", file=sys.stderr)
        return EXIT_CONFIG
    print(f"Gateway 기능 스위치: {describe_switches(env)}")
    if env.get("PLAYMATE_TEST_MODE") == "true":
        print("경고: PLAYMATE_TEST_MODE=true (라이프사이클 검사 1분 주기). 운영에서는 false로 둔다.")

    import pwd
    account = pwd.getpwnam("ubuntu")
    os.initgroups(account.pw_name, account.pw_gid)
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)

    os.chdir(BOT)
    os.execve(str(BASE / ".venv/bin/python"), [
        str(BASE / ".venv/bin/python"), "bot.py"
    ], env)


if __name__ == "__main__":
    sys.exit(main())
