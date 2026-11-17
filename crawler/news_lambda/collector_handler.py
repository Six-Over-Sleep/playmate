"""PlayMate 뉴스 Collector Lambda (Issue #133).

EventBridge Scheduler → 이 Lambda → S3 ``raw/news/YYYY/MM/DD/<run_id>.json``

- 수집은 기존 코드를 고치지 않고 그대로 부른다.
  - ``database/scripts/collect_career_news.py``의 ``load_crawler``(크롤러 폴더 검증 + 8개 분야 검사),
    ``collect_all``(분야·검색어별 수집, 실패한 검색어는 건너뜀), ``check_categories``
  - ``crawler/career_news_crawler``의 ``config.CATEGORIES``와 ``src.rss_collector.collect_google_news``
    (RSS 요청·제목 필터·제외 출처·기간 필터)
- 크롤러 ``main.py``(SQLite 저장)와 PostgreSQL 적재 함수(``import_articles``)는 부르지 않는다.
- raw JSON은 **RSS XML 원문이 아니라 기존 크롤러가 필터링해서 돌려준 결과**를 그대로 담는다.
  본문·원문 URL은 크롤러가 만들지 않으므로 여기서도 만들지 않는다.
- 전체 검색어가 실패하면 업로드하지 않고 예외로 끝낸다(성공한 수집처럼 저장하지 않음).
- S3 업로드가 실패하면 예외로 끝낸다(정상 완료로 처리하지 않음).
- raw는 조건부 쓰기(IfNoneMatch="*")로 한 번만 저장한다. 같은 run_id가 이미 저장되어 있으면 덮어쓰지 않고
  기존 raw를 확인해 정상 중복 실행으로 끝낸다.

자세한 규격과 운영 정책은 같은 폴더의 README.md를 본다.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Mapping

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 팀 공통 JSON 형식이 확정되기 전의 임시 내부 규격 버전
SCHEMA_VERSION = "0.1-draft"
# raw에 담긴 데이터의 성격: 크롤러가 필터링한 RSS 수집 결과(원본 RSS XML 아님)
DATA_KIND = "filtered_rss_results"
DEFAULT_PREFIX = "raw/news/"
DEFAULT_DAYS = 14
DEFAULT_PAUSE_SECONDS = 1.0
CONTENT_TYPE = "application/json; charset=utf-8"
# rss_collector.collect_google_news가 requests에 넘기는 타임아웃(초). 남은 실행 시간 판단에 쓴다.
RSS_REQUEST_TIMEOUT_SECONDS = 15
# 수집을 멈추고 S3 업로드와 응답 정리에 남겨 둘 시간(초)
UPLOAD_RESERVE_SECONDS = 20
# collect_all이 오류 메시지를 자르는 길이와 같게 맞춘다.
ERROR_MESSAGE_LIMIT = 200
ARTICLE_FIELDS = ("title", "source", "link", "published")

# run_id: <UTC 기준 시각 YYYYMMDDTHHMMSSZ>-<영문·숫자·_- 1~64자>. 객체 키의 날짜는 앞의 시각에서 정한다.
RUN_ID_PATTERN = re.compile(r"^(\d{8}T\d{6}Z)-([0-9A-Za-z][0-9A-Za-z_-]{0,63})$")
BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")

HERE = Path(__file__).resolve().parent
# 저장소에서 실행할 때의 루트 (crawler/news_lambda → 저장소). Lambda 배포 묶음에서는 쓰이지 않는다.
REPO_ROOT = HERE.parents[1]


class ConfigError(ValueError):
    """환경변수·이벤트 값이 잘못되었다. 수집을 시작하지 않는다."""


class CollectionFailedError(RuntimeError):
    """모든 검색어가 실패했다. 성공한 수집처럼 저장하지 않기 위해 업로드하지 않는다."""

    def __init__(self, message: str, summary: dict):
        super().__init__(message)
        self.summary = summary


class RawUploadError(RuntimeError):
    """S3 업로드가 실패했거나 성공을 확인하지 못했다."""


class RawWriteConflictError(RawUploadError):
    """같은 키에 동시 조건부 쓰기가 진행 중이었다(S3 409). 일시적이므로 재시도 대상이다."""


class RawConflictError(RawUploadError):
    """같은 키에 이 실행(run_id)의 raw가 아닌 객체가 있다. 덮어쓰지 않으며 사람이 확인해야 한다."""


class TimeBudgetExceeded(RuntimeError):
    """Lambda 남은 실행 시간이 부족해 이 검색어는 요청하지 않았다."""


# -- 설정 ---------------------------------------------------------------------
@dataclass(frozen=True)
class Settings:
    bucket: str
    prefix: str = DEFAULT_PREFIX
    days: int = DEFAULT_DAYS
    pause_seconds: float = DEFAULT_PAUSE_SECONDS

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        """필요한 환경변수만 읽는다. 값 자체는 로그에 남기지 않는다."""
        env = os.environ if environ is None else environ
        bucket = (env.get("NEWS_RAW_BUCKET") or "").strip()
        if not bucket:
            raise ConfigError("NEWS_RAW_BUCKET 환경변수가 없습니다.")
        if not BUCKET_PATTERN.fullmatch(bucket):
            raise ConfigError("NEWS_RAW_BUCKET 값이 S3 버킷 이름 형식이 아닙니다.")
        prefix = normalize_prefix(env.get("NEWS_RAW_PREFIX") or DEFAULT_PREFIX)
        try:
            days = int(env.get("NEWS_DAYS") or DEFAULT_DAYS)
            pause = float(env.get("NEWS_PAUSE_SECONDS") or DEFAULT_PAUSE_SECONDS)
        except ValueError as error:
            raise ConfigError("NEWS_DAYS, NEWS_PAUSE_SECONDS는 숫자여야 합니다.") from error
        # collect_career_news.py의 --days(1~30) 범위를 그대로 따른다.
        if not 1 <= days <= 30:
            raise ConfigError("NEWS_DAYS는 1~30 사이여야 합니다.")
        if not 0 <= pause <= 10:
            raise ConfigError("NEWS_PAUSE_SECONDS는 0~10 사이여야 합니다.")
        return cls(bucket=bucket, prefix=prefix, days=days, pause_seconds=pause)


def normalize_prefix(prefix: str) -> str:
    """raw/ 아래만 허용한다. processed/ 등에 쓰면 S3 이벤트가 Processor를 잘못 부를 수 있다."""
    value = prefix.strip().lstrip("/")
    if not value.endswith("/"):
        value += "/"
    if not value.startswith("raw/") or ".." in value.split("/"):
        raise ConfigError("NEWS_RAW_PREFIX는 raw/로 시작하는 경로여야 합니다.")
    return value


# -- 기존 코드 불러오기 (수정 없이 재사용) ----------------------------------------
_COLLECT_MODULE: ModuleType | None = None
_CRAWLER: tuple[dict, Callable] | None = None


def _collect_module() -> ModuleType:
    """database/scripts/collect_career_news.py를 파일 경로로 불러온다.

    저장소에서는 database/scripts/, Lambda 배포 묶음에서는 핸들러와 같은 폴더의 파일을 쓴다.
    파일 경로로 직접 불러오므로 다른 폴더의 같은 이름 모듈이 섞이지 않는다.
    """
    global _COLLECT_MODULE
    if _COLLECT_MODULE is not None:
        return _COLLECT_MODULE
    for directory in (REPO_ROOT / "database" / "scripts", HERE):
        path = directory / "collect_career_news.py"
        if path.is_file():
            spec = importlib.util.spec_from_file_location("collect_career_news", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _COLLECT_MODULE = module
            return module
    raise ImportError("collect_career_news.py를 찾을 수 없습니다 (배포 묶음 구성을 확인하세요).")


def _crawler_dir() -> Path:
    """크롤러 폴더: NEWS_CRAWLER_DIR > 저장소의 crawler/career_news_crawler > 배포 묶음(핸들러 폴더)."""
    configured = os.getenv("NEWS_CRAWLER_DIR")
    if configured:
        return Path(configured)
    repo_crawler = REPO_ROOT / "crawler" / "career_news_crawler"
    if (repo_crawler / "src" / "rss_collector.py").is_file():
        return repo_crawler
    return HERE


def load_crawler() -> tuple[dict, Callable]:
    """기존 load_crawler로 CATEGORIES와 collect_google_news를 불러온다 (8개 분야 검사 포함).

    warm start에서는 다시 불러오지 않는다.
    """
    global _CRAWLER
    if _CRAWLER is None:
        _CRAWLER = _collect_module().load_crawler(_crawler_dir())
    return _CRAWLER


# -- run_id와 객체 키 ------------------------------------------------------------
def _format_ts(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _iso_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_utc(value: Any) -> datetime:
    """시간대가 있는 ISO8601만 받는다 (EventBridge time, Scheduler scheduled-time 형식)."""
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise ConfigError("예약 시각 형식이 ISO8601이 아닙니다.") from error
    if parsed.tzinfo is None:
        raise ConfigError("예약 시각에 시간대가 없습니다.")
    return parsed.astimezone(timezone.utc)


def resolve_run_id(event: Mapping[str, Any], context: Any, now: datetime) -> str:
    """실행 식별자를 정한다. 같은 예약 실행의 재시도는 같은 run_id(같은 객체 키)가 되도록 한다.

    1. event["run_id"]: 수동 재실행. 형식이 맞아야 한다.
    2. event["scheduled_time"] 또는 event["time"]: 예약 시각 기반 → "<시각>-scheduled"
       (Lambda 비동기 재시도에도 같은 값이 들어와 같은 키가 된다. 조건부 쓰기로 처음 저장한 raw를 보존한다)
    3. 그 외(콘솔 수동 실행 등): 현재 시각 + Lambda 요청 ID(없으면 무작위)
    """
    explicit = event.get("run_id")
    if explicit is not None:
        if not isinstance(explicit, str) or not RUN_ID_PATTERN.fullmatch(explicit):
            raise ConfigError("run_id 형식이 올바르지 않습니다 (예: 20261117T090000Z-manual).")
        return explicit
    scheduled = event.get("scheduled_time") or event.get("time")
    if scheduled:
        return f"{_format_ts(_parse_utc(scheduled))}-scheduled"
    request_id = str(getattr(context, "aws_request_id", "") or "")
    suffix = re.sub(r"[^0-9A-Za-z_-]", "", request_id)[:64] or uuid.uuid4().hex
    if not suffix[0].isalnum():
        suffix = "r" + suffix[:63]
    return f"{_format_ts(now)}-{suffix}"


def build_object_key(prefix: str, run_id: str) -> str:
    """raw/news/YYYY/MM/DD/<run_id>.json. 날짜는 run_id 앞의 시각에서 정하므로 같은 run_id는 항상 같은 키다."""
    match = RUN_ID_PATTERN.fullmatch(run_id)
    if not match:
        raise ConfigError("run_id 형식이 올바르지 않습니다.")
    stamp = match.group(1)
    return f"{normalize_prefix(prefix)}{stamp[0:4]}/{stamp[4:6]}/{stamp[6:8]}/{run_id}.json"


# -- 검색어별 기록 -----------------------------------------------------------------
def _error_info(error: BaseException) -> dict:
    return {"type": type(error).__name__, "message": str(error)[:ERROR_MESSAGE_LIMIT]}


class QueryRecorder:
    """collect_all에 넘기는 수집 함수를 감싸 검색어별 결과·오류를 순서대로 기록한다.

    collect_all은 수집 결과를 (분야 코드, 기사) 행으로 합치므로 어느 검색어에서 왔는지가 사라진다.
    기존 함수를 고치지 않고 검색어 단위 정보를 남기려고 호출을 가로채 기록만 하고, 결과와 예외는
    그대로 돌려준다(실패 처리 정책은 collect_all이 그대로 결정한다).
    deadline이 있으면 "이 요청의 RSS 타임아웃 + 뒤에 남은 검색어 사이 대기(collect_all의 pause)"가
    deadline을 넘을 때 요청하지 않고 실패로 기록한다. 건너뛴 뒤에도 collect_all은 검색어마다 pause만큼
    쉬므로, 그 시간까지 미리 계산해야 업로드할 시간이 남는다.
    """

    def __init__(self, collect: Callable, deadline: float | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 total_queries: int = 0, pause_seconds: float = 0.0):
        self._collect = collect
        self._deadline = deadline
        self._clock = clock
        self._total = total_queries
        self._pause = pause_seconds
        self.records: list[dict] = []

    def _out_of_time(self) -> bool:
        if self._deadline is None:
            return False
        remaining_after = max(self._total - len(self.records) - 1, 0)
        needed = RSS_REQUEST_TIMEOUT_SECONDS + self._pause * remaining_after
        return self._clock() + needed > self._deadline

    def __call__(self, query, title_keywords, days, session=None):
        if self._out_of_time():
            error = TimeBudgetExceeded("Lambda 남은 실행 시간이 부족해 요청하지 않았습니다.")
            self.records.append(self._failed(query, error))
            raise error
        try:
            articles = self._collect(query, title_keywords, days=days, session=session)
        except Exception as error:
            self.records.append(self._failed(query, error))
            raise
        # 크롤러가 돌려준 기사 dict를 그대로 보존한다(필드를 만들거나 바꾸지 않음).
        copies = [dict(article) for article in articles]
        self.records.append({"query": query, "status": "ok", "error": None,
                             "article_count": len(copies), "articles": copies})
        return articles

    @staticmethod
    def _failed(query, error):
        return {"query": query, "status": "failed", "error": _error_info(error),
                "article_count": 0, "articles": []}


def group_by_category(categories: dict, records: list[dict], field_results: list) -> list[dict]:
    """검색어 기록을 분야별로 묶는다. collect_all의 FieldResult와 개수가 맞는지 확인한다."""
    expected = [(name, query) for name, spec in categories.items() for query in spec["queries"]]
    if len(records) != len(expected) or any(
        record["query"] != query for record, (_, query) in zip(records, expected)
    ):
        raise RuntimeError("검색어 기록 순서가 분야 설정과 다릅니다.")

    by_name = {result.name: result for result in field_results}
    output, index = [], 0
    for name, spec in categories.items():
        queries = records[index:index + len(spec["queries"])]
        index += len(spec["queries"])
        result = by_name[name]
        succeeded = sum(1 for record in queries if record["status"] == "ok")
        articles = sum(record["article_count"] for record in queries)
        if (succeeded, len(queries) - succeeded, articles) != (
            result.succeeded_queries, result.failed_queries, result.articles
        ):
            raise RuntimeError(f"분야 {spec['code']}의 집계가 collect_all 결과와 다릅니다.")
        # collect_all과 같은 기준: 검색어가 하나도 성공하지 못한 분야만 실패
        if result.failed:
            status = "failed"
        elif result.failed_queries:
            status = "partial"
        else:
            status = "ok"
        output.append({
            "name": name,
            "code": spec["code"],
            "status": status,
            "succeeded_queries": result.succeeded_queries,
            "failed_queries": result.failed_queries,
            "article_count": result.articles,
            "queries": queries,
        })
    return output


def summarize(categories_out: list[dict], days: int, finished_at: datetime) -> dict:
    """실행 전체 상태. 우선순위: failed(전체 실패) > partial(일부 실패) > empty(성공했지만 0건) > ok."""
    succeeded = sum(item["succeeded_queries"] for item in categories_out)
    failed = sum(item["failed_queries"] for item in categories_out)
    articles = sum(item["article_count"] for item in categories_out)
    if succeeded == 0:
        status = "failed"
    elif failed:
        status = "partial"
    elif articles == 0:
        status = "empty"
    else:
        status = "ok"
    return {
        "status": status,
        "data_kind": DATA_KIND,
        "days": days,
        "category_count": len(categories_out),
        "query_count": succeeded + failed,
        "succeeded_queries": succeeded,
        "failed_queries": failed,
        # 분야·검색어별 합계라서 여러 분야·검색어에 걸친 같은 기사는 중복으로 센다(중복 제거는 Processor 담당).
        "article_count": articles,
        "failed_categories": [item["code"] for item in categories_out if item["status"] == "failed"],
        "partial_categories": [item["code"] for item in categories_out if item["status"] == "partial"],
        "finished_at": _iso_utc(finished_at),
    }


def failed_error_types(categories_out: list[dict]) -> dict[str, int]:
    """실패한 검색어의 오류 종류별 개수 (예: {"ConnectionError": 2}). 검색어·오류 종류에는 비밀정보가 없다."""
    counts: dict[str, int] = {}
    for category in categories_out:
        for query in category["queries"]:
            if query["error"]:
                counts[query["error"]["type"]] = counts.get(query["error"]["type"], 0) + 1
    return dict(sorted(counts.items()))


def build_raw_document(run_id: str, collected_at: datetime, categories_out: list[dict],
                       summary: dict) -> dict:
    """임시 내부 규격(raw). 최상위 필드는 schema_version, run_id, collected_at, categories, collection_summary."""
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "collected_at": _iso_utc(collected_at),
        "categories": categories_out,
        "collection_summary": summary,
    }


def serialize(document: dict) -> bytes:
    """UTF-8 JSON. 한글을 \\uXXXX로 바꾸지 않는다. 직렬화할 수 없는 값은 숨기지 않고 오류로 낸다."""
    return json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")


# -- S3 ------------------------------------------------------------------------
# 같은 키에 이미 객체가 있을 때 기존 raw를 확인하며 읽을 최대 크기
MAX_EXISTING_BYTES = 10 * 1024 * 1024


def _s3_error(error: BaseException) -> tuple[str | None, int | None]:
    """botocore ClientError의 (오류 코드, HTTP 상태). 다른 예외면 (None, None). botocore를 직접 불러오지 않는다."""
    response = getattr(error, "response", None)
    if not isinstance(response, Mapping):
        return None, None
    code = (response.get("Error") or {}).get("Code")
    status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
    return code, status


def existing_raw_summary(s3_client, bucket: str, key: str, run_id: str) -> dict:
    """조건부 쓰기가 412로 거절되었을 때, 이미 있는 객체가 같은 run_id의 정상 raw인지 확인한다.

    같으면 그 raw의 collection_summary를 돌려준다(정상적인 중복 실행).
    읽지 못하면 RawUploadError(재시도 대상), 내용이 다르면 RawConflictError(사람이 확인).
    """
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        body = response["Body"].read(MAX_EXISTING_BYTES + 1)
    except Exception as error:
        raise RawUploadError(
            f"이미 있는 raw를 확인하지 못했습니다: s3://{bucket}/{key} ({type(error).__name__})"
        ) from error
    try:
        existing = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RawConflictError(f"같은 키에 raw가 아닌 객체가 있습니다: s3://{bucket}/{key}") from error
    if not isinstance(existing, Mapping):
        raise RawConflictError(f"같은 키에 raw가 아닌 객체가 있습니다: s3://{bucket}/{key}")
    summary = existing.get("collection_summary")
    if (len(body) > MAX_EXISTING_BYTES
            or existing.get("schema_version") != SCHEMA_VERSION
            or existing.get("run_id") != run_id
            or not isinstance(summary, Mapping)
            or summary.get("status") not in {"ok", "partial", "empty"}):
        raise RawConflictError(f"같은 키에 다른 실행의 객체가 있습니다: s3://{bucket}/{key}")
    return dict(summary)


def upload_raw(s3_client, bucket: str, key: str, body: bytes, run_id: str) -> tuple[str, dict | None]:
    """IfNoneMatch="*" 조건부 쓰기. 처음 저장된 raw는 덮어쓰지 않는다.

    반환: ("created", None) 새로 저장 / ("already_exists", 기존 요약) 같은 run_id가 이미 저장됨(정상 중복 실행)
    예외: RawWriteConflictError(409, 동시 조건부 쓰기 충돌 → 재시도), RawConflictError(다른 내용),
          RawUploadError(그 밖의 실패·HTTP 200 미확인)
    """
    try:
        response = s3_client.put_object(Bucket=bucket, Key=key, Body=body, ContentType=CONTENT_TYPE,
                                        IfNoneMatch="*")
    except Exception as error:
        code, status = _s3_error(error)
        if code == "PreconditionFailed" or status == 412:
            return "already_exists", existing_raw_summary(s3_client, bucket, key, run_id)
        if code == "ConditionalRequestConflict" or status == 409:
            raise RawWriteConflictError(
                f"같은 키에 동시 쓰기가 진행 중이라 저장하지 못했습니다(재시도 대상): s3://{bucket}/{key}"
            ) from error
        raise RawUploadError(
            f"S3 업로드 실패: s3://{bucket}/{key} ({type(error).__name__})"
        ) from error
    status = ((response or {}).get("ResponseMetadata") or {}).get("HTTPStatusCode")
    if status != 200:
        raise RawUploadError(f"S3 업로드 결과를 확인하지 못했습니다: s3://{bucket}/{key} (HTTP {status})")
    return "created", None


# -- 실행 --------------------------------------------------------------------------
def run_collection(
    event: Mapping[str, Any] | None,
    context: Any,
    *,
    settings: Settings,
    s3_client,
    collector: tuple[dict, Callable] | None = None,
    session=None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """수집 → raw 문서 → S3 업로드. 테스트는 collector·session·s3_client를 바꿔 넣는다."""
    event = event if isinstance(event, Mapping) else {}
    started = now()
    run_id = resolve_run_id(event, context, started)
    key = build_object_key(settings.prefix, run_id)

    collect_module = _collect_module()
    categories, collect = collector if collector is not None else load_crawler()
    collect_module.check_categories(categories)

    deadline = None
    remaining = getattr(context, "get_remaining_time_in_millis", None)
    if callable(remaining):
        deadline = clock() + remaining() / 1000 - UPLOAD_RESERVE_SECONDS
    query_count = sum(len(spec["queries"]) for spec in categories.values())
    recorder = QueryRecorder(collect, deadline=deadline, clock=clock,
                             total_queries=query_count, pause_seconds=settings.pause_seconds)

    logger.info("뉴스 수집 시작 run_id=%s 분야 %d개 기간 %d일", run_id, len(categories), settings.days)
    _rows, field_results = collect_module.collect_all(
        categories, recorder, settings.days, settings.pause_seconds, session, logger.info,
    )
    categories_out = group_by_category(categories, recorder.records, field_results)
    summary = summarize(categories_out, settings.days, now())

    error_types = failed_error_types(categories_out)
    if summary["status"] == "failed":
        # 전체 실패: 업로드하지 않는다. raw/ 아래에 남기면 Processor가 정상 수집으로 처리할 수 있다.
        # Lambda 실패 기록(DLQ·on-failure destination)에는 예외 메시지만 남으므로 run_id와 오류 종류를 메시지에 넣는다.
        message = (f"모든 검색어 수집 실패로 raw를 저장하지 않음 run_id={run_id} "
                   f"검색어 {summary['failed_queries']}개 오류 {error_types}")
        logger.error(message)
        raise CollectionFailedError(message, summary)

    if summary["status"] == "partial":
        # 일부 실패는 저장하고 성공으로 끝내므로, 로그 수준(WARNING)으로 알림·지표 필터에 걸리게 한다.
        logger.warning("일부 검색어 수집 실패 run_id=%s 실패 분야=%s 부분 실패 분야=%s 실패 검색어 %d개 오류 %s",
                       run_id, summary["failed_categories"], summary["partial_categories"],
                       summary["failed_queries"], error_types)

    document = build_raw_document(run_id, started, categories_out, summary)
    outcome, existing_summary = upload_raw(s3_client, settings.bucket, key, serialize(document), run_id)
    if outcome == "already_exists":
        # 같은 run_id(예약 실행 재시도 등)가 이미 저장했다. 처음 raw를 보존하고 이번 수집 결과는 버린다.
        logger.info("같은 run_id의 raw가 이미 있어 보존함(덮어쓰지 않음) run_id=%s key=%s 기존 상태=%s",
                    run_id, key, existing_summary.get("status"))
        summary = existing_summary
    else:
        logger.info("raw 저장 완료 run_id=%s key=%s 상태=%s 검색어 성공 %d/%d 기사 %d건",
                    run_id, key, summary["status"], summary["succeeded_queries"],
                    summary["query_count"], summary["article_count"])
    return {
        "status": summary.get("status"),
        "outcome": outcome,
        "run_id": run_id,
        "bucket": settings.bucket,
        "key": key,
        "summary": summary,
    }


def _new_s3_client():
    """실제 Lambda에서만 boto3를 불러온다(자격증명은 Lambda 실행 역할을 쓴다)."""
    import boto3

    return boto3.client("s3")


def _new_session():
    import requests

    return requests.Session()


def ensure_conditional_write_supported(s3_client) -> None:
    """boto3/botocore가 PutObject의 IfNoneMatch를 아는지 로컬 서비스 모델로 확인한다(네트워크 요청 없음).

    모르는 버전이면 RSS를 수집하기 전에 ConfigError로 멈춘다(수집 후 업로드에서 실패하는 것보다 낫고,
    조건 없는 덮어쓰기로 대신하지 않는다). 서비스 모델이 없는 객체(테스트용 가짜 등)는 검사하지 않는다.
    """
    meta = getattr(s3_client, "meta", None)
    service_model = getattr(meta, "service_model", None)
    if service_model is None:
        return
    members = service_model.operation_model("PutObject").input_shape.members
    if "IfNoneMatch" not in members:
        raise ConfigError("런타임 boto3/botocore가 S3 조건부 쓰기(IfNoneMatch)를 지원하지 않습니다. "
                          "boto3를 갱신하거나 배포 묶음에 포함하세요.")


_S3_CLIENT = None


def lambda_handler(event, context):
    """AWS Lambda 진입점. 설정 오류·전체 수집 실패·업로드 실패는 예외로 끝내 Lambda 실패로 기록되게 한다."""
    global _S3_CLIENT
    settings = Settings.from_env()
    if _S3_CLIENT is None:
        client = _new_s3_client()
        ensure_conditional_write_supported(client)
        _S3_CLIENT = client
    session = _new_session()
    try:
        return run_collection(event, context, settings=settings, s3_client=_S3_CLIENT, session=session)
    finally:
        session.close()
