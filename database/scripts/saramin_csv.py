"""CSV contract shared by offline export, resume and PostgreSQL import."""
from __future__ import annotations
import csv
import json
import os
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse

ARRAY_FIELDS = ('job_roles', 'specialties', 'tech_stacks', 'preferences', 'raw_tags')
FIELDS = ('source', 'source_id', 'title', 'company', 'url', 'location', 'career',
    'education', 'employment_type', 'deadline_text', *ARRAY_FIELDS,
    'role_classification_source', 'specialty_classification_source', 'detail_status',
    'collected_at', 'collection_year', 'collection_quarter')
REQUIRED = ('source', 'source_id', 'title', 'url', 'role_classification_source',
    'specialty_classification_source', 'detail_status', 'collected_at')


def validate_job(row):
    job = dict(row)
    if any(not isinstance(job.get(k), str) or not job[k].strip() for k in REQUIRED if k != 'collected_at'):
        raise ValueError('필수 문자열 누락')
    if job['source'] != 'saramin_web' or not job['source_id'].isascii() or not job['source_id'].isdigit():
        raise ValueError('사람인 source/source_id 형식 오류')
    url = urlparse(job['url'])
    if url.scheme not in ('http', 'https') or url.hostname not in ('www.saramin.co.kr', 'saramin.co.kr'):
        raise ValueError('사람인 공고 URL 오류')
    for key in ARRAY_FIELDS:
        if not isinstance(job.get(key), list) or any(not isinstance(v, str) or not v.strip() for v in job[key]):
            raise ValueError(f'{key}: 문자열 배열 필요')
        job[key] = list(dict.fromkeys(job[key]))
    if not job['job_roles']:
        raise ValueError('직무가 확인되지 않은 공고')
    dt = job.get('collected_at')
    if not isinstance(dt, datetime):
        dt = datetime.fromisoformat(dt)
    job['collected_at'] = dt
    job['collection_year'] = int(job['collection_year'])
    job['collection_quarter'] = int(job['collection_quarter'])
    if (job['collection_year'], job['collection_quarter']) != (dt.year, (dt.month - 1) // 3 + 1):
        raise ValueError('수집일과 분기 불일치')
    return job


def read_csv(path, *, fields=FIELDS, array_fields=ARRAY_FIELDS, validator=validate_job):
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames) or not set(fields) <= set(reader.fieldnames):
            raise ValueError('CSV 필수 헤더 누락 또는 중복')
        for line, row in enumerate(reader, 2):
            try:
                if None in row or any(row[k] is None for k in fields):
                    raise ValueError('CSV 열 개수 불일치')
                for key in fields:
                    if key in array_fields:
                        row[key] = json.loads(row[key])
                    elif row[key] == '':
                        row[key] = None
                yield validator(row)
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError(f'CSV {line}행: {exc}') from exc


def write_csv(path, jobs, *, fields=FIELDS, array_fields=ARRAY_FIELDS, validator=validate_job):
    """Atomically replace only a path already reserved by this run."""
    path = Path(path)
    temp = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8-sig', newline='',
                dir=path.parent, delete=False) as stream:
            temp = Path(stream.name)
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in jobs:
                job = validator(row)
                writer.writerow({key: json.dumps(job[key], ensure_ascii=False) if key in array_fields
                    else job[key].isoformat() if hasattr(job[key], 'isoformat') else job.get(key) for key in fields})
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp and temp.exists():
            temp.unlink()


def reserve_path(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8'):
        pass


def write_report(path, report):
    path = Path(path)
    temp = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temp = Path(stream.name)
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp and temp.exists():
            temp.unlink()
