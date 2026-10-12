"""Environment settings and the existing PlayMate timing policy."""
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

# Preserve the original ZoneInfo timezone; testing requires explicit opt-in.
KST = ZoneInfo("Asia/Seoul")
INACTIVITY_DAYS = 30
INACTIVITY_GRACE_DAYS = 7
ONE_TIME_DELETE_GRACE_HOURS = 24
TEST_MODE = os.getenv("PLAYMATE_TEST_MODE", "false").lower() == "true"
CHECK_INTERVAL_SECONDS = 60 if TEST_MODE else 60 * 60 * 24
