"""Sequential bounded public HTML requests; access restrictions always stop the run."""
from __future__ import annotations
from collections import Counter, OrderedDict
from collections.abc import Mapping
from datetime import datetime, timezone
import logging
import re
import time
import math
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urljoin
from urllib.robotparser import RobotFileParser
import requests
from requests.adapters import HTTPAdapter
from .parser import BASE, listing_page, detail_page
from .page_check import (NORMAL_PAGE, CHALLENGE_PAGE, UNKNOWN_PAGE, classify_page, page_kind,
    redact_html)
from .http_headers import (USER_AGENT, HTML_ACCEPT, ACCEPT_LANGUAGE, masked_headers,
    redact_text, validate_contact)

LOG = logging.getLogger(__name__)


class CollectionStopped(RuntimeError):
    def __init__(self, reason, retry_after=None):
        super().__init__(reason)
        self.retry_after = retry_after


def allowed_url(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.netloc != 'itchaeyong.com' or parsed.fragment:
        return False
    if parsed.path == '/robots.txt':
        return not parsed.query
    if parsed.path == '/jobs/dev':
        query = parse_qs(parsed.query, keep_blank_values=True)
        return not parsed.query or (set(query) == {'page'} and len(query['page']) == 1
            and query['page'][0].isascii() and query['page'][0].isdigit() and int(query['page'][0]) > 0)
    return bool(re.fullmatch(r'/jobs/[A-Za-z0-9_-]+', parsed.path)) and not parsed.query


class ItchaeyongCrawler:
    def __init__(self, user_agent=USER_AGENT, delay=4, timeout=10, session=None, debug_dir=None, contact_email=None):
        if not user_agent.strip() or not math.isfinite(delay) or not 4 <= delay <= 60 or timeout != 10:
            raise ValueError('봇 식별자, 요청 간격 4~60초, 타임아웃 10초 필요')
        self.session = session or requests.Session()
        self.session.headers.update({'User-Agent': user_agent, 'Accept': HTML_ACCEPT, 'Accept-Language': ACCEPT_LANGUAGE})
        if contact_email is not None:
            self.session.headers['From'] = validate_contact(contact_email)
        if isinstance(self.session, requests.Session):
            self.session.mount('https://', HTTPAdapter(max_retries=0))
            self.session.mount('http://', HTTPAdapter(max_retries=0))
        self.delay, self.timeout = delay, timeout
        self.last_request = None
        self.request_count = 0
        self.max_requests = 650
        self.robots = None
        self.report = {}
        # Diagnostic copies of response bodies (redacted); None keeps bodies in memory only.
        self.debug_dir = Path(debug_dir) if debug_dir else None
        self.last_page = None
        self._cache = OrderedDict()
        self._cache_bytes = 0
        self._stopped_reason = None

    def prepare_request(self, url):
        """Prepare only; requests adds transport-managed headers when sending."""
        if not allowed_url(url):
            raise CollectionStopped('허용된 공개 /jobs/ HTML 경로가 아닙니다')
        headers = {'Accept': 'text/plain'} if url == BASE + '/robots.txt' else None
        return self.session.prepare_request(requests.Request('GET', url, headers=headers))

    def _cache_context(self, url, headers):
        if isinstance(self.session, requests.Session):
            prepared = self.prepare_request(url).headers
        else:
            prepared = {**self.session.headers, **headers}
        private = any(re.search(r'authorization|cookie|token|secret|api[-_]?key|password', k, re.I) for k in prepared)
        return (url, tuple(sorted((k.lower(), str(v)) for k, v in prepared.items()))), private

    def _discard_cached(self, key):
        previous = self._cache.pop(key, None)
        if previous:
            self._cache_bytes -= previous['bytes']

    def _store_cached(self, key, text, headers, content_type, private):
        self._discard_cached(key)
        control = headers.get('Cache-Control', '').lower()
        if private or headers.get('Set-Cookie') or any(v in control for v in ('no-store', 'private')) or headers.get('Vary') == '*':
            return
        if not headers.get('ETag') and not headers.get('Last-Modified'):
            return
        size = len(text.encode('utf-8'))
        if size > 8 * 1024 * 1024:
            return
        while self._cache and (len(self._cache) >= 16 or self._cache_bytes + size > 8 * 1024 * 1024):
            self._discard_cached(next(iter(self._cache)))
        self._cache[key] = dict(text=text, content_type=content_type, bytes=size,
            etag=headers.get('ETag'), last_modified=headers.get('Last-Modified'))
        self._cache_bytes += size

    def request(self, url):
        if not allowed_url(url):
            raise CollectionStopped('허용된 공개 /jobs/ HTML 경로가 아닙니다')
        if self._stopped_reason:
            raise CollectionStopped(self._stopped_reason)
        if self.request_count >= self.max_requests:
            raise CollectionStopped('max_requests')
        if self.last_request is not None:
            time.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
        self.request_count += 1
        requested_at = datetime.now(timezone.utc).isoformat()
        # robots.txt is plain text. Keep the honest bot User-Agent and HTML defaults
        # unchanged; scope content negotiation to this request only.
        headers = {'Accept': 'text/plain'} if url == BASE + '/robots.txt' else {}
        cache_key, private = self._cache_context(url, headers)
        cached = self._cache.get(cache_key) if not private else None
        if cached:
            if cached['etag']:
                headers['If-None-Match'] = cached['etag']
            if cached['last_modified']:
                headers['If-Modified-Since'] = cached['last_modified']
            self._cache.move_to_end(cache_key)
        began = time.monotonic()
        try:
            response = self.session.get(url, timeout=self.timeout, allow_redirects=False, headers=headers)
        finally:
            self.last_request = time.monotonic()
        text = cached['text'] if response.status_code == 304 and cached else response.text
        content_type = (cached['content_type'] if response.status_code == 304 and cached
            else response.headers.get('Content-Type', ''))
        actual_headers = getattr(getattr(response, 'request', None), 'headers', None)
        if not isinstance(actual_headers, Mapping):
            actual_headers = {**self.session.headers, **headers}
        private = private or any(re.search(r'authorization|cookie|token|secret|api[-_]?key|password', k, re.I) for k in actual_headers)
        trace = dict(url=url, requested_at=requested_at,
            responded_at=datetime.now(timezone.utc).isoformat(), status=response.status_code,
            response_date=response.headers.get('Date'), content_type=response.headers.get('Content-Type'),
            effective_content_type=content_type, elapsed_seconds=round(time.monotonic() - began, 3),
            accept=actual_headers.get('Accept'), request_headers=masked_headers(actual_headers),
            cache_reused=response.status_code == 304 and cached is not None,
            redirect_response=300 <= response.status_code < 400 and response.status_code != 304,
            redirects_followed=False)
        # DOM-based verdict; a substring anywhere in the document (e.g. a comment) is not proof of a challenge.
        check = classify_page(text, page_kind(url))
        trace.update(page_verdict=check['verdict'], page_reason=check['reason'], html_title=check['title'],
            body_bytes=check['body_bytes'], job_link_count=check['job_link_count'],
            challenge_evidence=check['challenge_evidence'], passive_evidence=check['passive_evidence'],
            challenge_html=check['verdict'] == CHALLENGE_PAGE)
        if self.debug_dir:
            trace['debug_html_path'] = str(self.save_debug(url, response, text=text))
        trace['html_title'] = redact_text(trace['html_title']) if trace['html_title'] else None
        trace['challenge_evidence'] = [redact_text(v) for v in trace['challenge_evidence']]
        self.last_page = trace
        self.report.setdefault('http_responses', []).append(trace)
        LOG.info('HTTP GET %s status=%s requested_at=%s response_date=%s accept=%s verdict=%s',
            url, trace['status'], requested_at, trace['response_date'], trace['accept'], trace['page_verdict'])
        effective_url = getattr(response, 'url', url)
        if isinstance(effective_url, str) and not allowed_url(effective_url):
            raise CollectionStopped('응답 URL이 허용된 공개 경로를 벗어났습니다')
        if trace['redirect_response']:
            location = urljoin(url, response.headers.get('Location', ''))
            trace['redirect_target_allowed'] = bool(response.headers.get('Location')) and allowed_url(location)
            raise CollectionStopped('리다이렉트 중단: ' + ('자동 이동하지 않음' if trace['redirect_target_allowed'] else '허용되지 않은 대상'),
                response.headers.get('Retry-After'))
        if response.status_code not in (200, 304):
            # Do not retry a 429. Preserve Retry-After so a human can respect the cooldown.
            if response.status_code in (401, 403, 429):
                self._stopped_reason = f'HTTP {response.status_code}'
            raise CollectionStopped(f'HTTP {response.status_code}', response.headers.get('Retry-After'))
        if response.status_code == 304 and not cached:
            raise CollectionStopped('HTTP 304: 재사용할 캐시 본문 없음')
        if response.status_code == 304 and private:
            raise CollectionStopped('HTTP 304: 인증/쿠키 요청의 캐시는 재사용하지 않습니다')
        if trace['challenge_html']:
            self._stopped_reason = '접근 제한 challenge HTML'
            raise CollectionStopped('접근 제한 challenge HTML (CHALLENGE_PAGE: '
                + ', '.join(trace['challenge_evidence']) + ')')
        mime = content_type.partition(';')[0].strip().lower()
        if url == BASE + '/robots.txt' and mime != 'text/plain':
            raise CollectionStopped('robots.txt Content-Type은 text/plain이어야 합니다')
        if url != BASE + '/robots.txt' and mime not in ('text/html', 'application/xhtml+xml'):
            raise CollectionStopped('HTML 이외 응답')
        usable = check['verdict'] == NORMAL_PAGE or (url == BASE + '/robots.txt'
            and re.search(r'^\s*user-agent\s*:', text, re.I | re.M) and '<html' not in text.lower())
        if usable:
            if response.status_code == 200:
                self._store_cached(cache_key, text, response.headers, content_type, private)
            elif private or response.headers.get('Set-Cookie') or any(v in response.headers.get('Cache-Control', '').lower() for v in ('no-store', 'private')):
                self._discard_cached(cache_key)
        return text

    def save_debug(self, url, response, text=None):
        """Redacted body only: response headers/cookies are never written."""
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        name = re.sub(r'[^A-Za-z0-9_-]+', '_', urlparse(url).path.strip('/') + '_' + urlparse(url).query).strip('_')
        path = self.debug_dir / f'{self.request_count:03d}_{name or "root"}_{response.status_code}.html'
        with path.open('x', encoding='utf-8') as stream:
            stream.write(redact_text(redact_html(response.text if text is None else text)))
        return path

    def load_robots(self):
        text = self.request(BASE + '/robots.txt')
        if not re.search(r'^\s*user-agent\s*:', text, re.I | re.M) or '<html' in text.lower():
            raise CollectionStopped('robots.txt 확인 불가')
        robots = RobotFileParser()
        robots.parse(text.splitlines())
        self.robots = robots
        agent = self.session.headers['User-Agent']
        self.delay = max(self.delay, robots.crawl_delay(agent) or 0)
        rate = robots.request_rate(agent)
        if rate and rate.requests:
            self.delay = max(self.delay, rate.seconds / rate.requests)

    def get(self, url):
        if not allowed_url(url) or url == BASE + '/robots.txt':
            raise CollectionStopped('공개 채용 HTML URL만 허용')
        if not self.robots or not self.robots.can_fetch(self.session.headers['User-Agent'], url):
            raise CollectionStopped('robots.txt 수집 불허')
        return self.request(url)

    def crawl(self, target_count=500, max_pages=50, max_requests=650, details=True,
              initial_jobs=(), checkpoint=None):
        if not 1 <= target_count <= 500 or not 1 <= max_pages <= 1000 or max_requests < 1:
            raise ValueError('목표 1~500, 페이지 1~1000, 요청 상한 1 이상 필요')
        jobs = {row['source_job_id']: dict(row) for row in initial_jobs}
        if len(jobs) > target_count or any(row['source'] != 'itchaeyong' for row in jobs.values()):
            raise ValueError('재시작 CSV 출처/목표 초과 오류')
        self.request_count, self.max_requests, self.robots = 0, max_requests, None
        started = time.monotonic()
        report = self.report = dict(source='itchaeyong', target_count=target_count,
            unique_count=len(jobs), resumed_count=len(jobs), collected_count=0,
            duplicate_count=0, invalid_count=0, failed_count=0, pages=[], errors=[],
            status='running', started_at=datetime.now(timezone.utc).isoformat(), stop_reason=None, http_responses=[],
            trend_basis='collection_snapshot', retry_after=None)
        fingerprints = set()
        page, stage = 1, 'initialization'
        def save():
            report['unique_count'] = len(jobs)
            report['request_count'] = self.request_count
            if checkpoint:
                checkpoint(jobs.values(), report)
        try:
            save()
            if len(jobs) < target_count:
                stage = 'robots'
                self.load_robots()
            while len(jobs) < target_count and page <= max_pages:
                stage = 'listing'
                url = BASE + '/jobs/dev' + (f'?page={page}' if page > 1 else '')
                rows, next_page, stats, loading = listing_page(self.get(url), page)
                checked = self.last_page if self.last_page and self.last_page['url'] == url else None
                stats.update(page=page, added_count=0, unique_count=len(jobs), parser_executed=True,
                    page_verdict=checked['page_verdict'] if checked else None)
                report['pages'].append(stats)
                report['collected_count'] += stats['candidate_count']
                report['invalid_count'] += stats['invalid_count']
                report['duplicate_count'] += stats['duplicate_count']
                if not rows and checked and checked['page_verdict'] == NORMAL_PAGE:
                    raise CollectionStopped(f"파서 불일치: 공고 링크 {checked['job_link_count']}개, 추출 0건")
                if not rows and checked and checked['page_verdict'] == UNKNOWN_PAGE:
                    raise CollectionStopped('UNKNOWN_PAGE: ' + checked['page_reason'])
                if loading:
                    raise CollectionStopped('HTML loading shell: 공개 목록 구조 확인 필요')
                if not rows:
                    report['stop_reason'] = 'empty_page'
                    break
                fingerprint = frozenset(row['source_job_id'] for row in rows)
                if fingerprint in fingerprints:
                    report['duplicate_count'] += len(rows)
                    report['stop_reason'] = 'repeated_page'
                    break
                fingerprints.add(fingerprint)
                for row in rows:
                    identifier = row['source_job_id']
                    if identifier in jobs:
                        report['duplicate_count'] += 1
                        continue
                    jobs[identifier] = row
                    stats['added_count'] += 1
                    # Persist the list item before attempting its optional detail request.
                    save()
                    if details:
                        stage = f'detail:{identifier}'
                        row['detail_status'] = 'unavailable'
                        detail_html = self.get(row['job_url'])
                        checked = self.last_page if self.last_page and self.last_page['url'] == row['job_url'] else None
                        if checked and checked['page_verdict'] != NORMAL_PAGE:
                            # Keep the verified listing row; never merge metadata from an unverified page.
                            row['detail_status'] = 'unverified_page'
                            save()
                            if len(jobs) >= target_count:
                                break
                            continue
                        detail = detail_page(detail_html)
                        for key, value in detail.items():
                            if isinstance(value, list):
                                row[key] = list(dict.fromkeys(row[key] + value))
                            elif value is not None:
                                row[key] = value
                        row['detail_status'] = 'parsed' if any(detail.values()) else 'no_metadata'
                        save()
                    if len(jobs) >= target_count:
                        break
                stats['unique_count'] = len(jobs)
                LOG.info('페이지 %s 후보=%s 추가=%s 누적고유=%s', page,
                    stats['candidate_count'], stats['added_count'], len(jobs))
                if next_page is None:
                    report['stop_reason'] = 'last_page'
                    break
                page = next_page
            if len(jobs) >= target_count:
                report['stop_reason'] = 'target_reached'
            elif report['stop_reason'] is None:
                report['stop_reason'] = 'max_pages'
            report['status'] = 'completed' if len(jobs) >= target_count else 'partial'
        except (requests.RequestException, CollectionStopped, KeyboardInterrupt) as exc:
            # Do not include URLs/credentials from arbitrary network exceptions in logs/reports.
            reason = str(exc) if isinstance(exc, CollectionStopped) else type(exc).__name__
            report.update(status='stopped', stop_reason=reason, failed_count=1,
                retry_after=getattr(exc, 'retry_after', None))
            report['errors'].append(dict(page=page, stage=stage, reason=reason))
            LOG.error('수집 중단 page=%s stage=%s reason=%s', page, stage, reason)
        finally:
            report.update(unique_count=len(jobs), target_reached=len(jobs) >= target_count,
                achieved_500=len(jobs) == 500, request_count=self.request_count,
                finished_at=datetime.now(timezone.utc).isoformat(),
                duration_seconds=round(time.monotonic() - started, 3))
            for key, name in (('job_role', 'job_role_distribution'), ('tech_stack', 'tech_stack_distribution')):
                report[name] = dict(Counter(v for row in jobs.values() for v in set(row[key])))
            report['company_distribution'] = dict(Counter(row['company_name'] for row in jobs.values() if row['company_name']))
            report['missing_rates'] = {key: sum(not row.get(key) for row in jobs.values()) / max(len(jobs), 1)
                for key in ('source', 'source_job_id', 'job_title', 'job_url', 'original_url', 'company_name',
                            'job_category', 'job_role', 'experience', 'employment_type', 'location',
                            'tech_stack', 'requirements', 'preferred_qualifications', 'posted_at',
                            'deadline_at', 'collected_at', 'detail_status')}
            save()
        return list(jobs.values())
