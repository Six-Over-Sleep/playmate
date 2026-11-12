"""회전 파일 로그. 콘솔 출력은 그대로 두고, 같은 내용을 `logs/bot.log`에도 남긴다.

봇이 종료된 뒤에도 장애 시각의 DB 연결 실패, 락 대기, 권한 동기화 실패, 재시도 지연을 확인하기 위한 것이다.
기존 코드의 print()를 고치지 않도록 stdout / stderr를 파일에도 함께 쓴다 (discord.py 로그와 rate limit 경고는
stderr로 나오므로 함께 남는다). 파일에 쓰기 전에 비밀번호, 토큰, 접속 URI는 가린다.
최대 5MB 파일 5개(bot.log + 백업 4개)를 돌려 쓴다. 로그 폴더는 git에 포함하지 않는다(.gitignore).
"""
import logging
import logging.handlers
import os
import re
import sys
import threading
import time
from pathlib import Path

LOG_DIR = Path(os.getenv("PLAYMATE_LOG_DIR") or Path(__file__).resolve().parent / "logs")
LOG_FILE_NAME = "bot.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 4  # 현재 파일 + 백업 4개 = 5개

_FILE_LOGGER_NAME = "playmate.file"
_installed = False

# 값을 알 수 없는 비밀(접속 URI, 비밀번호 인자, Discord 토큰 형태, 오류 메시지의 서버/계정 이름)을 패턴으로 가린다.
_PATTERNS = [
    (re.compile(r"postgres(?:ql)?(?:\+\w+)?://\S+", re.I), "postgresql://***"),
    (re.compile(r"(password|passwd|pwd|token|secret)\s*[=:]\s*\S+", re.I), r"\1=***"),
    (re.compile(r"[A-Za-z0-9_-]{23,28}\.[A-Za-z0-9_-]{6,7}\.[A-Za-z0-9_-]{27,}"), "***"),
    (re.compile(r'(server at )"[^"]*"( \([^)]*\))?'), r'\1"***"'),
    (re.compile(r'(for user )"[^"]*"', re.I), r'\1"***"'),
]


# 터미널용 색상 코드와 discord.py 로그 줄의 등급 표시 ("[INFO    ] discord.client: ..." 또는 색상 형식의 "INFO     discord.client ...").
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DISCORD_LEVEL = re.compile(r"\b(DEBUG|INFO|WARNING|ERROR|CRITICAL)\b\s*\]?\s+discord[\w.]*")


def mask_id(value) -> str:
    """Discord 사용자 ID는 로그에 뒤 4자리만 남긴다 (개인정보 최소화)."""
    return "…" + str(value)[-4:]


class RedactingFilter(logging.Filter):
    """파일에 쓰는 모든 메시지에서 알려진 비밀 값과 비밀 형태의 문자열을 가린다."""

    def __init__(self, secrets=()):
        super().__init__()
        self._secrets = [s for s in secrets if s and len(s) >= 4]

    def redact(self, text: str) -> str:
        text = _ANSI.sub("", text)
        for secret in self._secrets:
            text = text.replace(secret, "***")
        for pattern, replacement in _PATTERNS:
            text = pattern.sub(replacement, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.redact(record.getMessage())
        record.args = ()
        return True


class _SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """파일 쓰기/회전에 실패해도 봇 기능을 멈추지 않는다 (디스크 가득 참, Windows에서 파일을 다른 프로그램이 연 경우 등).

    기본 handleError는 traceback을 stderr에 쓰는데, stderr가 이 파일 로그로 다시 들어가면 같은 실패가 반복되어
    무한 재귀가 된다. 대신 원래 콘솔에 짧은 안내를 1분에 한 번만 남기고 계속 진행한다.
    """

    _last_notice = 0.0

    def handleError(self, record):
        now = time.monotonic()
        if now - self._last_notice > 60:
            self._last_notice = now
            try:
                sys.__stderr__.write("[파일 로그] 기록 실패, 콘솔 출력만 계속합니다\n")
            except Exception:
                pass


class _Tee:
    """원래 스트림(콘솔)에 그대로 쓰면서, 줄 단위로 파일 로그에도 남긴다.

    파일 기록의 실패나 재진입은 콘솔 출력과 호출한 코드에 영향을 주지 않는다. stderr의 discord.py 로그 줄은
    "[INFO    ]" 같은 표시로 등급을 판별한다 (없으면 이 Tee의 기본 등급).
    """

    def __init__(self, stream, logger: logging.Logger, level: int):
        self._stream, self._logger, self._level = stream, logger, level
        self._buffer = ""
        self._local = threading.local()

    def write(self, text):
        written = self._stream.write(text)
        if getattr(self._local, "busy", False):
            return written  # 파일 로그 기록 중에 다시 들어온 출력은 파일에 중복해서 쓰지 않는다
        self._local.busy = True
        try:
            self._buffer += text
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                if line.strip():
                    clean = _ANSI.sub("", line.rstrip())
                    found = _DISCORD_LEVEL.search(clean)
                    level = getattr(logging, found.group(1)) if found else self._level
                    self._logger.log(level, clean)
        except Exception:
            self._buffer = ""
        finally:
            self._local.busy = False
        return written

    def flush(self):
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def build_file_handler(log_dir: Path = LOG_DIR, secrets=()) -> logging.Handler:
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = _SafeRotatingFileHandler(
        log_dir / LOG_FILE_NAME, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8",
    )
    handler.addFilter(RedactingFilter(secrets))
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    return handler


def setup_file_logging(log_dir: Path = LOG_DIR) -> logging.Handler | None:
    """회전 파일 로그를 켠다 (프로세스에서 한 번). 파일을 만들 수 없으면 콘솔만으로 계속 동작한다."""
    global _installed
    if _installed:
        return None
    try:
        import config

        secrets = (config.TOKEN, config.DB_PASSWORD)
        handler = build_file_handler(log_dir, secrets)
    except Exception as error:  # 로그 때문에 봇이 시작하지 못하면 안 된다
        print(f"파일 로그를 켜지 못했습니다(콘솔 출력만 사용): {type(error).__name__}")
        return None
    import datetime

    kst = config.KST
    handler.formatter.converter = lambda *_: datetime.datetime.now(kst).timetuple()

    file_logger = logging.getLogger(_FILE_LOGGER_NAME)
    file_logger.setLevel(logging.INFO)
    file_logger.propagate = False  # 콘솔에는 Tee가 이미 출력한다
    file_logger.addHandler(handler)
    # discord.py 로그(gateway, rate limit 경고 등)는 기본 설정이 stderr에 출력하므로 stderr Tee가 함께 파일에 남긴다.
    if sys.stdout is not None:
        sys.stdout = _Tee(sys.stdout, file_logger, logging.INFO)
    if sys.stderr is not None:
        sys.stderr = _Tee(sys.stderr, file_logger, logging.WARNING)
    _installed = True
    print(f"파일 로그 시작: {log_dir / LOG_FILE_NAME} (최대 {MAX_BYTES // (1024 * 1024)}MB x {BACKUP_COUNT + 1}개)")
    return handler
