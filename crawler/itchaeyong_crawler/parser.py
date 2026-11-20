"""Semantic public HTML/JobPosting JSON-LD only; never parse Next.js flight payloads."""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse, parse_qs
from bs4 import BeautifulSoup

BASE = 'https://itchaeyong.com'
ROLES = ('ML/AI', '개발(일반)', '보안', '백엔드', '데이터', 'DevOps/인프라',
    '하드웨어', 'QA', '프론트엔드', '풀스택', '안드로이드', 'iOS', '모바일')
EMPLOYMENT = ('정규직', '계약직', '인턴', '파트타임', '프리랜서', '기타')


def clean(node):
    return node.get_text(' ', strip=True) if node else ''


def job_id(url):
    parsed = urlparse(urljoin(BASE, url))
    if parsed.scheme != 'https' or parsed.netloc != 'itchaeyong.com':
        return None
    match = re.fullmatch(r'/jobs/([A-Za-z0-9_-]+)/?', parsed.path)
    return match[1] if match and match[1] != 'dev' else None


def absolute_date(value):
    """Only absolute dates; never convert '3일 전' into an invented posting date."""
    if not isinstance(value, str) or not re.match(r'^\d{4}-\d{2}-\d{2}(?:T| |$)', value):
        return None
    try:
        dt = datetime.fromisoformat(value)
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone(timedelta(hours=9)))).astimezone(timezone.utc)
    except ValueError:
        return None


def new_job(identifier, title, now=None):
    return dict(source='itchaeyong', source_job_id=identifier,
        job_url=f'{BASE}/jobs/{identifier}', original_url=None, company_name=None,
        job_title=title, job_category='dev', job_role=[], experience=None,
        employment_type=None, location=None, tech_stack=[], requirements=[],
        preferred_qualifications=[], posted_at=None, deadline_at=None,
        collected_at=now or datetime.now(timezone.utc), detail_status='not_requested')


def listing_page(html, page=1):
    soup = BeautifulSoup(html, 'html.parser')
    for node in soup(['script', 'style', 'footer', 'header']):
        node.decompose()
    root = soup.find('main') or soup
    jobs, seen = [], set()
    stats = dict(candidate_count=0, invalid_count=0, duplicate_count=0)
    for heading in root.select('h3'):
        anchor = heading.find('a', href=True) or heading.find_parent('a', href=True)
        if not anchor:
            continue
        identifier = job_id(anchor['href'])
        if not identifier:
            continue
        stats['candidate_count'] += 1
        if identifier in seen:
            stats['duplicate_count'] += 1
            continue
        seen.add(identifier)
        title = clean(heading)
        if not title:
            stats['invalid_count'] += 1
            continue
        card = heading.parent
        for parent in heading.parents:
            if parent.name in ('main', 'body', 'html') or len(parent.select('h3')) != 1:
                break
            card = parent
            if parent.name in ('article', 'li') or parent.get('data-job-id'):
                break
        job = new_job(identifier, title)
        company = card.select_one('a[href^="/companies/"], a[href^="/company/"], [data-company-name]')
        job['company_name'] = (company.get('data-company-name') or clean(company)) if company else None
        # Only explicit card metadata, never infer a role/stack from title or company text.
        for paragraph in card.select('p, [data-job-meta]'):
            text = clean(paragraph)
            if ' · ' not in text and text not in ROLES:
                continue
            parts = [v.strip() for v in text.split('·')]
            roles = [v.strip() for v in parts[0].split(',')] if parts else []
            if not roles or not all(role in ROLES for role in roles):
                continue
            job['job_role'] = list(dict.fromkeys(roles))
            for part in parts[1:]:
                if part in EMPLOYMENT:
                    job['employment_type'] = part
                elif re.match(r'^(신입|경력|경력무관)', part):
                    job['experience'] = part
                elif part:
                    job['location'] = part
            break
        text = card.get_text('\n', strip=True)
        stack = re.search(r'기술 스택\s*[:：]\s*([^\n]+)', text)
        if stack:
            value = re.split(r'\s+외\s+\d+|\s+신규|\s+\d+일 전', stack[1])[0]
            job['tech_stack'] = [s.strip() for s in value.split(',') if s.strip()]
        for tag in card.select('time[datetime]'):
            if tag.get('itemprop') == 'datePosted':
                job['posted_at'] = absolute_date(tag['datetime'])
            elif tag.get('itemprop') == 'validThrough':
                job['deadline_at'] = absolute_date(tag['datetime'])
        jobs.append(job)
    next_page = None
    for anchor in soup.select('a[href]'):
        parsed = urlparse(urljoin(BASE, anchor['href']))
        query = parse_qs(parsed.query)
        if parsed.netloc != 'itchaeyong.com' or parsed.path != '/jobs/dev' or set(query) != {'page'}:
            continue
        number = query['page'][0]
        if number.isdigit() and int(number) == page + 1:
            next_page = int(number)
            break
    # A visible loading shell is an unsupported response, not proof of no vacancies.
    loading_shell = not jobs and ('채용 정보를 불러오는 중' in clean(root)
        or any(job_id(a['href']) for a in root.select('a[href]')))
    return jobs, next_page, stats, loading_shell


def structured_jobs(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            values = json.loads(script.string or script.get_text())
        except (ValueError, TypeError):
            continue
        queue = values if isinstance(values, list) else [values]
        for value in queue:
            if not isinstance(value, dict):
                continue
            if isinstance(value.get('@graph'), list):
                queue.extend(value['@graph'])
            kind = value.get('@type')
            if kind == 'JobPosting' or isinstance(kind, list) and 'JobPosting' in kind:
                yield value


def paragraph_items(value):
    if not isinstance(value, str):
        return []
    soup = BeautifulSoup(value, 'html.parser')
    items = [clean(n) for n in soup.select('li, p') if clean(n)]
    return list(dict.fromkeys(items or ([clean(soup)] if clean(soup) else [])))


def detail_page(html):
    soup = BeautifulSoup(html, 'html.parser')
    result = dict(original_url=None, company_name=None, experience=None,
        employment_type=None, location=None, tech_stack=[], requirements=[],
        preferred_qualifications=[], posted_at=None, deadline_at=None)
    # JSON-LD is a public HTML standard. Ignore all ordinary/RSC script content.
    for value in structured_jobs(soup):
        result['posted_at'] = absolute_date(value.get('datePosted'))
        result['deadline_at'] = absolute_date(value.get('validThrough'))
        company = value.get('hiringOrganization')
        if isinstance(company, dict) and isinstance(company.get('name'), str):
            result['company_name'] = company['name']
        if isinstance(value.get('employmentType'), str):
            result['employment_type'] = value['employmentType']
        for key, field in (('qualifications', 'requirements'), ('skills', 'tech_stack')):
            result[field] = paragraph_items(value.get(key))
        result['tech_stack'] = [part.strip() for item in result['tech_stack'] for part in item.split(',') if part.strip()]
        if isinstance(value.get('experienceRequirements'), str):
            result['experience'] = value['experienceRequirements']
        place = value.get('jobLocation')
        if isinstance(place, list):
            place = place[0] if place else None
        if isinstance(place, dict) and isinstance(place.get('address'), dict):
            address = place['address']
            result['location'] = ' '.join(address[k] for k in ('addressRegion', 'addressLocality', 'streetAddress')
                if isinstance(address.get(k), str)) or None
        url = value.get('url')
        if isinstance(url, str) and urlparse(url).scheme in ('http', 'https') and urlparse(url).hostname != 'itchaeyong.com':
            result['original_url'] = url
        # One detail page must not import related vacancies' metadata.
        break
    for node in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
        node.decompose()
    root = soup.find('main') or soup
    for anchor in root.select('a[href]'):
        text, url = clean(anchor), urljoin(BASE, anchor['href'])
        if any(label in text for label in ('원문', '지원하기', '공식 채용')):
            parsed = urlparse(url)
            if parsed.scheme in ('http', 'https') and parsed.hostname != 'itchaeyong.com' and not parsed.username:
                result['original_url'] = url
                break
    labels = {'자격요건': 'requirements', '지원자격': 'requirements',
        '우대사항': 'preferred_qualifications', '우대조건': 'preferred_qualifications', '기술스택': 'tech_stack'}
    for heading in root.select('h2, h3, h4'):
        key = labels.get(re.sub(r'[\s:：]', '', clean(heading)))
        if not key:
            continue
        parts = []
        for sibling in heading.next_siblings:
            if getattr(sibling, 'name', None) in ('h1', 'h2', 'h3', 'h4', 'section'):
                break
            if getattr(sibling, 'name', None):
                parts.extend(paragraph_items(str(sibling)))
        result[key] = list(dict.fromkeys(result[key] + parts))
    result['tech_stack'] = list(dict.fromkeys(part.strip() for item in result['tech_stack'] for part in item.split(',') if part.strip()))
    return result
