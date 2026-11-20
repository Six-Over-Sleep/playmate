"""Response page classification: NORMAL_PAGE / CHALLENGE_PAGE / UNKNOWN_PAGE.

Decisions use the parsed DOM (title, forms, element ids, script src, job links), never a
whole-document substring search, so comments or passive scripts in a normal page do not stop a run.
An uncertain page is reported as UNKNOWN_PAGE; it is neither treated as normal data nor as a block.
"""
from __future__ import annotations
import re
from bs4 import BeautifulSoup, Comment
from .parser import job_id

NORMAL_PAGE, CHALLENGE_PAGE, UNKNOWN_PAGE = 'NORMAL_PAGE', 'CHALLENGE_PAGE', 'UNKNOWN_PAGE'
# Interstitial titles used by Cloudflare challenge/block pages (English and Korean localisations).
CHALLENGE_TITLES = re.compile(r'^(just a moment|attention required|please wait|잠시만 기다리십시오|access denied'
    r'|one more step|checking your browser)', re.I)
CHALLENGE_IDS = ('challenge-form', 'challenge-running', 'challenge-stage', 'challenge-error-text',
    'challenge-body-text', 'cf-challenge-running', 'cf-error-details', 'cf-wrapper')
# The orchestrated challenge lives under /h/; /scripts/jsd/ is a passive script also injected into normal pages.
ACTIVE_CHALLENGE_SRC = re.compile(r'/cdn-cgi/challenge-platform/(?:h/|orchestrate/)', re.I)
PASSIVE_CHALLENGE_SRC = re.compile(r'/cdn-cgi/challenge-platform/scripts/jsd/', re.I)


def page_kind(url):
    if url.endswith('/robots.txt'):
        return 'robots'
    return 'listing' if '/jobs/dev' in url else 'detail'


def classify_page(text, kind='listing'):
    """Return verdict plus the evidence that produced it (no raw body, no token values)."""
    soup = BeautifulSoup(text or '', 'html.parser')
    for node in soup.find_all(string=lambda value: isinstance(value, Comment)):
        node.extract()
    title = soup.title.get_text(' ', strip=True) if soup.title else None
    strong, weak = [], []
    if title and CHALLENGE_TITLES.match(title):
        strong.append(f'title:{title[:60]}')
    for identifier in CHALLENGE_IDS:
        if soup.find(id=identifier):
            strong.append(f'id:{identifier}')
    for form in soup.select('form[action]'):
        if '__cf_chl' in form['action']:
            strong.append('form:__cf_chl action')
            break
    for script in soup.find_all('script'):
        src = script.get('src') or ''
        body = script.string or ''
        if ACTIVE_CHALLENGE_SRC.search(src) or '_cf_chl_opt' in body:
            strong.append('script:challenge-platform orchestrate')
        elif PASSIVE_CHALLENGE_SRC.search(src) or PASSIVE_CHALLENGE_SRC.search(body) or '__CF$cv$params' in body:
            weak.append('script:passive cdn-cgi jsd')
    if soup.select_one('.cf-turnstile'):
        strong.append('widget:turnstile')
    strong, weak = list(dict.fromkeys(strong)), list(dict.fromkeys(weak))
    links = {job_id(a['href']) for a in soup.select('a[href]')} - {None}
    headings = sum(1 for h in soup.select('h3') if (h.find('a', href=True) or h.find_parent('a', href=True))
        and job_id((h.find('a', href=True) or h.find_parent('a', href=True))['href']))
    has_jobposting = any('JobPosting' in (s.string or '') for s in soup.select('script[type="application/ld+json"]'))
    has_main = bool(soup.find('main'))
    has_h1 = bool(soup.find('h1'))
    result = dict(kind=kind, title=title, body_bytes=len((text or '').encode('utf-8')),
        job_link_count=len(links), job_heading_count=headings, has_main=has_main, has_h1=has_h1,
        has_jobposting_jsonld=has_jobposting, challenge_evidence=strong, passive_evidence=weak)
    if kind == 'listing':
        content = len(links) > 0
    elif kind == 'detail':
        content = has_jobposting or (has_main and has_h1)
    else:
        content = False
    if strong and not content:
        verdict, reason = CHALLENGE_PAGE, '챌린지 DOM 구조 확인, 채용 콘텐츠 없음'
    elif strong:
        verdict, reason = UNKNOWN_PAGE, '챌린지 구조와 채용 콘텐츠가 함께 존재: 판정 보류'
    elif content:
        verdict, reason = NORMAL_PAGE, ('공고 링크 존재' if kind == 'listing' else '공고 상세 구조 존재')
    else:
        verdict, reason = UNKNOWN_PAGE, '챌린지 구조도 채용 콘텐츠도 확인되지 않음'
    result.update(verdict=verdict, reason=reason)
    return result


# Values that identify a client/session inside a page body; debug copies keep only the key names.
SECRET_PATTERNS = (
    (re.compile(r"(window\.__CF\$cv\$params\s*=\s*)\{[^}]*\}"), r'\1{REDACTED}'),
    (re.compile(r'(window\._cf_chl_opt\s*=\s*)\{.*?\};', re.S), r'\1{REDACTED};'),
    (re.compile(r'''(name=["'][^"']*(?:csrf|token|session|nonce)[^"']*["'][^>]*?value=["'])[^"']*''', re.I), r'\1REDACTED'),
    (re.compile(r'''(\snonce=["'])[^"']*''', re.I), r'\1REDACTED'),
    (re.compile(r'__cf_chl_[a-z_]*=[^"&\s]+', re.I), '__cf_chl_REDACTED'),
    (re.compile(r'''([?&]ray=)[^"'&\s]+''', re.I), r'\1REDACTED'),
)


def redact_html(text):
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text
