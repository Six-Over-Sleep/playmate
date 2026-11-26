"""Fail-closed runner configuration. Never loads .env or imports Gateway config."""
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from career_share.settings import SettingsError, load_db_settings
from hot_share.settings import load_hot_settings
from dm_share.settings import load_dm_settings


def integer(env, name, default, minimum, maximum):
    try:
        value = int(env.get(name, str(default)))
    except (ValueError, TypeError):
        raise SettingsError(f"{name}: integer required") from None
    if not minimum <= value <= maximum:
        raise SettingsError(f"{name}: out of range")
    return value


def enabled(env, name):
    value = env.get(name, "false").strip().lower()
    if value not in ("true", "false"):
        raise SettingsError(f"{name}: use true or false")
    return value == "true"


@dataclass(frozen=True)
class Settings:
    features: tuple[str, ...]
    queues: dict[str, str]
    region: str
    dm_mode: str
    digest_grace_minutes: int
    wait_seconds: int
    read_timeout: int
    visibility_seconds: int
    heartbeat_seconds: int
    lock_dir: str


def load_settings(env=None):
    env = os.environ if env is None else env
    features = tuple(f for f in ("career", "hot", "dm")
                     if enabled(env, f"DB_RUNNER_{f.upper()}_ENABLED"))
    mode = env.get("DB_RUNNER_DM_MODE", "disabled").strip()
    if mode not in ("disabled", "relay", "recover"):
        raise SettingsError("DB_RUNNER_DM_MODE: disabled, relay or recover required")
    if ("dm" in features) != (mode != "disabled"):
        raise SettingsError("DM opt-in and DM mode must agree")
    grace = integer(env, "DB_RUNNER_DIGEST_GRACE_MINUTES", 30, 1, 180)
    wait = integer(env, "DB_RUNNER_WAIT_SECONDS", 20, 1, 20)
    read = integer(env, "DB_RUNNER_READ_TIMEOUT_SECONDS", 30, 2, 120)
    visibility = integer(env, "DB_RUNNER_VISIBILITY_SECONDS", 360, 60, 43200)
    heartbeat = integer(env, "DB_RUNNER_HEARTBEAT_SECONDS", 60, 1, 3600)
    if read <= wait or heartbeat * 3 >= visibility or visibility <= 2 * read + 15:
        raise SettingsError("read must exceed wait; heartbeat < visibility/3; visibility > 2*read+15")
    region = env.get("AWS_DEFAULT_REGION", "").strip()
    queues = {}
    if features:
        environment = env.get("PLAYMATE_ENVIRONMENT", "").strip()
        if environment not in ("test", "prod"):
            raise SettingsError("PLAYMATE_ENVIRONMENT: test or prod required")
        import re
        if not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d", region):
            raise SettingsError("AWS_DEFAULT_REGION required")
        for name in ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"):
            if not env.get(name, "").strip():
                raise SettingsError(f"{name} required")
        integer(env, "DB_PORT", 5432, 1, 65535)
        if env.get("DB_SSLMODE", "require") not in ("disable", "allow", "prefer", "require", "verify-ca", "verify-full"):
            raise SettingsError("DB_SSLMODE invalid")
        # Validate every active service before constructing any AWS client or DB connection.
        for feature, loader in (("career", load_db_settings), ("hot", load_hot_settings), ("dm", load_dm_settings)):
            if feature not in features:
                continue
            service = loader(env)
            if feature != "dm" and not service.base_url:
                raise SettingsError("PLAYMATE_WEB_BASE_URL required for Career/HOT")
            prefix = feature.upper() + "_SHARE_"
            queues[feature] = env.get(prefix + "RESULT_QUEUE_URL", "").strip()
            for role, url in (("send", service.send_queue_url), ("result", queues[feature])):
                parts = urlsplit(url)
                suffix = ".amazonaws.com.cn" if region.startswith("cn-") else ".amazonaws.com"
                expected = f"playmate-{environment}-{feature}-share-{role}" + (".fifo" if feature == "dm" and role == "send" else "")
                if (parts.scheme != "https" or parts.netloc != f"sqs.{region}{suffix}"
                        or parts.query or parts.fragment or parts.path.split("/")[-1] != expected
                        or not re.fullmatch(r"/\d{12}/[^/]+", parts.path)):
                    raise SettingsError(f"{prefix}{role.upper()}_QUEUE_URL: unexpected environment/region/name")
        urls = [env.get(f"{f.upper()}_SHARE_{r}_QUEUE_URL", "").strip()
                for f in features for r in ("SEND", "RESULT")]
        accounts = {urlsplit(url).path.split("/")[1] for url in urls}
        if len(set(urls)) != len(urls) or len(accounts) != 1:
            raise SettingsError("queues must be distinct and in one account")
    return Settings(features, queues, region, mode, grace, wait, read, visibility, heartbeat,
                    env.get("DB_RUNNER_LOCK_DIR", "/var/lib/discord-db-runner"))
