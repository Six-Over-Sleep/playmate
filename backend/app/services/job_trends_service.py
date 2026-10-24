"""사람인 JSON 공통 정규화 및 원자적 적재. 외부 API를 호출하지 않는다."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re

from app.core.db_connect import db_cursor
from app.repositories import job_trends_repository as repository
from app.services.job_trends_catalog import ROLES


class SaraminResponseError(ValueError):
    """공식 API 오류 또는 잘못된 응답 컨테이너."""


@dataclass
class LoadReport:
    success: int = 0
    failed: int = 0
    duplicate: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


class JobTrendsLoadError(RuntimeError):
    def __init__(self, report):
        super().__init__("취업 공고 적재가 실패했습니다. 트랜잭션 결과를 확인하세요.")
        self.report = report


def _object(value):
    return value if isinstance(value, dict) else {}


def _text(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("문자열/코드 타입 오류")
    return str(value).strip() or None


def _timestamp(value):
    if value is None or value == "":
        return None
    # 채용시/상시 공고의 비양수 마감 값은 날짜로 추측하지 않는다.
    number = int(value)
    return datetime.fromtimestamp(number, timezone.utc) if number > 0 else None


def normalize_job(job, source):
    """원본 필드 보존. 급여 범위·대표 직무는 추측하지 않는다."""
    if source not in {"mock", "saramin"}:
        raise ValueError("지원하지 않는 source")
    if not isinstance(job, dict):
        raise ValueError("공고 객체가 필요합니다")
    job_id = _text(job.get("id"))
    if job_id is None:
        raise ValueError("공고 ID 누락")
    position = _object(job.get("position"))
    salary = _object(job.get("salary"))
    active = job.get("active")
    if active is not None and active not in (0, 1, "0", "1"):
        raise ValueError("active 값 오류")
    row = {
        "source": source, "source_job_id": job_id,
        "source_url": _text(job.get("url")),
        "is_active": None if active is None else str(active) == "1",
        "company_name": _text(_object(_object(job.get("company")).get("detail")).get("name")),
        "title": _text(position.get("title")),
        "keyword_text": _text(job.get("keyword")),
        "salary_code": _text(salary.get("code")),
        "salary_name": _text(salary.get("name")),
        "salary_min_manwon": None, "salary_max_manwon": None,
        "raw_payload": job,
    }
    for target, key in [("posted_at", "posting-timestamp"), ("modified_at", "modification-timestamp"), ("expires_at", "expiration-timestamp")]:
        row[target] = _timestamp(job.get(key))
    for target, key in [("location", "location"), ("industry", "industry")]:
        node = _object(position.get(key))
        row[target + "_code"] = _text(node.get("code"))
        row[target + "_name"] = _text(node.get("name"))
    for target, key in [("job_type_code", "job-type"), ("job_mid_code", "job-mid-code"), ("job_code", "job-code"), ("experience_code", "experience-level"), ("education_code", "required-education-level")]:
        row[target] = _text(_object(position.get(key)).get("code"))
    return row


def parse_response(payload, source):
    if source not in {"mock", "saramin"}:
        raise ValueError("지원하지 않는 source")
    if not isinstance(payload, dict):
        raise SaraminResponseError("JSON 객체가 필요합니다")
    if "code" in payload or "result" in payload:
        raise SaraminResponseError("사람인 API 오류 응답")
    jobs = payload.get("jobs")
    if not isinstance(jobs, dict) or not isinstance(jobs.get("job"), list):
        raise SaraminResponseError("jobs.job 배열이 필요합니다")
    try:
        count, start, total = (int(jobs[key]) for key in ("count", "start", "total"))
    except (KeyError, TypeError, ValueError) as exc:
        raise SaraminResponseError("페이지 메타데이터 오류") from exc
    if count != len(jobs["job"]) or min(count, start, total) < 0 or total < count:
        raise SaraminResponseError("페이지 건수 불일치")
    report = LoadReport()
    unique = {}
    for index, job in enumerate(jobs["job"]):
        try:
            row = normalize_job(job, source)
        except (ValueError, TypeError, OverflowError, OSError):
            report.failed += 1
            report.errors.append(f"공고 배열 {index}: 정규화 실패")
            continue
        if row["source_job_id"] in unique:
            report.duplicate += 1
            report.skipped += 1
        # 동일 입력 내 중복은 마지막 공고로 결정한다.
        unique[row["source_job_id"]] = row
    return list(unique.values()), report


def classify_roles(row):
    """명시적인 내부 직무명만 연결한다. 미분류와 복수 분류를 허용한다."""
    title = (row["title"] or "").casefold()
    return [code for _, code, name in ROLES if name.casefold() in title]


def keyword_mentions(row, aliases):
    """aliases: (keyword_code, alias_text) 목록. 근거 텍스트 출처를 보존한다."""
    mentions = set()
    for code, alias in aliases:
        if not alias.strip():
            continue
        pattern = r"(?<!\w)" + re.escape(alias) + r"(?!\w)"
        for source, text in [("title", row["title"]), ("api_keyword", row["keyword_text"])]:
            if text and re.search(pattern, text, re.IGNORECASE):
                mentions.add((code, source))
    return sorted(mentions)


def load_response(payload, source):
    rows, report = parse_response(payload, source)
    if not rows:
        return report
    try:
        with db_cursor(commit=True) as cursor:
            inserted, existing = repository.save_postings(cursor, rows)
        report.success = inserted + existing
        report.duplicate += existing
    except Exception as exc:
        report.failed += len(rows)
        raise JobTrendsLoadError(report) from exc
    return report
