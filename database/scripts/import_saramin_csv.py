"""Validate locally by default. Only --apply opens a database connection."""
import argparse
import sys
from pathlib import Path
from saramin_csv import read_csv
from import_saramin_jobs import dedupe_jobs, import_jobs

ROOT = Path(__file__).resolve().parents[2]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--preview-db', action='store_true', help='읽기 전용 DB 조회로 예상 신규/갱신 건수 확인')
    args = parser.parse_args(argv)
    jobs, skipped = dedupe_jobs(read_csv(args.csv))
    print(f'유효 고유 {len(jobs)}건 / 제외 {skipped}건')
    if not args.apply and not args.preview_db:
        print('DB 연결/변경 없음. 예상 신규/갱신: DB 미조회로 미확정. --preview-db로 읽기 전용 확인 가능.')
        return 0
    sys.path.insert(0, str(ROOT / 'backend'))
    from app.core.db_connect import db_cursor
    with db_cursor(commit=args.apply) as cursor:
        if not args.apply:
            cursor.execute('SET TRANSACTION READ ONLY')
            updated = 0
            for job in jobs:
                cursor.execute('SELECT 1 FROM saramin_job_postings WHERE source=%s AND source_id=%s',
                               (job['source'], job['source_id']))
                updated += cursor.fetchone() is not None
            print(f'예상 신규 {len(jobs) - updated}건 / 갱신 {updated}건 (DB 변경 없음)')
        else:
            result = import_jobs(cursor, jobs)
            for job in jobs:
                cursor.execute('SELECT 1 FROM saramin_job_postings WHERE source=%s AND source_id=%s',
                               (job['source'], job['source_id']))
                if cursor.fetchone() is None:
                    raise RuntimeError('적재 결과 검증 실패: 전체 롤백')
            print(f'신규 {result.inserted}건 / 갱신 {result.updated}건 / 제외 {result.skipped}건')
    return 0


if __name__ == '__main__':
    sys.exit(main())
