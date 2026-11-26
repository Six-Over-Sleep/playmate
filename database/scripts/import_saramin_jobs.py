"""Normalize/dedupe crawler results and UPSERT into public.job_postings.

The caller supplies a cursor managed by Playmate db_cursor(commit=True).
No direct DB connection or schema creation lives in the crawler package.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

ARRAY_FIELDS = ('job_roles', 'specialties', 'tech_stacks')
LOCK_KEY = 740_014_020

@dataclass
class ImportReport:
    total: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0

def dedupe_jobs(jobs: Iterable[dict]) -> tuple[list[dict], int]:
    by_key = {}
    skipped = 0
    for job in jobs:
        source_id = str(job.get('source_id') or '').strip()
        title = str(job.get('title') or '').strip()
        if not source_id or not title:
            skipped += 1
            continue
        key = (job.get('source', 'saramin_web'), source_id)
        if key in by_key:
            previous = by_key[key]
            for column in ARRAY_FIELDS:
                job[column] = list(dict.fromkeys([*(previous.get(column) or []), *(job.get(column) or [])]))
        by_key[key] = job
    return list(by_key.values()), skipped

def import_jobs(cursor, jobs: Iterable[dict]) -> ImportReport:
    from psycopg.types.json import Jsonb
    normalized, skipped = dedupe_jobs(jobs)
    report = ImportReport(total=len(normalized), skipped=skipped)
    if not normalized:
        return report
    cursor.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK_KEY,))
    for job in normalized:
        payload = {
            'source': job.get('source') or 'saramin_web',
            'source_id': str(job['source_id']),
            'title': job['title'],
            'company': job.get('company'),
            'url': job['url'],
            'job_roles': job.get('job_roles') or [],
            'specialties': job.get('specialties') or [],
            'tech_stacks': job.get('tech_stacks') or [],
            'raw_tags': Jsonb(job.get('raw_tags') or []),
            'role_classification_source': job.get('role_classification_source'),
            'detail_status': job.get('detail_status'),
            'collected_at': job.get('collected_at'),
            'collection_year': job.get('collection_year'),
            'collection_quarter': job.get('collection_quarter'),
        }
        cursor.execute("""
            INSERT INTO public.job_postings (
                source, source_id, title, company, url,
                job_roles, specialties, tech_stacks, raw_tags,
                role_classification_source, detail_status,
                collected_at, collection_year, collection_quarter
            ) VALUES (
                %(source)s, %(source_id)s, %(title)s, %(company)s, %(url)s,
                %(job_roles)s, %(specialties)s, %(tech_stacks)s, %(raw_tags)s,
                %(role_classification_source)s, %(detail_status)s,
                %(collected_at)s, %(collection_year)s, %(collection_quarter)s
            )
            ON CONFLICT (source, source_id) DO UPDATE SET
                title = EXCLUDED.title,
                company = EXCLUDED.company,
                url = EXCLUDED.url,
                job_roles = EXCLUDED.job_roles,
                specialties = EXCLUDED.specialties,
                tech_stacks = EXCLUDED.tech_stacks,
                raw_tags = EXCLUDED.raw_tags,
                role_classification_source = EXCLUDED.role_classification_source,
                detail_status = EXCLUDED.detail_status,
                updated_at = NOW()
            RETURNING (xmax = 0) AS inserted
        """, payload)
        result = cursor.fetchone()
        was_inserted = result['inserted'] if isinstance(result, dict) else result[0]
        if was_inserted:
            report.inserted += 1
        else:
            report.updated += 1
    return report
