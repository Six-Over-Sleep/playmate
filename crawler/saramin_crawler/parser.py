"""웹페이지 HTML 파싱: 접근 권한 없는 페이지/로그인 제한 우회하지 않음."""
from __future__ import annotations
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse, parse_qs
from bs4 import BeautifulSoup
from config import SPECIALTIES, JOB_ROLES, TECH_STACKS

BASE = 'https://www.saramin.co.kr'

def clean(node):
    return node.get_text(' ', strip=True) if node else ''

def find_first(node, *selectors):
    for selector in selectors:
        found = node.select_one(selector)
        if found:
            return found
    return None

# 영어 약어는 단어 경계를, 한글 직무는 공백/구분자 차이를 허용한다.
# 제목에 직무가 있더라도 실제 직무 태그가 비IT에 편중되면 제외한다.
ROLE_ALIASES = {
    '데이터엔지니어': ('데이터 엔지니어', 'data engineer', 'data engineering'),
    '데이터분석가': ('데이터 분석가', '데이터 분석', 'data analyst'),
    '데이터사이언티스트': ('데이터 사이언티스트', 'data scientist'),
    '백엔드/서버개발': ('백엔드', '백 엔드', 'backend', 'back-end', '서버 개발'),
    '프론트엔드': ('프론트 엔드', 'frontend', 'front-end'),
    '웹개발': ('웹 개발', 'web developer'),
    '앱개발': ('앱 개발', '모바일 앱 개발', 'android developer', 'ios developer'),
    '게임개발': ('게임 개발', 'game developer'),
    '개발PM': ('개발 PM', '테크니컬 PM', 'technical pm'),
    'BI엔지니어': ('BI 엔지니어', 'business intelligence engineer'),
    'DBA': ('database administrator',),
    'DevOps': ('데브옵스', 'devops engineer'),
    '풀스택': ('풀 스택', 'fullstack', 'full-stack'),
    'AI엔지니어': ('AI 엔지니어', 'AI engineer', '머신러닝 엔지니어', '딥러닝 엔지니어', 'machine learning engineer'),
    '클라우드엔지니어': ('클라우드 엔지니어', 'cloud engineer'),
    'SE(시스템엔지니어)': ('시스템 엔지니어', '시스템엔지니어', 'system engineer'),
    'QA/테스터': ('QA 엔지니어', 'QA engineer', 'SW 테스트', '테스트 자동화'),
    '정보보안': ('정보 보안', 'cybersecurity', '보안 엔지니어'),
}
# '회계'처럼 공고 태그가 전혀 다른 직군을 나타내는 경우 오분류 방지.
NON_IT_TAGS = (
    '관리회계', '기업회계', '법인세신고', '계산서발행', '세무', '재무회계',
    '경리', '급여관리', '영업관리', '매장관리', '고객상담', '인사총무',
)
# 전문분야만으로 IT 직무를 판단하지 않는다 (H/W, 클라우드 같은 태그만으로는 불충분).

def match_terms(text, words, aliases=None):
    """부분 문자열 오인식(예: SQL in MySQL)을 줄인 분류명 매칭."""
    results = []
    text = text or ''
    for word in words:
        terms = (word,) + tuple((aliases or {}).get(word, ()))
        for term in terms:
            if re.search(r'[A-Za-z]', term):
                # ASCII 알파벳이 붙은 접두/접미 단어는 허용하지 않는다.
                pat = rf'(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])'
            else:
                pat = re.escape(term)
            if re.search(pat, text, re.I):
                results.append(word)
                break
    return results

def extract_roles(title, tags):
    # 직무 태그가 신뢰도 최상. 제목 기반 분류는 추정값으로 별도 표시.
    tag_roles = match_terms(tags, JOB_ROLES, ROLE_ALIASES)
    title_roles = match_terms(title, JOB_ROLES, ROLE_ALIASES)
    if tag_roles:
        return list(dict.fromkeys(tag_roles + title_roles)), 'tag_and_title' if set(title_roles) - set(tag_roles) else 'tag'
    if title_roles:
        return title_roles, 'title_estimate'
    return [], 'unknown'

def is_it_listing(title, tags, roles, source):
    """IT 직무가 확인된 공고만 남긴다. 불명확하면 수집 대상에서 제외."""
    if not roles:
        return False
    if source in ('tag', 'tag_and_title'):
        return True
    # 제목에 IT 직무만 있고 태그는 회계 등 비IT 직무일 경우 제외.
    if any(term in tags for term in NON_IT_TAGS):
        return False
    return True

def extract_id(item, link):
    for value in (item.get('value'), item.get('data-recruit-idx'), item.get('data-rec-idx')):
        if value and re.fullmatch(r'\d+', str(value)):
            return str(value)
    query = parse_qs(urlparse(link).query)
    for key in ('rec_idx', 'recruit_idx'):
        if query.get(key) and query[key][0].isdigit():
            return query[key][0]
    return None

def _candidate_cards(soup):
    """Prefer actual recruit links over generic layout nodes (often nested/duplicated)."""
    selectors = (
        'a[href*="rec_idx="]',
        'a[href*="recruit_idx="]',
        'a[href*="/jobs/relay/view"]',
        'a[href*="/zf_user/jobs/view"]',
    )
    anchors = []
    seen_anchors = set()
    for selector in selectors:
        for anchor in soup.select(selector):
            if id(anchor) not in seen_anchors:
                seen_anchors.add(id(anchor))
                anchors.append(anchor)
    for anchor in anchors:
        # Container classes are not unique in the page. Pick a nearby recruit item.
        card = anchor.find_parent(class_=lambda value: value and any(
            cls in str(value).split() for cls in ('item_recruit', 'list_item', 'recruit_info', 'recruit_item')
        ))
        if card is None:
            card = anchor.find_parent(['article','li'])
        if card is None:
            card = anchor.parent
        yield card, anchor


def _job_anchor(card, candidate):
    # Some listing blocks include company/decorative links. Prefer title-specific anchor.
    title_anchor = find_first(
        card,
        'h2.job_tit a', '.job_tit a', '.recruit_tit a',
        '.job_title a', '.recruit_title a', 'a.str_tit',
        'a[href*="rec_idx="]', 'a[href*="recruit_idx="]'
    )
    return title_anchor if title_anchor and clean(title_anchor) else candidate


def _extract_listing_tags(card):
    # Do not match parent .job_sector and children together: creates duplicate text.
    nodes = card.select(
        '.job_sector a, .job_sector span, .job_meta a, .job_meta span, '
        '.job_keyword a, .job_keyword span, .job_tag a, .job_tag span, '
        '.skill a, .skill span, .skills a, .skills span, '
        '.tech_stack a, .tech_stack span, .stack a, .stack span, '
        '.job_skill a, .job_skill span, .job_skill, '
        '[data-skill], [data-tech-stack], [data-skill-name]'
    )
    tags = list(dict.fromkeys(clean(n) for n in nodes if clean(n)))
    # Some job cards encode stack names only in HTML attributes, not visible spans.
    for node in nodes:
        for attr in ('data-skill','data-tech-stack','data-skill-name'):
            value = node.get(attr)
            if value and value not in tags: tags.append(value)
    return tags


def parse_listing(html: str, crawled_at: datetime | None = None, stats=None):
    """Parse deduplicated recruit links, then keep only confirmed IT job roles.

    No fake classification values: a role must be confirmed by tags/title.
    If the returned page contains no identifiable IT postings, returns [].
    """
    soup = BeautifulSoup(html, 'html.parser')
    result, seen = [], set()
    now = crawled_at or datetime.now(timezone.utc).replace(tzinfo=None)
    if stats is not None:
        stats.update(candidate_count=0, filtered_count=0, passed_count=0, source_ids=[])
    for card, candidate in _candidate_cards(soup):
        a = _job_anchor(card, candidate)
        title = clean(a)
        href = a.get('href') or candidate.get('href') or ''
        link = urljoin(BASE, href)
        # IDs can be on the recruit card OR the anchor URL.
        rec_idx = extract_id(card, link) or extract_id(candidate, link)
        if not title or not rec_idx or rec_idx in seen:
            continue
        # Reject off-domain links and likely non-job navigation anchors.
        parsed_url = urlparse(link)
        if parsed_url.hostname not in ('www.saramin.co.kr', 'saramin.co.kr'):
            continue
        seen.add(rec_idx)
        if stats is not None:
            stats['candidate_count'] += 1
            stats['source_ids'].append(rec_idx)
        company = clean(find_first(card, 'div.area_corp strong.corp_name a', 'strong.corp_name a', '.corp_name'))
        deadline = clean(find_first(card, 'div.job_date span.date', '.job_date .date', '.date'))
        spans = card.select('div.area_job div.job_condition > span')
        conditions = [clean(item) for item in spans]
        tags = _extract_listing_tags(card)
        combined_tags = ' '.join(tags)
        roles, role_source = extract_roles(title, combined_tags)
        if not is_it_listing(title, combined_tags, roles, role_source):
            if stats is not None:
                stats['filtered_count'] += 1
            continue
        if stats is not None:
            stats['passed_count'] += 1
        specialties = match_terms(combined_tags, SPECIALTIES)
        title_specialties = match_terms(title, SPECIALTIES) if not specialties else []
        # Also inspect local job card text (not the entire page) to catch skills
        # rendered outside sector/tag containers. Avoid page-wide contamination.
        card_text = clean(card)
        stack_source = ' '.join((title, combined_tags, card_text if len(card_text)<1800 else ''))
        stacks = match_terms(stack_source, TECH_STACKS)
        result.append({
            'source':'saramin_web', 'source_id':rec_idx, 'title':title,
            'company':company or None, 'url':link, 'deadline_text':deadline or None,
            'location': conditions[0] if len(conditions)>0 else None,
            'career': conditions[1] if len(conditions)>1 else None,
            'education': conditions[2] if len(conditions)>2 else None,
            'employment_type': conditions[3] if len(conditions)>3 else None,
            'job_roles': roles, 'specialties': specialties or title_specialties,
            'tech_stacks': stacks, 'preferences': [],
            'role_classification_source': role_source,
            'specialty_classification_source': 'tag' if specialties else ('title_estimate' if title_specialties else 'unknown'),
            'detail_status': 'not_requested',
            'tech_stack_status':'list_matched' if stacks else 'not_found_in_listing',
            'raw_tags':tags,
            'collected_at':now, 'collection_year':now.year, 'collection_quarter':(now.month-1)//3+1,
        })
    return result

PREFERENCE_HEADERS = ('우대사항', '우대 조건', '우대조건', '우대 요건', '우대요건', '우대 자격', '우대자격')

def parse_detail(html: str):
    """정상적으로 열람 가능한 상세 HTML에서만 우대사항 문단 추출.
    구인공고마다 구조가 달라 추출 실패 가능. 추정 문장은 생성하지 않음.
    """
    soup = BeautifulSoup(html, 'html.parser')
    for el in soup(['script', 'style', 'nav', 'footer']):
        el.decompose()
    matches = []
    for heading in soup.find_all(['h2','h3','h4','strong','dt','th']):
        if clean(heading).strip(' :') not in PREFERENCE_HEADERS:
            continue
        pieces = []
        sibling = heading.find_next_sibling()
        if sibling:
            pieces.append(clean(sibling))
        if not pieces and heading.parent:
            pieces.append(clean(heading.parent).replace(clean(heading), '', 1).strip())
        segment = ' '.join(pieces).strip()
        if segment and len(segment) < 2500:
            matches.append(segment)
    return list(dict.fromkeys(matches))


def inspect_detail(html: str):
    """Extract technologies from text actually present in returned HTML.

    HTTP 200 does not mean embedded iframe/image job details were received.
    No guessed technologies are added.
    """
    soup = BeautifulSoup(html, 'html.parser')
    frames = [n.get('src') for n in soup.select('iframe[src]') if n.get('src')]
    for node in soup(['style', 'nav', 'footer']):
        node.decompose()
    # Include embedded JSON/JSON-LD visible in HTML for names like Python/SQL.
    scripts = [n.get_text(' ', strip=True) for n in soup.select('script[type="application/ld+json"]')]
    selectors = (
        '.recruitment-template', '.recruitment-view', '.recruitment-content',
        '.recruitment-detail', '.recruit_content', '.job_description',
        '.cont_recruit', '.user_content', '#recruit_detail',
        '.wrap_jv_cont', '.jv_cont', 'main',
    )
    sections = [clean(node) for selector in selectors for node in soup.select(selector)]
    sections = [x for x in sections if x]
    body_text = ' '.join(sections) if sections else clean(soup.body or soup)
    text = body_text + ' ' + ' '.join(scripts)
    return {
        'tech_stacks':match_terms(text, TECH_STACKS),
        'specialties':match_terms(text, SPECIALTIES),
        'preferences':parse_detail(html),
        'has_iframe':bool(frames),
        'iframe_sources':frames[:5],
        'visible_text_length':len(body_text),
    }
