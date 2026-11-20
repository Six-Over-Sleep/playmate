"""Response HTML diagnosis. Reuses saved HTML first; a site request needs --fetch and permission flags."""
import argparse
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'crawler'))
from itchaeyong_crawler.crawler import ItchaeyongCrawler, CollectionStopped
from itchaeyong_crawler.page_check import classify_page, CHALLENGE_PAGE
from itchaeyong_crawler.parser import BASE, listing_page, detail_page
import requests
from saramin_csv import write_report

DEBUG_DIR = ROOT / 'data/itchaeyong/debug'


def diagnose(path, kind=None):
    text = Path(path).read_text(encoding='utf-8')
    name = Path(path).name
    kind = kind or ('robots' if 'robots_txt' in name else 'listing' if 'jobs_dev' in name else 'detail')
    result = dict(html_path=str(Path(path).resolve()), **classify_page(text, kind))
    result['parser_executed'] = result['verdict'] != CHALLENGE_PAGE and kind != 'robots'
    if result['parser_executed'] and kind == 'listing':
        rows, next_page, stats, loading = listing_page(text)
        result.update(parsed_count=len(rows), next_page=next_page, parser_stats=stats, loading_shell=loading,
            sample=[{key: row[key] for key in ('source_job_id', 'job_title', 'company_name', 'job_role',
                'experience', 'location', 'employment_type', 'tech_stack')} for row in rows[:5]])
    elif result['parser_executed'] and kind == 'detail':
        detail = detail_page(text)
        result['parsed_fields'] = sorted(key for key, value in detail.items() if value)
    return result


def latest_saved():
    files = sorted(DEBUG_DIR.rglob('*.html'), key=lambda p: p.stat().st_mtime) if DEBUG_DIR.exists() else []
    listings = [p for p in files if 'jobs_dev' in p.name]
    return (listings or files or [None])[-1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--html', type=Path, help='분석할 저장 HTML. 생략 시 debug 폴더 최신 파일 재사용')
    parser.add_argument('--kind', choices=('robots', 'listing', 'detail'))
    parser.add_argument('--fetch', action='store_true', help='robots.txt + /jobs/dev 1회(최대 2요청) 실제 요청')
    parser.add_argument('--permission-confirmed', action='store_true')
    parser.add_argument('--user-agent')
    args = parser.parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    fetch_report = None
    if args.fetch:
        if not args.permission_confirmed or not args.user_agent or not args.user_agent.strip():
            parser.error('--fetch 는 --permission-confirmed 와 실제 봇 식별 --user-agent 필요')
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
        crawler = ItchaeyongCrawler(user_agent=args.user_agent, debug_dir=DEBUG_DIR / f'diag_{stamp}')
        crawler.max_requests = 2
        try:
            crawler.load_robots()
            crawler.get(BASE + '/jobs/dev')
            stop = None
        except (requests.RequestException, CollectionStopped) as exc:
            stop = str(exc) if isinstance(exc, CollectionStopped) else type(exc).__name__
        fetch_report = dict(stop_reason=stop, request_count=crawler.request_count,
            http_responses=crawler.report.get('http_responses', []))
        saved = [Path(t['debug_html_path']) for t in fetch_report['http_responses'] if t.get('debug_html_path')]
        path = ([p for p in saved if 'jobs_dev' in p.name] or saved or [None])[-1]
    else:
        path = args.html or latest_saved()
        if path is None:
            print('저장된 디버그 HTML 없음. 실제 요청 없이 종료합니다.')
            print('권한 확인 후: --fetch --permission-confirmed --user-agent "<봇 식별자>"')
            return 1
    result = dict(analyzed_at=datetime.now(timezone.utc).isoformat(), network_requests_made=
        fetch_report['request_count'] if fetch_report else 0, fetch=fetch_report,
        page=diagnose(path, args.kind) if path else None)
    report_path = ROOT / 'data/itchaeyong/reports' / f'html_diagnosis_{stamp}.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    write_report(report_path, result)
    page = result['page'] or {}
    print('=' * 40)
    print('IT 채용 레이더 응답 HTML 진단')
    for trace in (fetch_report or {}).get('http_responses', []):
        print(f"GET {trace['url']} status={trace['status']} type={trace['content_type']} "
            f"bytes={trace['body_bytes']} verdict={trace['page_verdict']}")
    if fetch_report and fetch_report['stop_reason']:
        print(f"요청 중단 사유: {fetch_report['stop_reason']}")
    for key in ('html_path', 'kind', 'title', 'body_bytes', 'job_link_count', 'job_heading_count',
                'has_jobposting_jsonld', 'challenge_evidence', 'passive_evidence', 'verdict', 'reason',
                'parser_executed', 'parsed_count', 'next_page', 'parsed_fields'):
        if key in page:
            print(f'{key}: {page[key]}')
    for row in page.get('sample', []):
        print(f"  - {row['source_job_id']} | {row['job_title']} | {row['company_name']} | {row['job_role']}"
            f" | {row['experience']} | {row['location']} | {row['tech_stack']}")
    print(f'보고서: {report_path}')
    print('=' * 40)
    return 0 if page.get('verdict') == 'NORMAL_PAGE' else 2


if __name__ == '__main__':
    sys.exit(main())
