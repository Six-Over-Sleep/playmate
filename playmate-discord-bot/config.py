"""환경변수 설정과 regular 모임의 시간 정책(비활성 기준, 점검/동기화 주기, timeout)을 모아 둔다."""
import os
from datetime import time
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

# 운영 기본값을 안전하게 유지한다: 테스트 모드(1분 주기)는 환경변수로 명시했을 때만 켜진다.
KST = ZoneInfo("Asia/Seoul")
INACTIVITY_DAYS = 30
INACTIVITY_GRACE_DAYS = 7
TEST_MODE = os.getenv("PLAYMATE_TEST_MODE", "false").lower() == "true"
CHECK_INTERVAL_SECONDS = 60 if TEST_MODE else 60 * 60 * 24

# PostgreSQL (Backend와 같은 변수 이름). 네 값이 모두 있어야 DB를 쓰고, 없으면 메모리 저장소로 동작한다.
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT") or "5432"
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")
DB_SSLMODE = os.getenv("DB_SSLMODE") or "require"
DB_CONFIGURED = all([DB_HOST, DB_USER, DB_PASSWORD, DB_NAME])
# SQL 한 개의 서버 쪽 최대 실행 시간. 느린 DB 때문에 worker thread가 무기한 멈추지 않게 한다.
DB_STATEMENT_TIMEOUT_MS = 15000
# recruits 행 락(FOR SHARE) 세션: 락 대기 한도 / 락을 잡은 뒤 Discord 작업 전체 시간 예산 /
# Bot이 작업 중 죽었을 때 서버가 락을 풀어 주는 최후의 안전망.
DB_LOCK_TIMEOUT_MS = 5000
DISCORD_LOCK_HOLD_SECONDS = 30
DB_LOCK_IDLE_IN_TRANSACTION_MS = 60000

# DB polling 주기(초).
SYNC_INTERVAL_SECONDS = int(os.getenv("PLAYMATE_SYNC_INTERVAL_SECONDS") or "10")
# FAILED 생성의 자동 재시도 대기(MANUAL/ABORTED 제외) / 이보다 오래된 PENDING은 중단으로 보고 MANUAL 처리.
SYNC_RETRY_AFTER_SECONDS = 300
SYNC_STALE_PENDING_SECONDS = 600

# TODO(임시 정책): Backend에 PUBLIC/PRIVATE 저장 위치가 없어 모두 PUBLIC으로 만든다.
# PRIVATE 권한 로직은 meeting_space.py / permissions.py에 구현되어 있다.
DEFAULT_VISIBILITY = "PUBLIC"


# -- 알림 / 공식 채널 기능 ------------------------------------------------------
# 아래 값은 모두 선택 사항이다. 비어 있거나 숫자가 아니면 해당 기능만 꺼지고 Bot은 계속 동작한다.
def _optional_id(name: str) -> int | None:
    value = (os.getenv(name) or "").strip()
    if not value:
        return None
    if not value.isdigit():
        print(f"{name} 값이 숫자가 아니어서 무시합니다.")
        return None
    return int(value)


# /게시글추천을 실행할 수 있는 Discord 역할. 없으면 아무도 실행할 수 없다.
ADMIN_ROLE_ID = _optional_id("PLAYMATE_ADMIN_ROLE_ID")
# #핫플레이메이트, #취업-소식 채널. 없으면 해당 채널 게시를 하지 않는다.
HOT_CHANNEL_ID = _optional_id("PLAYMATE_HOT_CHANNEL_ID")
CAREER_CHANNEL_ID = _optional_id("PLAYMATE_CAREER_CHANNEL_ID")
# 프론트 웹 주소. 상세 route가 확정되기 전까지 링크 버튼에는 쓰지 않는다.
WEB_BASE_URL = (os.getenv("PLAYMATE_WEB_BASE_URL") or "").strip().rstrip("/") or None

# notifications PENDING 행을 확인하는 주기(초). 모임 DB 동기화 루프와는 별개다.
NOTIFICATION_POLL_SECONDS = 10
NOTIFICATION_BATCH_SIZE = 20
# DM 전송 실패 시 총 시도 횟수 한도(도달하면 FAILED)와, 실패한 알림을 다시 시도하기까지의 간격(초).
NOTIFICATION_MAX_ATTEMPTS = 3
NOTIFICATION_RETRY_DELAY_SECONDS = 60

# HOT PLAYMATE 자동 게시 시각과 후보 기간.
HOT_POST_TIMES = (time(13, 0, tzinfo=KST), time(19, 0, tzinfo=KST))
HOT_CANDIDATE_HOURS = 24

# 취업 소식: 신규 콘텐츠 확인 주기와 채용공고 마감 재노출 규칙 (D-3, D-1 13:00).
CAREER_POLL_SECONDS = 60
CAREER_REMINDER_TIME = time(13, 0, tzinfo=KST)
CAREER_REMINDER_DAYS = (3, 1)
