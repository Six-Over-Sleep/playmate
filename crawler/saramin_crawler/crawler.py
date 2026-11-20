"""사람인 공개 웹 카테고리 페이지 수집. 공식 API/access key 사용하지 않음."""
from __future__ import annotations
import logging
import time
from datetime import datetime, timezone
from collections import Counter
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup
from config import CATEGORY_URL, CATEGORY_PARAMS
from parser import parse_listing, inspect_detail


LOG = logging.getLogger(__name__)
USER_AGENT = 'CareerTrendResearchBot/1.0 (educational project; contact: configure-before-use)'

class SaraminWebCrawler:
    def __init__(self, user_agent=USER_AGENT, delay=2.5, timeout=15, check_robots=True):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent':user_agent, 'Accept':'text/html,application/xhtml+xml'})
        self.delay = max(delay, 1.0)
        self.timeout = timeout
        self.check_robots = check_robots
        self.robots = RobotFileParser()
        self.robots.set_url('https://www.saramin.co.kr/robots.txt')
        self._last_request = 0.0
        self._robots_loaded = False
        self.request_count = 0
        self.max_requests = 100
        self.report = {}

    def _allowed(self, url):
        if not self.check_robots:
            return True
        if not self._robots_loaded:
            try:
                self._reserve_request()
                res = self.session.get('https://www.saramin.co.kr/robots.txt', timeout=self.timeout, allow_redirects=False)
                self._last_request = time.monotonic()
                if res.status_code != 200:
                    raise RuntimeError('robots.txt HTTP 응답을 확인할 수 없습니다')
                res.raise_for_status()
                self.robots.parse(res.text.splitlines())
                self._robots_loaded = True
            except requests.RequestException as exc:
                raise RuntimeError('robots.txt 확인 실패: 허용 여부를 확인할 수 없어 수집을 중단합니다.') from exc
        return self.robots.can_fetch(self.session.headers['User-Agent'], url)

    def _reserve_request(self):
        if self.request_count >= self.max_requests:
            raise RuntimeError("최대 요청 수 도달")
        self.request_count += 1

    def _get(self, url, params=None):
        request = requests.Request('GET',url,params=params).prepare()
        if not self._allowed(request.url):
            raise PermissionError(f'robots.txt에서 수집을 허용하지 않는 경로: {request.url}')
        remaining = self.delay - (time.monotonic()-self._last_request)
        if remaining>0:
            time.sleep(remaining)
        try:
            self._reserve_request()
            resp = self.session.get(url, params=params, timeout=self.timeout, allow_redirects=False)
        finally:
            self._last_request = time.monotonic()
        if resp.status_code in (401,403,429):
            raise RuntimeError(f'웹사이트가 요청을 제한했습니다 (HTTP {resp.status_code}). 우회하지 않고 중단합니다.')
        if 300 <= resp.status_code < 400:
            raise RuntimeError("리디렉션 또는 접근 제한: 중단합니다")
        resp.raise_for_status()
        if requests.utils.urlparse(resp.url).hostname not in ('www.saramin.co.kr', 'saramin.co.kr'):
            raise RuntimeError('예상치 못한 외부 도메인으로 이동하여 중단합니다.')
        return resp.text

    def crawl(self, max_pages=3, details=False, target_count=500,
              max_requests=100, initial_jobs=(), checkpoint=None):
        """Bounded, restartable HTML collection; caller must verify site permission."""
        if not 1 <= target_count <= 500 or not 1 <= max_pages <= 1000 or max_requests < 1:
            raise ValueError('target_count=1~500, max_pages=1~1000, max_requests>=1 필요')
        self.max_requests = max_requests
        self.request_count = 0
        jobs = {}
        for job in initial_jobs:
            if job.get('source') != 'saramin_web' or not job.get('job_roles'):
                raise ValueError('재시작 파일에 유효하지 않은 공고가 있습니다')
            jobs[str(job['source_id'])] = job
        if len(jobs) > target_count:
            raise ValueError('재시작 파일이 목표 건수를 초과합니다')
        started = time.monotonic()
        report = self.report = dict(target_count=target_count, collected_count=0,
            duplicate_count=0, filtered_count=0, failed_count=0, pages=[],
            started_at=datetime.now(timezone.utc).isoformat(), status='running',
            resumed_count=len(jobs), stop_reason=None)
        fingerprints = set()
        try:
            if checkpoint:
                checkpoint(jobs.values())
            for page in range(1, max_pages + 1):
                if len(jobs) >= target_count:
                    report['stop_reason'] = 'target_reached'
                    break
                html = self._get(CATEGORY_URL, params={**CATEGORY_PARAMS, 'page': page})
                stats = {}
                parsed = parse_listing(html, stats=stats)
                fingerprint = frozenset(stats.pop('source_ids'))
                stats.update(page=page, added_count=0, unique_count=len(jobs))
                report['pages'].append(stats)
                report['collected_count'] += stats['candidate_count']
                report['filtered_count'] += stats['filtered_count']
                if not fingerprint:
                    report['stop_reason'] = 'empty_page'
                    break
                if fingerprint in fingerprints:
                    report['duplicate_count'] += sum(j['source_id'] in jobs for j in parsed)
                    report['stop_reason'] = 'repeated_page'
                    break
                fingerprints.add(fingerprint)
                for job in parsed:
                    if job['source_id'] in jobs:
                        report['duplicate_count'] += 1
                        continue
                    jobs[job['source_id']] = job
                    stats['added_count'] += 1
                    if details:
                        job['detail_status'] = 'unavailable'
                        detail = inspect_detail(self._get(job['url']))
                        for key in ('preferences', 'tech_stacks', 'specialties'):
                            job[key] = list(dict.fromkeys((job.get(key) or []) + detail[key]))
                        job['detail_status'] = ('parsed' if detail['preferences'] else
                            'iframe_present_unparsed' if detail['has_iframe'] else 'no_preference_section')
                        if detail['specialties']:
                            job['specialty_classification_source'] = 'detail'
                        job['tech_stack_status'] = 'detail_matched' if detail['tech_stacks'] else job['tech_stack_status']
                    if checkpoint:
                        checkpoint(jobs.values())
                    if len(jobs) >= target_count:
                        report['stop_reason'] = 'target_reached'
                        break
                stats['unique_count'] = len(jobs)
                LOG.info('페이지 %s 후보=%s 직무통과=%s 제외=%s 누적고유=%s',
                         page, stats['candidate_count'], stats['passed_count'], stats['filtered_count'], len(jobs))
                if report['stop_reason'] == 'target_reached':
                    break
            else:
                report['stop_reason'] = 'max_pages'
            report['status'] = 'completed' if len(jobs) >= target_count else 'partial'
        except (requests.RequestException, RuntimeError, PermissionError, KeyboardInterrupt) as exc:
            report.update(status='stopped', failed_count=1,
                          stop_reason=f'{type(exc).__name__}: {exc}')
            LOG.error('수집 중단: %s', report['stop_reason'])
        finally:
            report.update(unique_count=len(jobs), target_reached=len(jobs) >= target_count,
                request_count=self.request_count, finished_at=datetime.now(timezone.utc).isoformat(),
                duration_seconds=round(time.monotonic() - started, 3))
            for field, name in (('job_roles', 'job_role_distribution'), ('tech_stacks', 'tech_stack_distribution')):
                report[name] = dict(Counter(v for j in jobs.values() for v in set(j.get(field) or [])))
            report['tech_stack_success_count'] = sum(bool(j.get('tech_stacks')) for j in jobs.values())
            report['tech_stack_missing_count'] = len(jobs) - report['tech_stack_success_count']
            report['preference_success_count'] = sum(bool(j.get('preferences')) for j in jobs.values())
            report['required_missing_rates'] = {k: sum(not j.get(k) for j in jobs.values()) / max(len(jobs), 1)
                for k in ('source_id', 'title', 'url', 'job_roles', 'collected_at')}
            report['duplicate_rate'] = report['duplicate_count'] / max(report['collected_count'], 1)
            if checkpoint:
                checkpoint(jobs.values())
        return list(jobs.values())
