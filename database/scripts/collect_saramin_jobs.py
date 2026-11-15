"""IT개발·데이터 웹페이지 수집 → Playmate PostgreSQL (optional).

Default: preview only. --apply: upsert via backend's db_cursor.
Like collect_career_news.py, this script owns the DB integration and
the crawler remains independently testable. Requires site permission.
"""
import argparse
import importlib.util
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = Path(__file__).resolve().parent
CRAWLER_DIR = ROOT / 'crawler' / 'saramin_crawler'
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from import_saramin_jobs import dedupe_jobs, import_jobs  # noqa: E402

def load_crawler(crawler_dir: Path):
    crawler_dir = crawler_dir.resolve()
    for filename in ('crawler.py', 'parser.py', 'config.py'):
        if not (crawler_dir / filename).is_file():
            raise FileNotFoundError(f'크롤러 파일 없음: {crawler_dir / filename}')
    # Explicitly scope module resolution to this crawler, rather than another crawler's config.py.
    sys.path.insert(0, str(crawler_dir))
    from crawler import SaraminWebCrawler  # noqa: E402
    if not Path(sys.modules['crawler'].__file__).resolve().is_relative_to(crawler_dir):
        raise ImportError('다른 크롤러 모듈이 import되었습니다')
    return SaraminWebCrawler

def main(argv=None):
    parser = argparse.ArgumentParser(description='사람인 IT개발·데이터 수집 (기본: DB 미저장)')
    parser.add_argument('--crawler-dir', type=Path, default=CRAWLER_DIR)
    parser.add_argument('--max-pages', type=int, default=3)
    parser.add_argument('--delay', type=float, default=3.0)
    parser.add_argument('--details', action='store_true', help='상세페이지 별도 이용 허가가 있는 경우만')
    parser.add_argument('--apply', action='store_true', help='PostgreSQL에 UPSERT (기본은 미저장)')
    parser.add_argument('--output', type=Path, default=None, help='수집 결과 JSON 저장 경로')
    args = parser.parse_args(argv)
    if not 1 <= args.max_pages <= 50:
        parser.error('--max-pages는 1~50이어야 합니다')
    if args.delay < 1:
        parser.error('--delay는 1초 이상이어야 합니다')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    Crawler = load_crawler(args.crawler_dir)
    jobs = Crawler(delay=args.delay).crawl(max_pages=args.max_pages, details=args.details)
    unique, skipped = dedupe_jobs(jobs)
    print(f'수집 {len(jobs)}건 → 고유 공고 {len(unique)}건 (유효성 제외 {skipped}건)')
    for job in unique[:3]:
        print(f"  {job['source_id']}: {job['title']} / 직무={job['job_roles']} / 분야={job['specialties']}")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(unique, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        print(f'JSON 저장: {args.output}')
    if not args.apply:
        print('미리보기 모드: DB 변경 없음. 저장하려면 --apply 옵션을 사용하세요.')
        return 0 if unique else 2
    if not unique:
        print('저장할 유효한 공고 없음: DB 변경 없음')
        return 2
    sys.path.insert(0, str(ROOT / 'backend'))
    from app.core.db_connect import db_cursor  # noqa: E402
    with db_cursor(commit=True) as cursor:
        report = import_jobs(cursor, unique)
    print(f'DB 저장 완료: 신규 {report.inserted}건 / 갱신 {report.updated}건')
    return 0

if __name__ == '__main__':
    sys.exit(main())
