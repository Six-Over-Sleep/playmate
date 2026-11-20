"""Local public HTML → CSV. Database import is always a separate command."""
import argparse
from datetime import datetime, timezone
import hashlib
import logging
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'crawler'))
from itchaeyong_crawler.crawler import ItchaeyongCrawler
from itchaeyong_crawler.http_headers import USER_AGENT, validate_contact
from itchaeyong_csv import read_csv, write_csv, dedupe_jobs
from saramin_csv import reserve_path, write_report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-count', type=int, default=500)
    parser.add_argument('--max-pages', type=int, default=50)
    parser.add_argument('--max-requests', type=int, default=650)
    parser.add_argument('--delay', type=float, default=4)
    parser.add_argument('--list-only', action='store_true', help='상세 HTML 수집 생략')
    parser.add_argument('--permission-confirmed', action='store_true', help='목록/상세 자동수집·CSV 보관·DB 재사용 허용 범위 확인')
    parser.add_argument('--user-agent', default=os.getenv('ITCHAEYONG_USER_AGENT', USER_AGENT))
    parser.add_argument('--resume', nargs='?', const='latest', help='이전 CSV 경로. 생략 시 기본 폴더 최신 CSV')
    parser.add_argument('--csv', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--debug-html', action='store_true',
        help='응답 본문(민감값 마스킹)을 data/itchaeyong/debug/<run_id>/ 에 저장. Git 제외 경로')
    args = parser.parse_args(argv)
    if not args.permission_confirmed or not args.user_agent or not args.user_agent.strip():
        parser.error('수집·보관·재사용 권한 확인 및 유효한 봇 식별자 필요')
    if not 1 <= args.target_count <= 500 or not 1 <= args.max_pages <= 1000 or args.max_requests < 1 or not 4 <= args.delay <= 60:
        parser.error('target-count=1~500, max-pages=1~1000, max-requests>=1, delay=4~60 필요')
    try:
        contact_email = validate_contact(os.getenv('ITCHAEYONG_CONTACT_EMAIL'))
    except ValueError as exc:
        parser.error(str(exc))
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid4().hex[:8]
    csv_path = (args.csv or ROOT / 'data/itchaeyong/exports' / f'itchaeyong_jobs_{run_id}.csv').resolve()
    report_path = (args.report or ROOT / 'data/itchaeyong/reports' / f'collection_report_{run_id}.json').resolve()
    if csv_path == report_path or csv_path.exists() or report_path.exists():
        parser.error('출력 경로 중복 또는 기존 파일: 덮어쓰기 금지')
    resume_path, initial, skipped = None, [], 0
    if args.resume:
        if args.resume == 'latest':
            files = list((ROOT / 'data/itchaeyong/exports').glob('itchaeyong_jobs_*.csv'))
            if not files:
                parser.error('재시작할 CSV 없음. --resume 경로를 직접 지정하세요')
            resume_path = max(files, key=lambda p: p.stat().st_mtime)
        else:
            resume_path = Path(args.resume).resolve()
        initial, skipped = dedupe_jobs(read_csv(resume_path))
        if len(initial) > args.target_count:
            parser.error('이전 CSV 고유 행 수가 목표를 초과합니다')
        print(f'재시작: {resume_path} / 기존 고유 {len(initial)}건 / 파일 내 중복 {skipped}건')
    reserve_path(csv_path)
    reserve_path(report_path)
    debug_dir = ROOT / 'data/itchaeyong/debug' / run_id if args.debug_html else None
    crawler = ItchaeyongCrawler(user_agent=args.user_agent, delay=args.delay, debug_dir=debug_dir,
        contact_email=contact_email)
    def checkpoint(rows, report):
        write_csv(csv_path, rows)
        write_report(report_path, {**report, 'run_id': run_id, 'csv_path': str(csv_path),
            'resumed_from': str(resume_path) if resume_path else None, 'resume_duplicates': skipped})
    jobs = crawler.crawl(target_count=args.target_count, max_pages=args.max_pages,
        max_requests=args.max_requests, details=not args.list_only, initial_jobs=initial, checkpoint=checkpoint)
    verified, duplicates = dedupe_jobs(read_csv(csv_path))
    if len(verified) != len(jobs) or duplicates or len(verified) > args.target_count:
        raise RuntimeError('CSV 재로딩 행 수/고유키 검증 실패')
    if not verified:
        # A header-only file is a diagnostic artefact, not a collection result: rename it so that
        # --resume latest and the DB import never mistake it for collected data.
        empty_path = csv_path.with_name(csv_path.name.replace('itchaeyong_jobs_', 'itchaeyong_EMPTY_', 1))
        csv_path = csv_path.replace(empty_path)
    with csv_path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    report = {**crawler.report, 'run_id': run_id, 'csv_path': str(csv_path),
        'csv_kind': 'collected' if verified else 'empty_diagnostic',
        'csv_sha256': digest, 'csv_rows': len(verified), 'csv_bytes': csv_path.stat().st_size,
        'resumed_from': str(resume_path) if resume_path else None, 'resume_duplicates': skipped,
        'debug_html_dir': str(debug_dir) if debug_dir else None}
    write_report(report_path, report)
    if not verified:
        print('=' * 40)
        print('IT 채용 레이더 수집 결과')
        print('수집 실패: 실제 채용공고 0건\nCSV 데이터 없음 (DB 적재 대상 아님)')
        print(f"실패 원인: {report['stop_reason']}\n상태: {report['status']} / 요청 수: {report['request_count']}")
        for trace in report.get('http_responses', [])[-2:]:
            print(f"  응답 {trace['url']} status={trace['status']} 판정={trace.get('page_verdict')}"
                f" title={trace.get('html_title')!r} 공고링크={trace.get('job_link_count')}")
        print(f'진단용 빈 CSV(정상 수집 아님):\n{csv_path}\n보고서:\n{report_path}')
        if debug_dir:
            print(f'디버그 HTML:\n{debug_dir}')
        print('=' * 40)
        return 2
    print('=' * 40)
    print('IT 채용 레이더 수집 결과')
    print(f"수집 출처: itchaeyong.com\n목표 공고: {args.target_count}건\n실제 고유 공고: {len(verified)}건")
    print(f"중복 제외: {report['duplicate_count']}건\n누락/오류: {report['invalid_count'] + report['failed_count']}건")
    print(f"상태: {report['status']} / 종료 사유: {report['stop_reason']}\n수집 완료 시각(UTC): {report['finished_at']}")
    print(f'CSV 저장 완료:\n{csv_path}\n보고서 저장 완료:\n{report_path}\nSHA256: {digest}')
    print('=' * 40)
    return 2 if report['status'] == 'stopped' else 0


if __name__ == '__main__':
    sys.exit(main())
