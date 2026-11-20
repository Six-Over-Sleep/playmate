"""Explicit, separate additive migration. Do not run against production without approval."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    sys.path.insert(0, str(ROOT / 'backend'))
    from app.core.db_connect import db_cursor
    sql = (ROOT / 'database/sql/037_itchaeyong_job_postings.sql').read_text(encoding='utf-8')
    with db_cursor(commit=True) as cursor:
        cursor.execute(sql)
    print('IT 채용 레이더 테이블/인덱스 준비 완료')


if __name__ == '__main__':
    main()
