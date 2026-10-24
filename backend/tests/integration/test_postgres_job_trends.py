"""전용 로컬 DB에서만 실행한다. 공유 DB와 public 테이블은 변경하지 않는다."""

import os
from pathlib import Path

import psycopg2
import pytest

from app.core.db_connect import db_cursor
from app.repositories.job_trends_repository import seed_catalog
from app.services.job_trends_service import load_response
from app.services import job_trends_service as service
from database.scripts.generate_job_trends_mock import generate, QUARTERS

pytestmark = pytest.mark.skipif(
    os.getenv('RUN_POSTGRES_INTEGRATION') != '1'
    or os.getenv('DB_HOST') not in {'127.0.0.1', 'localhost', '::1'}
    or not os.getenv('DB_NAME', '').startswith('job_insights_test'),
    reason='전용 로컬 PostgreSQL 테스트 DB가 필요합니다.',
)


def test_postgres_migration_seed_load_and_constraints(monkeypatch):
    root = Path(__file__).resolve().parents[3]
    with db_cursor(commit=True) as cursor:
        for _ in range(2):
            cursor.execute((root / 'database/sql/004_job_insights.sql').read_text(encoding='utf-8'))
            seed_catalog(cursor)
        cursor.execute("SELECT COUNT(*) AS n FROM job_insights.postings")
        assert cursor.fetchone()['n'] == 0, '처음 생성한 빈 전용 DB에서 실행하세요.'
    assert load_response(generate(sample=True), 'mock').success == 5
    assert load_response(generate(), 'mock').success == 467
    repeat = load_response(generate(), 'mock')
    assert repeat.success == repeat.duplicate == 467
    with db_cursor() as cursor:
        for table, expected in [('fields', 8), ('roles', 30), ('postings', 467)]:
            cursor.execute(f'SELECT COUNT(*) AS n FROM job_insights.{table}')
            assert cursor.fetchone()['n'] == expected
        cursor.execute('''
            SELECT f.field_code, r.role_code, r.role_name
            FROM job_insights.roles AS r JOIN job_insights.fields AS f USING (field_id)
            ''')
        from app.services.job_trends_catalog import ROLES
        assert {tuple(row.values()) for row in cursor.fetchall()} == set(ROLES)
        cursor.execute("""
            SELECT to_char(posted_at AT TIME ZONE 'Asia/Seoul', 'YYYY-"Q"Q') AS quarter, COUNT(*) AS n
            FROM job_insights.postings WHERE source = 'mock' GROUP BY 1
            """)
        assert {row['quarter']: row['n'] for row in cursor.fetchall()} == QUARTERS
        cursor.execute("SELECT COUNT(*) AS n FROM job_insights.postings WHERE raw_payload->>'id' = source_job_id")
        assert cursor.fetchone()['n'] == 467
        cursor.execute("""
            SELECT p.posting_id FROM job_insights.postings AS p
            JOIN job_insights.posting_roles AS r USING (posting_id)
            GROUP BY p.posting_id HAVING COUNT(*) > 1 LIMIT 1
            """)
        posting_id = cursor.fetchone()['posting_id']
    with pytest.raises(psycopg2.IntegrityError):
        with db_cursor(commit=True) as cursor:
            cursor.execute('UPDATE job_insights.posting_roles SET is_primary = TRUE WHERE posting_id = %s', (posting_id,))
    with pytest.raises(psycopg2.IntegrityError):
        with db_cursor(commit=True) as cursor:
            cursor.execute("INSERT INTO job_insights.posting_roles (posting_id, role_id) VALUES (-1, -1)")
    # 원본 갱신·관계 갱신 후 실패해도 공고와 관계가 함께 롤백되어야 한다.
    payload = generate(sample=True)
    original = payload['jobs']['job'][0]['position']['title']
    payload['jobs']['job'][0]['position']['title'] = 'rollback marker'
    save = service.repository.save_postings
    def fail_after_save(cursor, rows):
        save(cursor, rows)
        raise RuntimeError('intentional isolated rollback')
    with monkeypatch.context() as patch:
        patch.setattr(service.repository, 'save_postings', fail_after_save)
        with pytest.raises(service.JobTrendsLoadError):
            load_response(payload, 'mock')
    with db_cursor() as cursor:
        cursor.execute("SELECT title FROM job_insights.postings WHERE source='mock' AND source_job_id='90000000'")
        assert cursor.fetchone()['title'] == original
    # 출처 분리용 가상 saramin 공고는 트랜잭션 안에서만 확인하고 롤백한다.
    rows, _ = service.parse_response(generate(sample=True), "saramin")
    with db_cursor() as cursor:
        assert save(cursor, rows) == (5, 0)
        cursor.execute("SELECT source, COUNT(*) AS n FROM job_insights.postings GROUP BY source")
        assert {row["source"]: row["n"] for row in cursor.fetchall()} == {"mock": 467, "saramin": 5}
    with db_cursor() as cursor:
        cursor.execute('SELECT source, COUNT(*) AS n FROM job_insights.postings GROUP BY source')
        assert {row['source']: row['n'] for row in cursor.fetchall()} == {'mock': 467}
