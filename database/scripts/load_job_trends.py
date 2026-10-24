"""격리된 로컬 PostgreSQL에만 명시적으로 마이그레이션/적재한다."""

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--isolated-local', action='store_true', required=True)
    parser.add_argument('--migrate', action='store_true')
    parser.add_argument('--input', type=Path)
    parser.add_argument('--source', choices=['mock', 'saramin'], default='mock')
    args = parser.parse_args()
    # .env의 팀 DB 설정을 기본값으로 사용하지 않도록 import 전에 검증한다.
    if (os.getenv('DB_HOST') not in {'localhost', '127.0.0.1', '::1'}
            or not os.getenv('DB_NAME', '').startswith('job_insights_test')
            or os.getenv('APP_ENV') != 'test'):
        parser.error('APP_ENV=test, 명시적인 로컬 DB_HOST, job_insights_test* DB_NAME이 필요합니다.')
    from app.core.db_connect import db_cursor, close_pool
    from app.repositories.job_trends_repository import seed_catalog
    from app.services.job_trends_service import load_response

    try:
        if args.migrate:
            with db_cursor(commit=True) as cursor:
                cursor.execute((ROOT / 'database/sql/004_job_insights.sql').read_text(encoding='utf-8'))
                seed_catalog(cursor)
        if args.input:
            report = load_response(json.loads(args.input.read_text(encoding='utf-8')), args.source)
            print(json.dumps(asdict(report), ensure_ascii=False))
    finally:
        close_pool()


if __name__ == '__main__':
    main()
