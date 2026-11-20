"""Honest identification and safe diagnostic output; no browser impersonation."""
import re
from urllib.parse import urlsplit, urlunsplit

USER_AGENT = 'PlaymateResearchBot/1.0 (PlayMate student project; public job postings; low rate)'
HTML_ACCEPT = 'text/html,application/xhtml+xml;q=0.9,*/*;q=0.8'
ACCEPT_LANGUAGE = 'ko-KR,ko;q=0.9,en;q=0.5'


def redact_text(value):
    text = str(value)
    text = re.sub(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', '[REDACTED_EMAIL]', text)
    text = re.sub(r'(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+', r'\1 [REDACTED]', text)
    return text


def masked_headers(headers):
    sensitive = re.compile(r'authorization|cookie|token|secret|api[-_]?key|password|^from$', re.I)
    return {str(key): '[REDACTED]' if sensitive.search(str(key)) else redact_text(value)
        for key, value in headers.items()}


def safe_url(url):
    """Diagnostics never expose credentials, fragments or arbitrary query values."""
    try:
        parsed = urlsplit(url)
        netloc = parsed.hostname or ''
        if parsed.port:
            netloc += f':{parsed.port}'
        query = parsed.query if re.fullmatch(r'page=[0-9]+', parsed.query) else ('REDACTED' if parsed.query else '')
        return redact_text(urlunsplit((parsed.scheme, netloc, parsed.path, query, '')))
    except ValueError:
        return '[INVALID_URL]'


def validate_contact(value):
    if value is not None and not re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', value):
        raise ValueError('승인된 연락처는 개행 없는 이메일 주소여야 합니다')
    return value
