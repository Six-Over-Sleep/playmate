"""Environment settings and the PlayMate regular-meeting timing policy."""
import os
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD_ID")

if not TOKEN:
    raise ValueError("DISCORD_BOT_TOKEN이 .env에 없습니다.")
if not GUILD_ID:
    raise ValueError("DISCORD_GUILD_ID가 .env에 없습니다.")
GUILD_ID = int(GUILD_ID)

# Keep the production-safe default: tests require explicit opt-in.
KST = ZoneInfo("Asia/Seoul")
INACTIVITY_DAYS = 30
INACTIVITY_GRACE_DAYS = 7
TEST_MODE = os.getenv("PLAYMATE_TEST_MODE", "false").lower() == "true"
CHECK_INTERVAL_SECONDS = 60 if TEST_MODE else 60 * 60 * 24

# PostgreSQL: same variable names as the backend (backend/app/core/config.py).
# Validated lazily so tests and in-memory runs do not need a database.
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT") or "5432"
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
DB_SSLMODE = os.getenv("DB_SSLMODE") or "require"
DB_CONFIGURED = all([DB_HOST, DB_USER, DB_PASSWORD, DB_NAME])
# Server-side cap per statement so a slow DB cannot hang a worker thread forever.
DB_STATEMENT_TIMEOUT_MS = 15000
# Row-lock session (recruits FOR SHARE held across a Discord side effect):
# how long to wait for the lock, how long the Discord work may keep it, and a
# server-side safety net that frees the lock if the Bot dies mid-operation.
DB_LOCK_TIMEOUT_MS = 5000
DISCORD_LOCK_HOLD_SECONDS = 30
DB_LOCK_IDLE_IN_TRANSACTION_MS = 60000

# How often the Bot reconciles the shared DB with Discord.
SYNC_INTERVAL_SECONDS = int(os.getenv("PLAYMATE_SYNC_INTERVAL_SECONDS") or "10")
# A FAILED creation without Discord IDs is retried after this many seconds;
# a PENDING claim older than the stale limit is treated as interrupted.
SYNC_RETRY_AFTER_SECONDS = 300
SYNC_STALE_PENDING_SECONDS = 600

# TODO(temporary policy): the backend has no place to store PUBLIC/PRIVATE yet.
# Until that is decided, every DB-provisioned regular meeting is PUBLIC.
# PRIVATE is still fully implemented in services/meeting_space.py and
# services/permissions.py; only the source of the value is pending.
DEFAULT_VISIBILITY = "PUBLIC"
