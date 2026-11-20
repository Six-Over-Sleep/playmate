"""Career insight preview and future database endpoints."""
import logging
import os

from fastapi import APIRouter, HTTPException, Query
import psycopg
from psycopg.rows import dict_row

from backend.app.services.career_insight_stats import load_preview, options, summarize, validate_rows

router = APIRouter(prefix='/api/career/insights', tags=['career-insights'])
logger = logging.getLogger(__name__)


def connect():
    url = os.getenv('DATABASE_URL') or os.getenv('POSTGRES_DSN')
    if url:
        return psycopg.connect(url, row_factory=dict_row)
    args = {'host': os.getenv('DB_HOST'), 'dbname': os.getenv('DB_NAME'),
            'user': os.getenv('DB_USER'), 'password': os.getenv('DB_PASSWORD'),
            'port': os.getenv('DB_PORT', '5432')}
    if not all(args.values()):
        raise RuntimeError('Database connection is not configured')
    return psycopg.connect(**args, row_factory=dict_row)


def load_rows(source='db'):
    with connect() as conn:
        with conn.cursor() as cur:
            if source == 'itchaeyong':
                cur.execute("""
                    SELECT source_job_id AS source_id, source, job_role AS job_roles,
                        ARRAY[job_category] AS specialties, tech_stack AS tech_stacks,
                        ARRAY[]::text[] AS certifications, preferred_qualifications AS preferences,
                        company_name AS company, experience AS career, location, job_category,
                        collected_at, posted_at,
                        EXTRACT(YEAR FROM collected_at AT TIME ZONE 'UTC')::int AS collection_year,
                        EXTRACT(QUARTER FROM collected_at AT TIME ZONE 'UTC')::int AS collection_quarter
                    FROM itchaeyong_job_postings
                    WHERE source = 'itchaeyong'
                """)
            else:
                cur.execute('SELECT source_id,source,job_roles,specialties,tech_stacks,certifications,preferences,collected_at,collection_year,collection_quarter FROM saramin_insight_jobs')
            return validate_rows(cur.fetchall())


def get_rows(source):
    try:
        if source == 'preview':
            return load_preview()
        selected = os.getenv('CAREER_INSIGHTS_DB_SOURCE', 'saramin') if source == 'db' else source
        if selected not in ('saramin', 'itchaeyong'):
            raise ValueError('지원하지 않는 DB 데이터 출처')
        return load_rows('itchaeyong') if selected == 'itchaeyong' else load_rows()
    except (OSError, ValueError, psycopg.Error, RuntimeError) as exc:
        logger.error('Career insight %s data unavailable (%s)', source, type(exc).__name__)
        raise HTTPException(503, '채용 인사이트 데이터를 불러올 수 없습니다.') from exc


@router.get('/{source}/filters')
def filters(source: str):
    if source not in ('preview', 'db', 'itchaeyong'):
        raise HTTPException(404, '지원하지 않는 데이터 원본입니다.')
    return options(get_rows(source))


@router.get('/{source}/summary')
def summary(source: str, quarter: str | None = Query(default=None, pattern=r'^\d{4}-Q[1-4]$'),
            field: str | None = None, skill: str | None = None):
    if source not in ('preview', 'db', 'itchaeyong'):
        raise HTTPException(404, '지원하지 않는 데이터 원본입니다.')
    return summarize(get_rows(source), quarter, field, skill, source)


@router.get('/filters')
def legacy_filters():
    return options(get_rows('db'))


@router.get('/summary')
def legacy_summary(quarter: str | None = Query(default=None, pattern=r'^\d{4}-Q[1-4]$'),
                   field: str | None = None, skill: str | None = None):
    return summarize(get_rows('db'), quarter, field, skill, 'db')
