"""PlayMate 뉴스 Processor Lambda (Issue #133).

S3 ObjectCreated(raw/news/YYYY/MM/DD/<run_id>.json) → 이 Lambda → S3 processed/news/YYYY/MM/DD/<run_id>.json

- 정규화·중복 제거·분야 병합은 ``database/scripts/import_career_news.py``의 ``build_articles``
  (내부에서 ``normalize_link``, ``link_key_of``, ``link_type_of``, ``parse_published``, ``field_code_of``,
  ``clean_text`` 사용)를 고치지 않고 그대로 쓴다. DB 저장 함수 ``import_articles``는 부르지 않는다.
- raw 형식은 ``collector_handler.py``가 만든 임시 규격(0.1-draft)을 그대로 검증한다. 잘못된 raw를
  빈 뉴스 목록으로 처리하지 않고 오류로 끝낸다.
- 같은 raw 키는 항상 같은 processed 키로 저장하고, 같은 입력이면 같은 바이트를 만든다(처리 시각을 넣지 않음).
- 읽은 raw가 그사이 다른 내용으로 바뀌었으면(이벤트 순서 역전·재업로드) 저장하지 않는다.

자세한 규격과 남은 위험은 같은 폴더의 README.md를 본다.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping
from urllib.parse import unquote_plus

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

HERE = Path(__file__).resolve().parent
# 저장소에서 실행할 때의 루트. Lambda 배포 묶음에서는 쓰이지 않는다.
REPO_ROOT = HERE.parents[1]


def _load_module(name: str, directories: tuple[Path, ...]) -> ModuleType:
    """같은 이름의 다른 폴더 모듈이 섞이지 않도록 정해진 파일 경로에서만 불러온다."""
    for directory in directories:
        path = directory / f"{name}.py"
        if not path.is_file():
            continue
        existing = sys.modules.get(name)
        if existing is not None and Path(getattr(existing, "__file__", "") or "").resolve() == path.resolve():
            return existing
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module  # dataclass가 지연 평가 주석을 해석할 때 필요
        spec.loader.exec_module(module)
        return module
    raise ImportError(f"{name}.py를 찾을 수 없습니다 (배포 묶음 구성을 확인하세요).")


# raw 형식(스키마 버전·run_id 규칙·검사 함수)은 Collector와 한 곳에서 관리한다.
collector = _load_module("collector_handler", (HERE,))
importer = _load_module("import_career_news", (REPO_ROOT / "database" / "scripts", HERE))

SCHEMA_VERSION = "0.1-draft"
# 처리할 수 있는 raw 규격 버전
SUPPORTED_RAW_SCHEMAS = frozenset({collector.SCHEMA_VERSION})
DEFAULT_RAW_PREFIX = collector.DEFAULT_PREFIX  # raw/news/
DEFAULT_PROCESSED_PREFIX = "processed/news/"
CONTENT_TYPE = collector.CONTENT_TYPE
# raw는 검색어 28개 × 최대 30건 수준이라 수백 KB다. 비정상적으로 큰 객체는 읽지 않는다.
MAX_RAW_BYTES = 10 * 1024 * 1024
RAW_KEY_TAIL = re.compile(r"^(\d{4})/(\d{2})/(\d{2})/([^/]+)\.json$")
RAW_STATUSES = frozenset({"ok", "partial", "empty"})  # Collector는 failed를 저장하지 않는다.


class ConfigError(ValueError):
    """환경변수가 잘못되었다."""


class InvalidEventError(ValueError):
    """S3 이벤트 형식이 아니다."""


class RawReadError(RuntimeError):
    """raw 객체를 읽지 못했다."""


class RawValidationError(ValueError):
    """raw JSON이 깨졌거나 규격과 다르다. 빈 뉴스 목록으로 처리하지 않는다."""


class ProcessedWriteError(RuntimeError):
    """processed 객체 저장에 실패했거나 성공을 확인하지 못했다."""


class ProcessingError(RuntimeError):
    """한 개 이상의 레코드 처리에 실패했다. 성공한 레코드는 이미 저장되었다."""

    def __init__(self, message: str, results: list[dict]):
        super().__init__(message)
        self.results = results


# -- 설정 ---------------------------------------------------------------------
@dataclass(frozen=True)
class ProcessorSettings:
    raw_prefix: str = DEFAULT_RAW_PREFIX
    processed_prefix: str = DEFAULT_PROCESSED_PREFIX
    # 비우면 raw와 같은 버킷에 저장한다.
    processed_bucket: str | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "ProcessorSettings":
        env = os.environ if environ is None else environ
        try:
            raw_prefix = collector.normalize_prefix(env.get("NEWS_RAW_PREFIX") or DEFAULT_RAW_PREFIX)
        except collector.ConfigError as error:
            raise ConfigError(str(error)) from error
        processed_prefix = normalize_processed_prefix(env.get("NEWS_PROCESSED_PREFIX") or DEFAULT_PROCESSED_PREFIX)
        bucket = (env.get("NEWS_PROCESSED_BUCKET") or "").strip() or None
        if bucket is not None and not collector.BUCKET_PATTERN.fullmatch(bucket):
            raise ConfigError("NEWS_PROCESSED_BUCKET 값이 S3 버킷 이름 형식이 아닙니다.")
        return cls(raw_prefix=raw_prefix, processed_prefix=processed_prefix, processed_bucket=bucket)


def normalize_processed_prefix(prefix: str) -> str:
    """processed/ 아래만 허용한다. raw/에 쓰면 Processor가 자기 출력으로 다시 호출된다."""
    value = prefix.strip().lstrip("/")
    if not value.endswith("/"):
        value += "/"
    if not value.startswith("processed/") or ".." in value.split("/"):
        raise ConfigError("NEWS_PROCESSED_PREFIX는 processed/로 시작하는 경로여야 합니다.")
    return value


# -- S3 이벤트 ------------------------------------------------------------------
def decode_s3_key(raw_key: str) -> str:
    """S3 이벤트의 객체 키는 URL 인코딩되고 공백은 '+'로 온다."""
    return unquote_plus(raw_key)


def parse_record(record: Any) -> dict:
    """레코드에서 버킷·키·버전을 꺼낸다. 처리 대상이 아니면 skip 사유를 담는다."""
    if not isinstance(record, Mapping):
        raise InvalidEventError("Records 항목이 객체가 아닙니다.")
    if record.get("eventSource") != "aws:s3":
        return {"skip": "not_s3_event"}
    if not str(record.get("eventName", "")).startswith("ObjectCreated:"):
        return {"skip": "not_object_created"}
    s3 = record.get("s3") or {}
    bucket = (s3.get("bucket") or {}).get("name")
    obj = s3.get("object") or {}
    key = obj.get("key")
    if not isinstance(bucket, str) or not bucket or not isinstance(key, str) or not key:
        raise InvalidEventError("S3 레코드에 버킷 이름이나 객체 키가 없습니다.")
    return {
        "bucket": bucket,
        "key": decode_s3_key(key),
        "event_version_id": obj.get("versionId"),
        "sequencer": obj.get("sequencer"),
    }


def processed_key_for(raw_key: str, settings: ProcessorSettings) -> tuple[str, str]:
    """raw/news/YYYY/MM/DD/<run_id>.json → (processed/news/YYYY/MM/DD/<run_id>.json, run_id).

    날짜가 run_id의 시각과 다르거나 run_id 형식이 아니면 RawValidationError.
    """
    tail = raw_key[len(settings.raw_prefix):]
    match = RAW_KEY_TAIL.fullmatch(tail)
    if not match:
        raise RawValidationError(f"raw 키 형식이 아닙니다: {raw_key}")
    year, month, day, run_id = match.groups()
    run_match = collector.RUN_ID_PATTERN.fullmatch(run_id)
    if not run_match or run_match.group(1)[:8] != f"{year}{month}{day}":
        raise RawValidationError(f"raw 키의 run_id·날짜가 맞지 않습니다: {raw_key}")
    return f"{settings.processed_prefix}{year}/{month}/{day}/{run_id}.json", run_id


# -- raw 검증 -------------------------------------------------------------------
def _require(mapping: Any, field: str, kind: type | tuple[type, ...], path: str):
    if not isinstance(mapping, Mapping):
        raise RawValidationError(f"{path}가 객체가 아닙니다.")
    if field not in mapping:
        raise RawValidationError(f"{path}.{field} 누락")
    value = mapping[field]
    if not isinstance(value, kind):
        raise RawValidationError(f"{path}.{field} 형식 오류")
    return value


def validate_raw(document: Any, expected_run_id: str) -> None:
    """Collector raw 규격을 검사한다. 집계가 분야·검색어 기록과 맞지 않아도 오류로 본다."""
    schema = _require(document, "schema_version", str, "raw")
    if schema not in SUPPORTED_RAW_SCHEMAS:
        raise RawValidationError(f"지원하지 않는 raw 규격 버전: {schema}")
    if _require(document, "run_id", str, "raw") != expected_run_id:
        raise RawValidationError("raw.run_id가 객체 키의 run_id와 다릅니다.")
    _require(document, "collected_at", str, "raw")
    categories = _require(document, "categories", list, "raw")
    summary = _require(document, "collection_summary", Mapping, "raw")
    status = _require(summary, "status", str, "raw.collection_summary")
    if status not in RAW_STATUSES:
        raise RawValidationError(f"처리할 수 없는 수집 상태: {status}")

    for ci, category in enumerate(categories):
        cpath = f"raw.categories[{ci}]"
        _require(category, "name", str, cpath)
        code = _require(category, "code", str, cpath)
        if code not in importer.FIELD_CODE_VALUES:
            raise RawValidationError(f"{cpath}.code가 PlayMate 분야 코드가 아닙니다: {code}")
        if _require(category, "status", str, cpath) not in {"ok", "partial", "failed"}:
            raise RawValidationError(f"{cpath}.status 값 오류")
        for name in ("succeeded_queries", "failed_queries", "article_count"):
            _require(category, name, int, cpath)
        for qi, query in enumerate(_require(category, "queries", list, cpath)):
            qpath = f"{cpath}.queries[{qi}]"
            _require(query, "query", str, qpath)
            qstatus = _require(query, "status", str, qpath)
            articles = _require(query, "articles", list, qpath)
            _require(query, "article_count", int, qpath)
            if "error" not in query:
                raise RawValidationError(f"{qpath}.error 누락")
            if qstatus == "ok":
                if query["error"] is not None:
                    raise RawValidationError(f"{qpath}: 성공한 검색어에 오류 정보가 있습니다.")
            elif qstatus == "failed":
                _require(query, "error", Mapping, qpath)
                _require(query["error"], "type", str, f"{qpath}.error")
                _require(query["error"], "message", str, f"{qpath}.error")
                if articles:
                    raise RawValidationError(f"{qpath}: 실패한 검색어에 기사가 있습니다.")
            else:
                raise RawValidationError(f"{qpath}.status 값 오류")
            if query["article_count"] != len(articles):
                raise RawValidationError(f"{qpath}.article_count가 기사 수와 다릅니다.")
            for ai, article in enumerate(articles):
                apath = f"{qpath}.articles[{ai}]"
                for field in ("title", "source", "link"):
                    _require(article, field, str, apath)
                _require(article, "published", (str, type(None)), apath)

    # 분야·검색어 기록으로 다시 계산한 집계가 raw 요약과 같아야 한다(어긋난 raw를 추측해 고치지 않음).
    try:
        recomputed = collector.group_by_category(
            {c["name"]: {"code": c["code"], "queries": [q["query"] for q in c["queries"]]} for c in categories},
            [q for c in categories for q in c["queries"]],
            [_FieldCounts(c) for c in categories],
        )
    except RuntimeError as error:
        raise RawValidationError(f"분야별 집계가 검색어 기록과 다릅니다: {error}") from error
    if [c["status"] for c in recomputed] != [c["status"] for c in categories]:
        raise RawValidationError("분야 상태가 검색어 기록과 다릅니다.")
    expected = collector.summarize(recomputed, 0, datetime.now(timezone.utc))
    for field in ("status", "query_count", "succeeded_queries", "failed_queries", "article_count",
                  "failed_categories", "partial_categories"):
        if summary.get(field) != expected[field]:
            raise RawValidationError(f"raw.collection_summary.{field}가 분야·검색어 기록과 다릅니다.")


class _FieldCounts:
    """collector.group_by_category가 기대하는 collect_all FieldResult 모양(raw 값으로 채움)."""

    def __init__(self, category: Mapping):
        self.name = category["name"]
        self.succeeded_queries = category["succeeded_queries"]
        self.failed_queries = category["failed_queries"]
        self.articles = category["article_count"]

    @property
    def failed(self) -> bool:
        return self.succeeded_queries == 0


# -- 변환 -----------------------------------------------------------------------
def raw_rows(document: Mapping) -> list[tuple]:
    """build_articles 입력 행: (분야 코드, 제목, 언론사, 링크, 발행일). 성공한 검색어의 기사만 있다."""
    return [
        (category["code"], article["title"], article["source"], article["link"], article["published"])
        for category in document["categories"]
        for query in category["queries"]
        for article in query["articles"]
    ]


def _utc_text(value) -> str | None:
    """parse_published가 돌려준 시간대 없는 UTC 시각을 'Z'를 붙인 ISO8601로 쓴다."""
    if value is None:
        return None
    return value.isoformat(timespec="seconds") + "Z"


def article_to_json(article) -> dict:
    """NewsArticle 필드 이름을 그대로 쓴다(career_news 컬럼과 같은 이름)."""
    return {
        "link_key": article.link_key,
        "link_url": article.link_url,
        "link_type": article.link_type,
        "title": article.title,
        "source_name": article.source_name,
        "published_at": _utc_text(article.published_at),
        "field_codes": sorted(article.field_codes),
    }


def build_processed_document(document: Mapping, raw_bucket: str, raw_key: str,
                             raw_version_id: str | None, raw_etag: str | None) -> dict:
    """processed 임시 규격. 실행 정보·수집 결과(raw 그대로)·처리 결과·기사를 나눠 둔다.

    처리 시각을 넣지 않아 같은 입력이면 같은 바이트가 된다(저장 시각은 S3 LastModified).
    """
    rows = raw_rows(document)
    articles, skipped = importer.build_articles(rows)
    articles_json = [article_to_json(article) for article in articles]
    raw_status = document["collection_summary"]["status"]
    if raw_status == "partial":
        status = "partial"
    elif not articles_json:
        status = "empty"
    else:
        status = "ok"
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": document["run_id"],
        "source_raw_key": raw_key,
        "source": {
            "bucket": raw_bucket,
            "version_id": raw_version_id,
            "etag": raw_etag,
            "raw_schema_version": document["schema_version"],
            "collected_at": document["collected_at"],
        },
        "collection": {
            # raw 요약을 바꾸지 않고 옮긴다. 실패 분야 처리 정책은 DB 적재 담당과 합의 사항이다.
            "summary": dict(document["collection_summary"]),
            "categories": [
                {key: category[key] for key in
                 ("name", "code", "status", "succeeded_queries", "failed_queries", "article_count")}
                for category in document["categories"]
            ],
            "query_failures": [
                {"category_code": category["code"], "query": query["query"], "error": dict(query["error"])}
                for category in document["categories"]
                for query in category["queries"]
                if query["status"] == "failed"
            ],
        },
        "processing": {
            "status": status,
            "input_rows": len(rows),
            "article_count": len(articles_json),
            "multi_field_article_count": sum(1 for a in articles_json if len(a["field_codes"]) > 1),
            "skipped": dict(sorted(skipped.items())),
        },
        "articles": articles_json,
    }


def serialize(document: dict) -> bytes:
    return json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")


# -- S3 입출력 -------------------------------------------------------------------
def read_raw(s3_client, bucket: str, key: str) -> tuple[Any, str | None, str | None]:
    """(JSON 문서, VersionId, ETag). 읽기 실패는 RawReadError, 깨진 JSON은 RawValidationError."""
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        length = response.get("ContentLength")
        if isinstance(length, int) and length > MAX_RAW_BYTES:
            raise RawValidationError(f"raw 객체가 너무 큽니다: {length} bytes")
        body = response["Body"].read(MAX_RAW_BYTES + 1)
    except RawValidationError:
        raise
    except Exception as error:
        raise RawReadError(f"S3 읽기 실패: s3://{bucket}/{key} ({type(error).__name__})") from error
    if len(body) > MAX_RAW_BYTES:
        raise RawValidationError("raw 객체가 너무 큽니다.")
    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RawValidationError(f"raw JSON 형식 오류: {type(error).__name__}") from error
    return document, response.get("VersionId"), response.get("ETag")


def is_still_current(s3_client, bucket: str, key: str, version_id: str | None, etag: str | None) -> bool:
    """읽은 뒤 같은 키에 다른 내용이 올라왔는지 확인한다. 바뀌었으면 그 업로드의 이벤트가 처리한다."""
    try:
        head = s3_client.head_object(Bucket=bucket, Key=key)
    except Exception as error:
        raise RawReadError(f"S3 상태 확인 실패: s3://{bucket}/{key} ({type(error).__name__})") from error
    return head.get("ETag") == etag and head.get("VersionId") == version_id


def write_processed(s3_client, bucket: str, key: str, body: bytes) -> None:
    try:
        response = s3_client.put_object(Bucket=bucket, Key=key, Body=body, ContentType=CONTENT_TYPE)
    except Exception as error:
        raise ProcessedWriteError(f"S3 저장 실패: s3://{bucket}/{key} ({type(error).__name__})") from error
    status = ((response or {}).get("ResponseMetadata") or {}).get("HTTPStatusCode")
    if status != 200:
        raise ProcessedWriteError(f"S3 저장 결과를 확인하지 못했습니다: s3://{bucket}/{key} (HTTP {status})")


# -- 실행 -------------------------------------------------------------------------
def process_record(record: Any, *, settings: ProcessorSettings, s3_client) -> dict:
    """레코드 하나를 처리한다. 결과 status: written / skipped / superseded. 실패는 예외."""
    parsed = parse_record(record)
    if "skip" in parsed:
        return {"status": "skipped", "reason": parsed["skip"]}
    bucket, key = parsed["bucket"], parsed["key"]
    # processed/ 등 raw 접두사 밖의 키는 읽지 않는다(트리거 설정이 잘못돼도 자기 출력으로 반복하지 않음).
    if not key.startswith(settings.raw_prefix):
        return {"status": "skipped", "reason": "outside_raw_prefix", "raw_key": key}
    if not key.endswith(".json"):
        return {"status": "skipped", "reason": "not_json", "raw_key": key}

    processed_key, run_id = processed_key_for(key, settings)
    document, version_id, etag = read_raw(s3_client, bucket, key)
    validate_raw(document, run_id)
    processed = build_processed_document(document, bucket, key, version_id, etag)
    body = serialize(processed)

    result = {
        "raw_key": key,
        "processed_key": processed_key,
        "run_id": run_id,
        "raw_version_id": version_id,
        "event_version_id": parsed["event_version_id"],
        "collection_status": document["collection_summary"]["status"],
        "processing_status": processed["processing"]["status"],
        "article_count": processed["processing"]["article_count"],
    }
    if not is_still_current(s3_client, bucket, key, version_id, etag):
        logger.warning("raw가 처리 중 다시 업로드되어 저장하지 않음 key=%s", key)
        return {**result, "status": "superseded"}
    write_processed(s3_client, settings.processed_bucket or bucket, processed_key, body)
    logger.info("processed 저장 완료 key=%s 상태=%s 기사 %d건", processed_key,
                result["processing_status"], result["article_count"])
    return {**result, "status": "written", "processed_bucket": settings.processed_bucket or bucket}


def process_event(event: Any, *, settings: ProcessorSettings, s3_client) -> dict:
    """모든 레코드를 처리한다. 하나라도 실패하면 나머지를 처리한 뒤 ProcessingError로 끝낸다."""
    if not isinstance(event, Mapping) or not isinstance(event.get("Records"), list):
        raise InvalidEventError("S3 이벤트에 Records 배열이 없습니다.")
    results = []
    for index, record in enumerate(event["Records"]):
        try:
            results.append(process_record(record, settings=settings, s3_client=s3_client))
        except Exception as error:  # 레코드별 실패를 모아 마지막에 알린다
            key = None
            try:
                key = decode_s3_key(record["s3"]["object"]["key"])
            except Exception:
                pass
            logger.error("raw 처리 실패 record=%d key=%s %s: %s", index, key, type(error).__name__, error)
            results.append({"status": "failed", "raw_key": key, "error": {
                "type": type(error).__name__, "message": str(error)[:collector.ERROR_MESSAGE_LIMIT]}})
    failed = [result for result in results if result["status"] == "failed"]
    if failed:
        keys = [result["raw_key"] for result in failed]
        raise ProcessingError(f"raw 처리 실패 {len(failed)}/{len(results)}건: {keys}", results)
    return {"status": "ok", "results": results}


def _new_s3_client():
    """실제 Lambda에서만 boto3를 불러온다(자격증명은 Lambda 실행 역할)."""
    import boto3

    return boto3.client("s3")


_S3_CLIENT = None


def lambda_handler(event, context):
    """AWS Lambda 진입점. 처리 실패·설정 오류는 예외로 끝내 Lambda 실패(재시도·DLQ 대상)로 남긴다."""
    global _S3_CLIENT
    settings = ProcessorSettings.from_env()
    if _S3_CLIENT is None:
        _S3_CLIENT = _new_s3_client()
    return process_event(event, settings=settings, s3_client=_S3_CLIENT)
