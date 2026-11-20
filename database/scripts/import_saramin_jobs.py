"""Normalize/dedupe crawler results and UPSERT into saramin_job_postings.

The caller supplies a cursor managed by Playmate db_cursor(commit=True).
No direct DB connection or schema creation lives in the crawler package.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

ALLOWED_JSON_FIELDS = ('job_roles','specialties','tech_stacks','preferences','raw_tags')
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
        job = dict(job)
        key = (job.get('source', 'saramin_web'), source_id)
        if key in by_key:
            skipped += 1
            previous = by_key[key]
            for column in ALLOWED_JSON_FIELDS:
                job[column] = list(dict.fromkeys([*(previous.get(column) or []), *(job.get(column) or [])]))
            for column in ('company', 'deadline_text', 'location', 'career', 'education', 'employment_type'):
                if not job.get(column):
                    job[column] = previous.get(column)
            if job.get('detail_status') in ('not_requested', 'unavailable', 'iframe_present_unparsed') and previous.get('preferences'):
                job['detail_status'] = previous.get('detail_status', 'parsed')
        by_key[key] = job
    return list(by_key.values()), skipped

def import_jobs(cursor, jobs: Iterable[dict]) -> ImportReport:
    from psycopg2.extras import Json
    normalized, skipped = dedupe_jobs(jobs)
    report = ImportReport(total=len(normalized), skipped=skipped)
    if not normalized:
        return report
    cursor.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK_KEY,))
    for job in normalized:
        payload = dict(job)
        for key in ALLOWED_JSON_FIELDS:
            payload[key] = Json(payload.get(key) or [])
        cursor.execute("""
            INSERT INTO saramin_job_postings (
                source, source_id, title, company, url, deadline_text,
                location, career, education, employment_type,
                job_roles, specialties, tech_stacks, preferences, raw_tags,
                role_classification_source, specialty_classification_source,
                detail_status, collected_at, collection_year, collection_quarter
            ) VALUES (
                %(source)s,%(source_id)s,%(title)s,%(company)s,%(url)s,%(deadline_text)s,
                %(location)s,%(career)s,%(education)s,%(employment_type)s,
                %(job_roles)s,%(specialties)s,%(tech_stacks)s,%(preferences)s,%(raw_tags)s,
                %(role_classification_source)s,%(specialty_classification_source)s,
                %(detail_status)s,%(collected_at)s,%(collection_year)s,%(collection_quarter)s
            )
            ON CONFLICT (source, source_id) DO UPDATE SET
                title = EXCLUDED.title,
                company = COALESCE(EXCLUDED.company, saramin_job_postings.company),
                url = EXCLUDED.url,
                deadline_text = COALESCE(EXCLUDED.deadline_text, saramin_job_postings.deadline_text),
                location = COALESCE(EXCLUDED.location, saramin_job_postings.location),
                career = COALESCE(EXCLUDED.career, saramin_job_postings.career),
                education = COALESCE(EXCLUDED.education, saramin_job_postings.education),
                employment_type = COALESCE(EXCLUDED.employment_type, saramin_job_postings.employment_type),
                job_roles = (SELECT COALESCE(jsonb_agg(DISTINCT item), '[]'::jsonb)
                    FROM jsonb_array_elements(saramin_job_postings.job_roles || EXCLUDED.job_roles) AS item),
                specialties = (SELECT COALESCE(jsonb_agg(DISTINCT item), '[]'::jsonb)
                    FROM jsonb_array_elements(saramin_job_postings.specialties || EXCLUDED.specialties) AS item),
                tech_stacks = (SELECT COALESCE(jsonb_agg(DISTINCT item), '[]'::jsonb)
                    FROM jsonb_array_elements(saramin_job_postings.tech_stacks || EXCLUDED.tech_stacks) AS item),
                preferences = CASE WHEN (EXCLUDED.detail_status IN ('not_requested', 'unavailable', 'iframe_present_unparsed') OR EXCLUDED.preferences = '[]'::jsonb)
                    THEN saramin_job_postings.preferences ELSE
                    (SELECT COALESCE(jsonb_agg(DISTINCT item), '[]'::jsonb)
                    FROM jsonb_array_elements(saramin_job_postings.preferences || EXCLUDED.preferences) AS item) END,
                raw_tags = (SELECT COALESCE(jsonb_agg(DISTINCT item), '[]'::jsonb)
                    FROM jsonb_array_elements(saramin_job_postings.raw_tags || EXCLUDED.raw_tags) AS item),
                role_classification_source = EXCLUDED.role_classification_source,
                specialty_classification_source = EXCLUDED.specialty_classification_source,
                detail_status = CASE WHEN (EXCLUDED.detail_status IN ('not_requested', 'unavailable', 'iframe_present_unparsed') OR EXCLUDED.preferences = '[]'::jsonb)
                    THEN saramin_job_postings.detail_status ELSE EXCLUDED.detail_status END,
                last_seen_at = NOW()
            RETURNING (xmax = 0) AS inserted
        """, payload)
        result = cursor.fetchone()
        was_inserted = result['inserted'] if isinstance(result, dict) else result[0]
        if was_inserted:
            report.inserted += 1
        else:
            report.updated += 1
    return report
