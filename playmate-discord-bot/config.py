"""환경변수 설정과 모임 채널의 시간 정책(생성 기준, 비활성 기준, 점검/동기화 주기, timeout)을 모아 둔다."""
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
TEST_MODE = os.getenv("PLAYMATE_TEST_MODE", "false").lower() == "true"

# 모임 채널 비활성 정책: INACTIVITY_DAYS일 동안 메시지가 없으면 채널에 경고하고,
# INACTIVITY_GRACE_HOURS시간 안에 메시지가 없으면 채널을 삭제한다.
INACTIVITY_DAYS = 7
INACTIVITY_GRACE_HOURS = 24
# 24시간 유예를 크게 어기지 않도록 하루 1번이 아니라 1시간마다 점검한다 (테스트 모드는 1분).
CHECK_INTERVAL_SECONDS = 60 if TEST_MODE else 60 * 60

# Discord 채널을 만드는 모임 방식. 모집 마감(deadline_at) 시점에 방식과 관계없이 모임 채널 하나를 만든다.
CHANNEL_RECRUIT_MODES = ("regular", "short")
# 마감을 놓친 모임(Bot 장애/재시작)은 기간 제한 없이 "마감이 지났고 채널이 없는 모임"으로 복구한다.
# 오래된 데이터에 채널이 한꺼번에 생기지 않도록 한 번의 동기화(poll)에서 만드는 채널 수에 상한을 둔다.
CHANNEL_PROVISION_BATCH_LIMIT = int(os.getenv("PLAYMATE_PROVISION_BATCH_LIMIT") or 5)
# 운영자가 처음 배포할 때 아주 오래된 과거 모임을 제외하고 싶다면 환경변수로 복구 범위(일)를 지정한다.
# 기본값은 None(제한 없음)이다. 정책으로 확정된 값이 아니므로 코드에 고정하지 않는다.
CHANNEL_CATCHUP_DAYS = int(os.getenv("PLAYMATE_CATCHUP_DAYS") or 0) or None

# 공식 서버 구조. 모임 채널은 모임별 Category 없이 이 공용 카테고리 아래에 채널 하나씩 만든다.
# Discord 카테고리는 채널 50개가 한도라서, 가득 차면 "모임별 채널 2"처럼 공용 카테고리를 늘린다.
MEETING_CATEGORY_NAME = "모임별 채널"
MEETING_CATEGORY_CHANNEL_LIMIT = 50
# 상시 오픈채팅: 모임과 무관하게 항상 있는 채널. recruit_id와 연결하지 않고 자동 삭제하지 않는다.
OFFICIAL_CATEGORY_NAME = "상시 오픈채팅"
OFFICIAL_CHANNEL_NAMES = ("자격증-정보공유", "기술스택-정보공유", "직무-정보공유")
# 필수 상시 채널이 모두 준비될 때까지 누락된 채널을 다시 만들어 보는 간격(분).
OFFICIAL_RETRY_MINUTES = 10

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

LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "[::1]")


def _web_base_url(value: str | None, allow_local: bool) -> str | None:
    """Discord 메시지의 상세 링크에 쓸 웹 주소. http(s)가 아니거나, 운영에서 localhost면 링크를 붙이지 않는다."""
    value = (value or "").strip().rstrip("/")
    if not value:
        return None
    scheme, _, rest = value.partition("://")
    host = rest.split("/")[0].split("@")[-1].lower()
    if host.startswith("["):
        host = host.split("]")[0] + "]"
    else:
        host = host.split(":")[0]
    if scheme.lower() not in ("http", "https") or not host:
        print("PLAYMATE_WEB_BASE_URL 값이 http(s) 주소가 아니어서 상세 링크를 붙이지 않습니다.")
        return None
    if host in LOCAL_HOSTS and not allow_local:
        print("PLAYMATE_WEB_BASE_URL이 localhost라 상세 링크를 붙이지 않습니다 (테스트 모드에서만 허용).")
        return None
    return value


# 프론트 웹 주소. /게시글추천 Embed의 상세 페이지 링크에 쓴다. 비어 있으면 링크 없이 게시한다.
WEB_BASE_URL = _web_base_url(os.getenv("PLAYMATE_WEB_BASE_URL"), allow_local=TEST_MODE)

# notifications PENDING 행을 확인하는 주기(초). 모임 DB 동기화 루프와는 별개다.
NOTIFICATION_POLL_SECONDS = 10
NOTIFICATION_BATCH_SIZE = 20
# DM 전송 실패 시 총 시도 횟수 한도(도달하면 FAILED)와, 실패한 알림을 다시 시도하기까지의 간격(초).
NOTIFICATION_MAX_ATTEMPTS = 3
NOTIFICATION_RETRY_DELAY_SECONDS = 60

# 취업게시판 신규 글 자동 공지: 매일 18:00 (KST), 취준 도감·커리어 연구소, 하루 최대 5개.
# 채널은 PLAYMATE_CAREER_CHANNEL_ID(#취업-소식)를 쓴다. 실패한 글은 다음 실행에서 총 3회까지 다시 시도한다.
CAREER_NOTICE_TIME = time(18, 0, tzinfo=KST)
CAREER_NOTICE_CATEGORIES = ("reviews", "lab")
CAREER_NOTICE_DAILY_LIMIT = 5
CAREER_NOTICE_MAX_ATTEMPTS = 3

# 취업 소식: 신규 콘텐츠 확인 주기와 채용공고 마감 재노출 규칙 (D-3, D-1 13:00).
CAREER_POLL_SECONDS = 60
CAREER_REMINDER_TIME = time(13, 0, tzinfo=KST)
CAREER_REMINDER_DAYS = (3, 1)
