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


def load_rows():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT source_id,source,job_roles,specialties,tech_stacks,certifications,preferences,collected_at,collection_year,collection_quarter FROM saramin_insight_jobs')
            return validate_rows(cur.fetchall())


def get_rows(source):
    try:
        return load_preview() if source == 'preview' else load_rows()
    except (OSError, ValueError, psycopg.Error, RuntimeError) as exc:
        logger.exception('Career insight %s data unavailable', source)
        raise HTTPException(503, '채용 인사이트 데이터를 불러올 수 없습니다.') from exc


@router.get('/{source}/filters')
def filters(source: str):
    if source not in ('preview', 'db'):
        raise HTTPException(404, '지원하지 않는 데이터 원본입니다.')
    return options(get_rows(source))


@router.get('/{source}/summary')
def summary(source: str, quarter: str | None = Query(default=None, pattern=r'^\d{4}-Q[1-4]$'),
            field: str | None = None, skill: str | None = None):
    if source not in ('preview', 'db'):
        raise HTTPException(404, '지원하지 않는 데이터 원본입니다.')
    return summarize(get_rows(source), quarter, field, skill, source)


@router.get('/filters')
def legacy_filters():
    return options(get_rows('db'))


@router.get('/summary')
def legacy_summary(quarter: str | None = Query(default=None, pattern=r'^\d{4}-Q[1-4]$'),
                   field: str | None = None, skill: str | None = None):
    return summarize(get_rows('db'), quarter, field, skill, 'db')
