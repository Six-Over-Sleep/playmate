"""사람인 공개 웹 카테고리 페이지 수집. 공식 API/access key 사용하지 않음."""
from __future__ import annotations
import logging
import time
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup
from config import CATEGORY_URL, CATEGORY_PARAMS
from parser import parse_listing, parse_detail, match_terms
from config import SPECIALTIES, TECH_STACKS

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

    def _allowed(self, url):
        if not self.check_robots:
            return True
        if not self._robots_loaded:
            try:
                res = self.session.get('https://www.saramin.co.kr/robots.txt', timeout=self.timeout)
                res.raise_for_status()
                self.robots.parse(res.text.splitlines())
                self._robots_loaded = True
            except requests.RequestException as exc:
                raise RuntimeError('robots.txt 확인 실패: 허용 여부를 확인할 수 없어 수집을 중단합니다.') from exc
        return self.robots.can_fetch(self.session.headers['User-Agent'], url)

    def _get(self, url, params=None):
        request = requests.Request('GET',url,params=params).prepare()
        if not self._allowed(request.url):
            raise PermissionError(f'robots.txt에서 수집을 허용하지 않는 경로: {request.url}')
        remaining = self.delay - (time.monotonic()-self._last_request)
        if remaining>0:
            time.sleep(remaining)
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout, allow_redirects=True)
        finally:
            self._last_request = time.monotonic()
        if resp.status_code in (401,403,429):
            raise RuntimeError(f'웹사이트가 요청을 제한했습니다 (HTTP {resp.status_code}). 우회하지 않고 중단합니다.')
        resp.raise_for_status()
        if requests.utils.urlparse(resp.url).hostname not in ('www.saramin.co.kr', 'saramin.co.kr'):
            raise RuntimeError('예상치 못한 외부 도메인으로 이동하여 중단합니다.')
        return resp.text

    def crawl(self,max_pages=3, details=False):
        """현재 웹페이지의 page 파라미터 기반 수집. 구조가 다르면 공고가 0개로 끝날 수 있음."""
        jobs={}
        for page in range(1,max_pages+1):
            params = {**CATEGORY_PARAMS,'page':page}
            LOG.info('IT개발·데이터 페이지 %s/%s',page,max_pages)
            html=self._get(CATEGORY_URL,params=params)
            parsed=parse_listing(html)
            if not parsed:
                LOG.warning('페이지 %s에서 파싱된 공고가 없습니다. 페이지 구조/선택자를 확인하세요.',page)
                break
            for job in parsed:
                jobs[job['source_id']] = job
            LOG.info('이번 페이지 %s개, 현재 고유 %s개',len(parsed),len(jobs))
        if details:
            for job in jobs.values():
                try:
                    html=self._get(job['url'])
                    job['preferences']=parse_detail(html)
                    from bs4 import BeautifulSoup
                    soup=BeautifulSoup(html, 'html.parser')
                    for node in soup(['script','style','nav','footer']):
                        node.decompose()
                    detail_text=soup.get_text(' ',strip=True)
                    job['tech_stacks']=list(dict.fromkeys(job['tech_stacks'] + match_terms(detail_text, TECH_STACKS)))
                    job['specialties']=list(dict.fromkeys(job['specialties'] + match_terms(detail_text, SPECIALTIES)))
                    job['tech_stack_status']='detail_matched' if job['tech_stacks'] else 'not_found_in_detail'
                    job['detail_status']='parsed' if job['preferences'] else 'no_preference_section'
                except (requests.RequestException,RuntimeError,PermissionError) as exc:
                    LOG.warning('상세페이지 읽기 실패 id=%s: %s',job['source_id'],exc)
                    job['detail_status']='unavailable'
        return list(jobs.values())
