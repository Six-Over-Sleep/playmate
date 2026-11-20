"""Site-specific contract on the existing atomic CSV storage implementation."""
from datetime import datetime, timezone
from urllib.parse import urlparse
import re
import saramin_csv as storage

ARRAY_FIELDS = ('job_role', 'tech_stack', 'requirements', 'preferred_qualifications')
FIELDS = ('source', 'source_job_id', 'job_url', 'original_url', 'company_name',
    'job_title', 'job_category', 'job_role', 'experience', 'employment_type',
    'location', 'tech_stack', 'requirements', 'preferred_qualifications',
    'posted_at', 'deadline_at', 'collected_at', 'detail_status')


def validate_job(row):
    job = {key: row.get(key) for key in FIELDS}
    for key in ('source', 'source_job_id', 'job_url', 'job_title', 'job_category', 'detail_status'):
        if not isinstance(job[key], str) or not job[key].strip():
            raise ValueError(f'{key}: 필수 문자열 누락')
    if job['source'] != 'itchaeyong' or job['job_category'] != 'dev':
        raise ValueError('itchaeyong 개발 공고만 허용')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', job['source_job_id']) or job['source_job_id'] == 'dev':
        raise ValueError('공고 ID 오류')
    if job['job_url'] != f"https://itchaeyong.com/jobs/{job['source_job_id']}":
        raise ValueError('공고 URL/ID 불일치')
    for key in ('company_name', 'experience', 'employment_type', 'location', 'original_url'):
        if job[key] is not None and not isinstance(job[key], str):
            raise ValueError(f'{key}: 문자열 또는 NULL 필요')
        if isinstance(job[key], str):
            job[key] = job[key].strip() or None
    if job['original_url']:
        url = urlparse(job['original_url'])
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
            raise ValueError('원본 URL 오류')
    for key in ARRAY_FIELDS:
        if not isinstance(job[key], list) or any(not isinstance(v, str) or not v.strip() for v in job[key]):
            raise ValueError(f'{key}: 문자열 배열 필요')
        job[key] = list(dict.fromkeys(job[key]))
    for key in ('collected_at', 'posted_at', 'deadline_at'):
        value = job[key]
        if value is None and key != 'collected_at':
            continue
        if not isinstance(value, datetime):
            value = datetime.fromisoformat(value)
        if value.tzinfo is None:
            raise ValueError(f'{key}: 시간대 필요')
        job[key] = value.astimezone(timezone.utc)
    return job


def read_csv(path):
    return storage.read_csv(path, fields=FIELDS, array_fields=ARRAY_FIELDS, validator=validate_job)


def write_csv(path, jobs):
    return storage.write_csv(path, jobs, fields=FIELDS, array_fields=ARRAY_FIELDS, validator=validate_job)


def dedupe_jobs(rows):
    jobs, duplicate_count = {}, 0
    for row in rows:
        row = validate_job(row)
        key = (row['source'], row['source_job_id'])
        if key in jobs:
            duplicate_count += 1
            previous = jobs[key]
            for field in ARRAY_FIELDS:
                row[field] = list(dict.fromkeys(previous[field] + row[field]))
            for field in ('original_url', 'company_name', 'experience', 'employment_type', 'location', 'posted_at', 'deadline_at'):
                row[field] = row[field] or previous[field]
            row['collected_at'] = min(row['collected_at'], previous['collected_at'])
            if row['detail_status'] != 'parsed' and previous['detail_status'] == 'parsed':
                row['detail_status'] = 'parsed'
        jobs[key] = row
    return list(jobs.values()), duplicate_count
