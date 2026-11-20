"""IT개발·데이터 웹페이지 수집 → Playmate PostgreSQL (optional).

Default: preview only. --apply: upsert via backend's db_cursor.
Like collect_career_news.py, this script owns the DB integration and
the crawler remains independently testable. Requires site permission.
"""
import argparse
import importlib.util
import json
import logging
import os
import hashlib
from datetime import datetime, timezone
from uuid import uuid4
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = Path(__file__).resolve().parent
CRAWLER_DIR = ROOT / 'crawler' / 'saramin_crawler'
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from import_saramin_jobs import dedupe_jobs, import_jobs  # noqa: E402
from saramin_csv import read_csv, write_csv, reserve_path, write_report

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
    parser.add_argument('--max-pages', type=int, default=int(os.getenv('SARAMIN_MAX_PAGES', '50')))
    parser.add_argument('--target-count', type=int, default=int(os.getenv('SARAMIN_TARGET_COUNT', '500')))
    parser.add_argument('--max-requests', type=int, default=int(os.getenv('SARAMIN_MAX_REQUESTS', '100')))
    parser.add_argument('--csv', type=Path, help='CSV 출력 (기존 파일 덮어쓰기 금지)')
    parser.add_argument('--report', type=Path, help='JSON 보고서 경로')
    parser.add_argument('--resume', type=Path, help='이전 CSV를 읽어 새 파일로 재시작')
    parser.add_argument('--permission-confirmed', action='store_true',
        help='목록 HTML 자동수집/저장/분석 권한을 별도로 확인한 경우에만 지정')
    parser.add_argument('--details-permission-confirmed', action='store_true')
    parser.add_argument('--user-agent', default=os.getenv('SARAMIN_USER_AGENT'),
        help='연락처를 포함한 정직한 봇 식별자')
    parser.add_argument('--delay', type=float, default=3.0)
    parser.add_argument('--details', action='store_true', help='상세페이지 별도 이용 허가가 있는 경우만')
    parser.add_argument('--apply', action='store_true', help='PostgreSQL에 UPSERT (기본은 미저장)')
    parser.add_argument('--output', type=Path, default=None, help='수집 결과 JSON 저장 경로')
    args = parser.parse_args(argv)
    if not args.permission_confirmed or not args.user_agent:
        parser.error('수집 권한 확인 및 연락처가 포함된 --user-agent 설정 필요')
    if args.details and not args.details_permission_confirmed:
        parser.error('상세 수집은 --details-permission-confirmed 필요')
    if not 1 <= args.target_count <= 500 or args.max_requests < 1:
        parser.error('target-count는 1~500, max-requests는 1 이상이어야 합니다')
    if not 1 <= args.max_pages <= 50:
        parser.error('--max-pages는 1~50이어야 합니다')
    if args.delay < 1:
        parser.error('--delay는 1초 이상이어야 합니다')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    Crawler = load_crawler(args.crawler_dir)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:8]
    csv_path = args.csv or ROOT / 'data/saramin/exports' / f'saramin_jobs_{run_id}.csv'
    report_path = args.report or ROOT / 'data/saramin/reports' / f'saramin_collection_{run_id}.json'
    paths = [p.resolve() for p in (csv_path, report_path, args.output) if p is not None]
    if len(set(paths)) != len(paths) or any(p.exists() for p in paths):
        parser.error('출력 경로는 서로 달라야 하며 기존 파일은 덮어쓰지 않습니다')
    initial = list(read_csv(args.resume)) if args.resume else []
    if len({j['source_id'] for j in initial}) > args.target_count:
        parser.error('재시작 CSV가 목표 건수를 초과합니다')
    crawler = Crawler(delay=args.delay, user_agent=args.user_agent)
    for path in paths:
        reserve_path(path)
    def checkpoint(rows):
        write_csv(csv_path, rows)
        crawler.report['unique_count'] = len(rows)
        write_report(report_path, {**crawler.report, 'run_id': run_id, 'csv_path': str(csv_path),
            'status': crawler.report.get('status', 'running')})
    jobs = crawler.crawl(max_pages=args.max_pages, details=args.details,
        target_count=args.target_count, max_requests=args.max_requests,
        initial_jobs=initial, checkpoint=checkpoint)
    reloaded, _ = dedupe_jobs(read_csv(csv_path))
    if len(reloaded) != len(jobs) or csv_path.stat().st_size == 0:
        raise RuntimeError('CSV 행 수 또는 파일 검증 실패')
    with csv_path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    crawler.report.update(run_id=run_id, csv_path=str(csv_path), csv_rows=len(reloaded),
        csv_bytes=csv_path.stat().st_size, csv_sha256=digest)
    write_report(report_path, crawler.report)
    print(f'CSV: {csv_path} / 보고서: {report_path} / 목표 달성: {crawler.report["target_reached"]}')
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
        return 0 if crawler.report['status'] != 'stopped' and unique else 2
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
