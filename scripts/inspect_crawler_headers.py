"""Prepare headers offline by default. Live GET requires both --live and --authorized."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'crawler'))
import requests
from itchaeyong_crawler.crawler import ItchaeyongCrawler, CollectionStopped, allowed_url
from itchaeyong_crawler.http_headers import USER_AGENT, masked_headers, safe_url


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--live', action='store_true')
    parser.add_argument('--authorized', action='store_true', help='사이트 접근 허용 및 진단 요청 승인 확인')
    parser.add_argument('--url', default='https://itchaeyong.com/robots.txt')
    args = parser.parse_args(argv)
    if args.live and not args.authorized:
        parser.error('실제 요청은 --live --authorized를 함께 지정해야 합니다')
    if not allowed_url(args.url):
        parser.error('itchaeyong.com의 허용된 공개 채용/robots 경로만 검사할 수 있습니다')
    try:
        crawler = ItchaeyongCrawler(user_agent=os.getenv('ITCHAEYONG_USER_AGENT', USER_AGENT),
            contact_email=os.getenv('ITCHAEYONG_CONTACT_EMAIL'))
        prepared = crawler.prepare_request(args.url)
    except (ValueError, requests.RequestException) as exc:
        parser.error(f'요청 설정 오류 ({type(exc).__name__})')
    result = dict(mode='live' if args.live else 'dry-run', url=safe_url(prepared.url),
        prepared_headers=masked_headers(prepared.headers), timeout_seconds=crawler.timeout,
        minimum_delay_seconds=crawler.delay, automatic_retries=0, follow_redirects=False,
        transport_headers_note='Host 및 일부 전송 헤더는 requests/urllib3가 송신 시 자동 관리합니다.',
        network_requests_made=0)
    if args.live:
        crawler.max_requests = 2
        try:
            crawler.load_robots()
            if args.url != 'https://itchaeyong.com/robots.txt':
                crawler.get(args.url)
            result['error'] = None
        except (CollectionStopped, requests.RequestException) as exc:
            result['error'] = str(exc) if isinstance(exc, CollectionStopped) else type(exc).__name__
        result['network_requests_made'] = crawler.request_count
        result['responses'] = crawler.report.get('http_responses', [])
    else:
        result['note'] = '네트워크 요청 없음. 실제 채용 URL 진단에서는 robots를 먼저 확인합니다.'
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result.get('error') else 0


if __name__ == '__main__':
    sys.exit(main())
