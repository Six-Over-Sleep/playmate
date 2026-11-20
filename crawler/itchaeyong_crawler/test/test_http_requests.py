"""Network-free HTTP contract tests; all send() calls return synthetic responses."""
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import Mock
import pytest
import requests

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'crawler'))
from itchaeyong_crawler.crawler import ItchaeyongCrawler, CollectionStopped
from itchaeyong_crawler.http_headers import (USER_AGENT, HTML_ACCEPT, ACCEPT_LANGUAGE,
    masked_headers, safe_url)

spec = importlib.util.spec_from_file_location('inspect_crawler_headers', ROOT / 'scripts/inspect_crawler_headers.py')
inspector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inspector)

URL = 'https://itchaeyong.com/jobs/dev'
ROBOTS = 'https://itchaeyong.com/robots.txt'
BODY = '<html><head><title>합성 페이지</title></head><body><main><h3><a href="/jobs/test-1">합성 공고</a></h3></main></body></html>'


def client(monkeypatch, responses, **kwargs):
    """Exercise requests' real preparation, but never its network adapters."""
    c = ItchaeyongCrawler(**kwargs)
    monkeypatch.setattr('itchaeyong_crawler.crawler.time.sleep', lambda _: None)
    pending, sent = iter(responses), []
    def send(prepared, **options):
        sent.append((prepared, options))
        item = next(pending)
        if isinstance(item, Exception):
            raise item
        status, body, headers = item
        r = requests.Response()
        r.status_code, r.url, r.request = status, prepared.url, prepared
        r.headers.update(headers)
        r.encoding = 'utf-8'
        r._content = body.encode('utf-8')
        return r
    monkeypatch.setattr(c.session, 'send', send)
    return c, sent


def ok(body=BODY, **headers):
    return 200, body, {'Content-Type': 'text/html', **headers}


def test_defaults_preparation_timeout_and_optional_headers(monkeypatch):
    c, sent = client(monkeypatch, [ok()])
    prepared = c.prepare_request(URL)
    assert prepared.headers['User-Agent'] == USER_AGENT
    assert prepared.headers['Accept'] == HTML_ACCEPT
    assert prepared.headers['Accept-Language'] == ACCEPT_LANGUAGE
    assert c.session.get_adapter(URL).max_retries.total == 0
    assert c.request(URL) == BODY
    request, options = sent[0]
    assert options['timeout'] == 10 and options['allow_redirects'] is False
    assert request.headers == prepared.headers
    assert c.report['http_responses'][0]['status'] == 200
    for field in ('From', 'If-None-Match', 'If-Modified-Since', 'X-Request-ID', 'Cache-Control',
                  'Referer', 'Content-Type', 'Authorization', 'Cookie', 'Sec-Fetch-Site', 'Sec-CH-UA'):
        assert field not in request.headers
    assert c.prepare_request(ROBOTS).headers['Accept'] == 'text/plain'
    assert c.session.headers['Accept'] == HTML_ACCEPT


def test_contact_from_is_explicit_and_masked(monkeypatch):
    c, sent = client(monkeypatch, [ok()], contact_email='approved@example.com')
    c.request(URL)
    assert sent[0][0].headers['From'] == 'approved@example.com'
    assert c.report['http_responses'][0]['request_headers']['From'] == '[REDACTED]'
    assert 'approved@example.com' not in json.dumps(c.report)
    with pytest.raises(ValueError):
        ItchaeyongCrawler(contact_email='not-an-email\r\nCookie: bad')


def test_conditional_get_304_reuses_only_known_body(monkeypatch):
    headers = {'ETag': '"version-1"', 'Last-Modified': 'Thu, 19 Nov 2026 00:00:00 GMT'}
    c, sent = client(monkeypatch, [ok(**headers), (304, '', {})])
    assert c.request(URL) == BODY
    assert c.request(URL) == BODY
    assert 'If-None-Match' not in sent[0][0].headers
    assert sent[1][0].headers['If-None-Match'] == '"version-1"'
    assert sent[1][0].headers['If-Modified-Since'] == headers['Last-Modified']
    trace = c.report['http_responses'][1]
    assert trace['status'] == 304 and trace['cache_reused'] is True
    assert trace['effective_content_type'] == 'text/html' and trace['job_link_count'] == 1


@pytest.mark.parametrize('server_header, request_header', [('ETag', 'If-None-Match'), ('Last-Modified', 'If-Modified-Since')])
def test_individual_validators_only_when_server_supplies_them(monkeypatch, server_header, request_header):
    c, sent = client(monkeypatch, [ok(**{server_header: 'validator'}), (304, '', {})])
    c.request(URL)
    assert c.request(URL) == BODY
    assert sent[1][0].headers[request_header] == 'validator'
    other = 'If-Modified-Since' if request_header == 'If-None-Match' else 'If-None-Match'
    assert other not in sent[1][0].headers


def test_304_without_cached_body_fails_without_retry(monkeypatch):
    c, sent = client(monkeypatch, [(304, '', {})])
    with pytest.raises(CollectionStopped, match='캐시 본문 없음'):
        c.request(URL)
    assert len(sent) == 1


@pytest.mark.parametrize('cache_headers', [
    {}, {'ETag': 'v1', 'Cache-Control': 'no-store'}, {'ETag': 'v1', 'Cache-Control': 'private'},
    {'ETag': 'v1', 'Set-Cookie': 'session=secret'}, {'ETag': 'v1', 'Vary': '*'},
])
def test_no_unsafe_or_validatorless_cache(monkeypatch, cache_headers):
    c, sent = client(monkeypatch, [ok(**cache_headers), ok()])
    c.request(URL)
    c.request(URL)
    assert 'If-None-Match' not in sent[1][0].headers
    assert not c._cache


def test_cache_scoped_to_headers_and_bounded(monkeypatch):
    c, sent = client(monkeypatch, [ok(ETag='v1')] * 19)
    c.request(URL)
    c.session.headers['Accept-Language'] = 'en'
    c.request(URL)
    assert 'If-None-Match' not in sent[1][0].headers
    for page in range(1, 18):
        c.request(URL + f'?page={page}')
    assert len(c._cache) == 16 and c._cache_bytes <= 8 * 1024 * 1024


@pytest.mark.parametrize('status', [401, 403, 429, 500])
def test_errors_stop_without_automatic_retry(monkeypatch, status):
    c, sent = client(monkeypatch, [(status, 'error', {'Content-Type': 'text/html', 'Retry-After': '120'})])
    with pytest.raises(CollectionStopped) as error:
        c.request(URL)
    assert str(error.value) == f'HTTP {status}' and error.value.retry_after == '120'
    assert len(sent) == 1
    if status in (401, 403, 429):
        with pytest.raises(CollectionStopped):
            c.request(URL)
        assert len(sent) == 1


@pytest.mark.parametrize('location, allowed', [
    ('https://evil.example/jobs/1', False), ('/api/jobs', False), ('/jobs/dev?_rsc=x', False),
    ('/jobs/dev?page=2', True), ('https://itchaeyong.com@evil.example/jobs/1', False),
])
def test_redirects_are_checked_and_never_followed(monkeypatch, location, allowed):
    c, sent = client(monkeypatch, [(302, '', {'Location': location})])
    with pytest.raises(CollectionStopped, match='리다이렉트 중단'):
        c.request(URL)
    trace = c.report['http_responses'][0]
    assert trace['redirect_target_allowed'] == allowed and trace['redirects_followed'] is False
    assert len(sent) == 1 and sent[0][1]['allow_redirects'] is False


@pytest.mark.parametrize('content_type', ['application/json', 'text/plain', 'text/html-malicious', ''])
def test_content_type_checked(monkeypatch, content_type):
    c, _ = client(monkeypatch, [(200, BODY, {'Content-Type': content_type})])
    with pytest.raises(CollectionStopped, match='HTML 이외'):
        c.request(URL)


def test_robots_policy_and_type(monkeypatch):
    c, sent = client(monkeypatch, [(200, 'User-agent: *\nDisallow: /jobs/', {'Content-Type': 'text/plain'})])
    c.load_robots()
    with pytest.raises(CollectionStopped, match='불허'):
        c.get(URL)
    assert len(sent) == 1
    c, _ = client(monkeypatch, [(200, 'User-agent: *\nAllow: /', {'Content-Type': 'text/html'})])
    with pytest.raises(CollectionStopped, match='Content-Type'):
        c.load_robots()


def test_minimum_interval_and_invalid_settings(monkeypatch):
    c, _ = client(monkeypatch, [ok()])
    c.last_request = 10.0
    sleep = Mock()
    monkeypatch.setattr('itchaeyong_crawler.crawler.time.monotonic', lambda: 12.0)
    monkeypatch.setattr('itchaeyong_crawler.crawler.time.sleep', sleep)
    c.request(URL)
    sleep.assert_called_once_with(2.0)
    for delay in (0, 3, float('nan')):
        with pytest.raises(ValueError):
            ItchaeyongCrawler(delay=delay)
    with pytest.raises(ValueError):
        ItchaeyongCrawler(timeout=20)


def test_sensitive_headers_are_masked_in_trace_and_log(monkeypatch, caplog):
    c, _ = client(monkeypatch, [ok(ETag='v1')], user_agent=USER_AGENT + ' contact=private@example.com')
    c.session.headers.update({'Authorization': 'Bearer SECRET_AUTH', 'Cookie': 'session=SECRET_COOKIE',
        'X-API-Key': 'SECRET_KEY'})
    with caplog.at_level('INFO'):
        c.request(URL)
    output = json.dumps(c.report) + caplog.text
    assert not any(value in output for value in ('SECRET_AUTH', 'SECRET_COOKIE', 'SECRET_KEY', 'private@example.com'))
    assert not c._cache
    assert masked_headers({'Proxy-Authorization': 'Basic secret'})['Proxy-Authorization'] == '[REDACTED]'
    assert 'secret' not in safe_url('https://user:secret@example.com/path?token=secret#secret')


def test_inspector_dry_run_no_network(monkeypatch, capsys):
    monkeypatch.delenv('ITCHAEYONG_USER_AGENT', raising=False)
    monkeypatch.delenv('ITCHAEYONG_CONTACT_EMAIL', raising=False)
    send = Mock(side_effect=AssertionError('network forbidden'))
    monkeypatch.setattr(requests.Session, 'send', send)
    assert inspector.main(['--dry-run', '--url', URL]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['network_requests_made'] == 0
    assert output['prepared_headers']['User-Agent'] == USER_AGENT
    assert output['prepared_headers']['Accept'] == HTML_ACCEPT
    send.assert_not_called()


@pytest.mark.parametrize('flags', [['--live'], ['--live', '--authorized', '--url', 'https://evil.example/'],
    ['--live', '--authorized', '--url', URL + '?_rsc=x']])
def test_inspector_permission_and_url_gates(monkeypatch, flags):
    factory = Mock(side_effect=AssertionError('must reject before client construction'))
    monkeypatch.setattr(inspector, 'ItchaeyongCrawler', factory)
    with pytest.raises(SystemExit):
        inspector.main(flags)
    factory.assert_not_called()


def test_inspector_live_is_mocked_and_403_stops(monkeypatch, capsys):
    c, sent = client(monkeypatch, [(403, 'blocked', {'Content-Type': 'text/html'})])
    monkeypatch.setattr(inspector, 'ItchaeyongCrawler', lambda **_: c)
    assert inspector.main(['--live', '--authorized', '--url', URL]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output['network_requests_made'] == 1 and output['error'] == 'HTTP 403'
    assert output['responses'][0]['url'] == ROBOTS and len(sent) == 1


def test_network_exception_does_not_disclose_credentials(monkeypatch, capsys):
    c, sent = client(monkeypatch, [requests.ConnectionError('https://user:SECRET@example.com')])
    monkeypatch.setattr(inspector, 'ItchaeyongCrawler', lambda **_: c)
    assert inspector.main(['--live', '--authorized']) == 2
    output = capsys.readouterr().out
    assert 'ConnectionError' in output and 'SECRET' not in output and len(sent) == 1
