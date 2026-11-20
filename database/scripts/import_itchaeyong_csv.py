"""CSV validation is offline; database access requires --preview-db or --apply."""
import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
from itchaeyong_csv import FIELDS, ARRAY_FIELDS, read_csv, dedupe_jobs

ROOT = Path(__file__).resolve().parents[2]
TABLE = 'itchaeyong_job_postings'
KEY_QUERY = 'SELECT 1 FROM itchaeyong_job_postings WHERE source=%s AND source_job_id=%s'
LOCK_KEY = 740_014_037


@dataclass
class ImportReport:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0


def upsert_sql():
    # Identifiers come exclusively from this module's fixed contract, never CLI/input data.
    updates = []
    for field in FIELDS:
        if field in ('source', 'source_job_id', 'collected_at'):
            continue
        if field in ARRAY_FIELDS:
            expression = f"ARRAY(SELECT DISTINCT unnest({TABLE}.{field} || EXCLUDED.{field}))"
        elif field == 'detail_status':
            expression = f"CASE WHEN {TABLE}.detail_status = 'parsed' AND EXCLUDED.detail_status <> 'parsed' THEN {TABLE}.detail_status ELSE EXCLUDED.detail_status END"
        else:
            expression = f'COALESCE(EXCLUDED.{field}, {TABLE}.{field})'
        updates.append(f'                {field} = {expression}')
    updates.append('                last_seen_at = NOW()')
    return ('INSERT INTO itchaeyong_job_postings (' + ', '.join(FIELDS) + ')\n'
        '            VALUES (' + ', '.join(f'%({field})s' for field in FIELDS) + ')\n'
        '            ON CONFLICT (source,source_job_id) DO UPDATE SET\n' + ',\n'.join(updates) +
        '\n            RETURNING (xmax = 0) AS inserted')


def import_jobs(cursor, rows):
    jobs, skipped = dedupe_jobs(rows)
    report = ImportReport(skipped=skipped)
    if not jobs:
        return report
    cursor.execute('SELECT pg_advisory_xact_lock(%s)', (LOCK_KEY,))
    sql = upsert_sql()
    for job in jobs:
        cursor.execute(sql, job)
        result = cursor.fetchone()
        was_inserted = result['inserted'] if isinstance(result, dict) else result[0]
        if was_inserted:
            report.inserted += 1
        else:
            report.updated += 1
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--preview-db', action='store_true')
    mode.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    jobs, duplicates = dedupe_jobs(read_csv(args.csv))
    print(f'유효 고유 {len(jobs)}건 / 중복 제외 {duplicates}건')
    if not jobs:
        # A 0-row (diagnostic) CSV is never a valid collection result; refuse before any DB access.
        print('CSV 데이터 없음: 실제 채용공고 0건이므로 DB 적재/미리보기를 수행하지 않습니다')
        return 2
    if not args.apply and not args.preview_db:
        print('CSV 검증 완료. DB 연결/변경 없음. 예상 신규/갱신: --preview-db 필요')
        return 0
    sys.path.insert(0, str(ROOT / 'backend'))
    from app.core.db_connect import db_cursor
    with db_cursor(commit=args.apply) as cursor:
        if args.preview_db:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            updated = 0
            for job in jobs:
                cursor.execute(KEY_QUERY, (job['source'], job['source_job_id']))
                updated += cursor.fetchone() is not None
            print(f'예상 신규 {len(jobs) - updated}건 / 갱신 {updated}건 / 제외 {duplicates}건 (읽기 전용)')
        else:
            report = import_jobs(cursor, jobs)
            for job in jobs:
                cursor.execute(KEY_QUERY, (job['source'], job['source_job_id']))
                if cursor.fetchone() is None:
                    raise RuntimeError('적재 결과 검증 실패: 전체 롤백')
            print(f'적재 신규 {report.inserted}건 / 갱신 {report.updated}건 / 제외 {duplicates}건')
    return 0


if __name__ == '__main__':
    sys.exit(main())
