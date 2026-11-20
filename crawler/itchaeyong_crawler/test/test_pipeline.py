"""Synthetic HTML/cursors only. These fixtures are not actual collected job postings."""
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import types
from contextlib import contextmanager
from unittest.mock import Mock
import pytest
import requests

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'database/scripts'))
sys.path.insert(0, str(ROOT / 'crawler'))
from itchaeyong_crawler.parser import listing_page, detail_page, absolute_date
from itchaeyong_crawler.crawler import ItchaeyongCrawler, allowed_url
from itchaeyong_crawler.http_headers import HTML_ACCEPT
from itchaeyong_csv import FIELDS, validate_job, read_csv, write_csv, dedupe_jobs
import collect_itchaeyong_jobs as collector
import import_itchaeyong_csv as importer
from saramin_csv import reserve_path


def html(ids, next_page=None):
    cards = ''.join(f'''<article><a href="/companies/test">테스트 회사</a>
        <h3><a href="/jobs/job-{i}">합성 백엔드 공고 {i}</a></h3>
        <p>백엔드 · 경력 3년 이상 · 서울 · 정규직</p>
        <p>기술 스택: Python, SQL 외 3</p><p>신규 3일 전 D-5</p></article>''' for i in ids)
    return '<main>' + cards + (f'<nav><a href="/jobs/dev?page={next_page}">다음 →</a></nav>' if next_page else '') + '</main>'


def jobs(ids=(1,)):
    return listing_page(html(ids))[0]


def crawler(pages):
    c = ItchaeyongCrawler('TestBot contact=test@example.com')
    c.load_robots = Mock()
    c.get = Mock(side_effect=pages)
    return c


def response(status=200, text='', headers=None):
    return types.SimpleNamespace(status_code=status, text=text, headers=headers or {'Content-Type': 'text/html'})


def test_listing_fields_pagination_and_no_invention():
    rows, next_page, stats, loading = listing_page(html([1, 2], 2))
    assert next_page == 2 and len(rows) == 2 and not loading
    assert stats['candidate_count'] == 2
    row = rows[0]
    assert row['source'] == 'itchaeyong' and row['source_job_id'] == 'job-1'
    assert row['job_url'] == 'https://itchaeyong.com/jobs/job-1'
    assert row['company_name'] == '테스트 회사' and row['job_role'] == ['백엔드']
    assert row['experience'] == '경력 3년 이상' and row['location'] == '서울'
    assert row['employment_type'] == '정규직' and row['tech_stack'] == ['Python', 'SQL']
    assert row['posted_at'] is None and row['deadline_at'] is None
    assert row['requirements'] == row['preferred_qualifications'] == []


def test_detail_structured_and_visible_sections():
    page = '''<main><h1>합성 공고</h1><a href="https://careers.example.com/1">공고 원문</a>
    <section><h2>자격 요건</h2><ul><li>Python 경험</li><li>협업 경험</li></ul></section>
    <section><h2>우대사항</h2><p>SQL 활용 경험</p></section></main>
    <script type="application/ld+json">{"@type":"JobPosting","datePosted":"2026-10-01",
    "validThrough":"2026-12-31T23:59:00+09:00","skills":"Python, SQL",
    "hiringOrganization":{"name":"합성 회사"},"employmentType":"정규직",
    "jobLocation":{"address":{"addressRegion":"서울","addressLocality":"강남구"}}}</script>
    <script>self.__next_f.push('hidden technologies: Rust')</script>'''
    detail = detail_page(page)
    assert detail['original_url'] == 'https://careers.example.com/1'
    assert detail['requirements'] == ['Python 경험', '협업 경험']
    assert detail['preferred_qualifications'] == ['SQL 활용 경험']
    assert detail['tech_stack'] == ['Python', 'SQL'] and detail['company_name'] == '합성 회사'
    assert detail['location'] == '서울 강남구'
    assert detail['posted_at'].isoformat() == '2026-09-30T15:00:00+00:00'


def test_detail_unknown_and_dates():
    assert detail_page('<main><p>Python 경험 우대</p><iframe src="/api/jobs"></iframe></main>')['tech_stack'] == []
    for value in ('3일 전', 'D-5', '2026-99-01', None):
        assert absolute_date(value) is None


def test_multiple_explicit_roles_and_posting_quarter_boundary(tmp_path):
    from backend.app.services.career_insight_stats import posting_quarter
    page = html([1]).replace('백엔드 ·', '백엔드, 프론트엔드 ·')
    row = listing_page(page)[0][0]
    assert row['job_role'] == ['백엔드', '프론트엔드']
    assert posting_quarter(absolute_date('2026-10-01')) == '2026-Q4'
    path = tmp_path / '500.csv'
    c = crawler([html(range(1, 601))])
    write_csv(path, c.crawl(details=False))
    assert len(list(read_csv(path))) == 500


def test_500_cap_and_duplicates():
    c = crawler([html(range(1, 301), 2), html(range(250, 601), 3)])
    rows = c.crawl(details=False)
    assert len(rows) == 500 == len({r['source_job_id'] for r in rows})
    assert c.get.call_count == 2 and c.report['duplicate_count'] == 51
    assert c.report['achieved_500'] and c.report['stop_reason'] == 'target_reached'
    assert c.get.call_args_list[1].args == ('https://itchaeyong.com/jobs/dev?page=2',)


@pytest.mark.parametrize('pages, reason, count', [
    ([html([1], 2), html([1], 3)], 'repeated_page', 1),
    (['<main></main>'], 'empty_page', 0),
    ([html([1])], 'last_page', 1),
])
def test_termination(pages, reason, count):
    c = crawler(pages)
    assert len(c.crawl(details=False)) == count
    assert c.report['stop_reason'] == reason


def test_loading_shell_not_success():
    c = crawler(['<main>채용 정보를 불러오는 중…</main>'])
    c.crawl(details=False)
    assert c.report['status'] == 'stopped' and 'loading shell' in c.report['stop_reason']


def test_network_checkpoint_resume_and_interruption(tmp_path):
    path = tmp_path / 'resume.csv'
    c = crawler([html([1, 2], 2), requests.ConnectionError('private connection text')])
    c.crawl(details=False, checkpoint=lambda rows, _: write_csv(path, rows))
    assert len(list(read_csv(path))) == 2 and c.report['stop_reason'] == 'ConnectionError'
    resumed = crawler([html([1, 2, 3, 4])])
    assert len(resumed.crawl(target_count=3, details=False, initial_jobs=read_csv(path))) == 3
    assert resumed.report['duplicate_count'] == 2
    c = crawler([html([1], 2), KeyboardInterrupt()])
    c.crawl(details=False)
    assert c.report['status'] == 'stopped'


@pytest.mark.parametrize('status', [401, 403, 429, 302, 503])
def test_robots_http_restrictions_no_retry(status, monkeypatch):
    monkeypatch.setattr('itchaeyong_crawler.crawler.time.sleep', lambda _: None)
    session = Mock(headers={})
    session.get.return_value = response(status, headers={'Retry-After': '120'})
    c = ItchaeyongCrawler('TestBot', session=session)
    assert c.crawl() == []
    assert c.report['status'] == 'stopped' and session.get.call_count == 1
    assert c.report['request_count'] == 1 and c.report['retry_after'] == '120'


def test_robots_rules_request_budget_and_delay(monkeypatch):
    sleep = Mock()
    monkeypatch.setattr('itchaeyong_crawler.crawler.time.sleep', sleep)
    session = Mock(headers={})
    session.get.side_effect = [response(text='User-agent: *\nAllow: /\nDisallow: /api/\nCrawl-delay: 5', headers={'Content-Type': 'text/plain'}), response(text=html([1]))]
    c = ItchaeyongCrawler('TestBot', session=session)
    assert len(c.crawl(details=False)) == 1
    assert c.delay == 5 and sleep.call_count == 1 and c.request_count == 2
    session.get.side_effect = None
    session.get.return_value = response(text='User-agent: *\nAllow: /', headers={'Content-Type': 'text/plain'})
    c.crawl(max_requests=1)
    assert c.report['stop_reason'] == 'max_requests' and c.request_count == 1


def test_plain_text_robots_header_is_request_scoped(monkeypatch):
    monkeypatch.setattr('itchaeyong_crawler.crawler.time.sleep', lambda _: None)
    c = ItchaeyongCrawler('PlaymateResearchBot/1.0 (contact: test@example.com)')
    prepared = []
    def send(request, **kwargs):
        prepared.append(request)
        assert kwargs['allow_redirects'] is False
        result = requests.Response()
        result.status_code = 200
        result.request = request
        result.url = request.url
        result.headers['Content-Type'] = 'text/plain' if request.url.endswith('robots.txt') else 'text/html'
        result._content = b'User-agent: *\nAllow: /' if request.url.endswith('robots.txt') else b'<main></main>'
        return result
    monkeypatch.setattr(c.session, 'send', send)
    c.load_robots()
    c.get('https://itchaeyong.com/jobs/dev')
    assert [r.headers['Accept'] for r in prepared] == ['text/plain', HTML_ACCEPT]
    assert all(r.headers['User-Agent'] == 'PlaymateResearchBot/1.0 (contact: test@example.com)' for r in prepared)
    assert c.session.headers['Accept'] == HTML_ACCEPT and c.session.trust_env is True


def test_http_403_trace_survives_stop_without_sensitive_headers(monkeypatch):
    session = Mock(headers={})
    session.get.return_value = response(403, '<title>Just a moment</title>',
        {'Content-Type': 'text/html', 'Date': 'Fri, 20 Nov 2026 03:08:33 GMT'})
    c = ItchaeyongCrawler('TestBot contact=private@example.com', session=session)
    c.crawl()
    trace = c.report['http_responses'][0]
    assert trace['url'] == 'https://itchaeyong.com/robots.txt' and trace['status'] == 403
    assert trace['requested_at'] and trace['responded_at'] and trace['response_date']
    assert trace['challenge_html'] and trace['accept'] == 'text/plain'
    assert 'private@example.com' not in json.dumps(trace)
    assert session.get.call_count == 1 and c.report['status'] == 'stopped'


def test_robots_deny_and_challenge(monkeypatch):
    monkeypatch.setattr('itchaeyong_crawler.crawler.time.sleep', lambda _: None)
    session = Mock(headers={})
    session.get.return_value = response(text='User-agent: *\nDisallow: /jobs/', headers={'Content-Type': 'text/plain'})
    c = ItchaeyongCrawler('TestBot', session=session)
    assert c.crawl() == [] and session.get.call_count == 1
    assert '불허' in c.report['stop_reason']
    session.get.return_value = response(text='<html><title>Just a moment</title></html>')
    c.crawl()
    assert 'challenge' in c.report['stop_reason']


@pytest.mark.parametrize('url', [
    'https://itchaeyong.com/api/jobs', 'https://itchaeyong.com/jobs/dev?_rsc=x',
    'https://itchaeyong.com/jobs/dev?page=2&_rsc=x', 'https://itchaeyong.com/jobs/test.rsc',
    'https://itchaeyong.com/jobs/test?x=1', 'https://example.com/jobs/test',
    'https://itchaeyong.com@evil.example/jobs/test', 'https://itchaeyong.com/jobs/dev?page=0',
])
def test_disallowed_urls(url):
    assert not allowed_url(url)


def test_detail_failure_preserves_listing(tmp_path):
    path = tmp_path / 'failure.csv'
    c = crawler([html([1, 2]), requests.Timeout()])
    c.crawl(checkpoint=lambda rows, _: write_csv(path, rows))
    rows = list(read_csv(path))
    assert len(rows) == 1 and rows[0]['detail_status'] == 'unavailable'
    assert c.get.call_count == 2


def test_csv_roundtrip_encoding_and_atomicity(tmp_path):
    path = tmp_path / 'jobs.csv'
    rows = jobs()
    reserve_path(path)
    write_csv(path, rows)
    assert path.read_bytes().startswith(b'\xef\xbb\xbf')
    assert list(read_csv(path)) == rows
    assert rows[0]['original_url'] is None
    with path.open(encoding='utf-8-sig', newline='') as stream:
        assert next(csv.reader(stream)) == list(FIELDS)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        reserve_path(path)
    with pytest.raises(ValueError):
        write_csv(path, [dict(rows[0], tech_stack='Python')])
    assert path.read_bytes() == before


@pytest.mark.parametrize('field, value', [('source', 'saramin_web'), ('job_url', 'https://example.com'),
    ('source_job_id', '../api'), ('job_title', None), ('job_role', '백엔드'),
    ('collected_at', '2026-11-20T12:00:00'), ('posted_at', '3일 전'), ('original_url', 'javascript:bad')])
def test_invalid_contract(field, value):
    with pytest.raises((ValueError, TypeError)):
        validate_job(dict(jobs()[0], **{field: value}))


def test_csv_header_and_json_errors(tmp_path):
    path = tmp_path / 'bad.csv'
    path.write_text('source,source_job_id\nitchaeyong,1', encoding='utf-8-sig')
    with pytest.raises(ValueError, match='헤더'):
        list(read_csv(path))
    write_csv(path, jobs())
    text = path.read_text(encoding='utf-8-sig').replace('"[""백엔드""]"', 'bad-array')
    path.write_text(text, encoding='utf-8-sig')
    with pytest.raises(ValueError, match='행'):
        list(read_csv(path))


def test_dedupe_preserves_data():
    row = jobs()[0]
    updated = dict(row, tech_stack=[], original_url='https://careers.example.com/1')
    result, skipped = dedupe_jobs([updated, row])
    assert len(result) == skipped == 1
    assert result[0]['original_url'] == updated['original_url']
    assert result[0]['tech_stack'] == ['Python', 'SQL']


def test_cli_exports_and_resumes(tmp_path, monkeypatch):
    c = crawler([html([1, 2])])
    monkeypatch.setattr(collector, 'ItchaeyongCrawler', lambda **_: c)
    path, report = tmp_path / 'jobs.csv', tmp_path / 'report.json'
    args = ['--permission-confirmed', '--user-agent', 'TestBot', '--target-count', '2',
        '--list-only', '--csv', str(path), '--report', str(report)]
    assert collector.main(args) == 0
    data = json.loads(report.read_text(encoding='utf-8'))
    assert data['csv_rows'] == 2 and data['csv_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(SystemExit):
        collector.main(args)
    c = crawler([html([1, 2, 3])])
    monkeypatch.setattr(collector, 'ItchaeyongCrawler', lambda **_: c)
    args = ['--permission-confirmed', '--user-agent', 'TestBot', '--target-count', '3', '--list-only',
        '--resume', str(path), '--csv', str(tmp_path / 'new.csv'), '--report', str(tmp_path / 'new.json')]
    assert collector.main(args) == 0 and len(list(read_csv(path))) == 2
    assert len(list(read_csv(tmp_path / 'new.csv'))) == 3


def test_cli_permission_gate(monkeypatch):
    factory = Mock()
    monkeypatch.setattr(collector, 'ItchaeyongCrawler', factory)
    with pytest.raises(SystemExit):
        collector.main([])
    factory.assert_not_called()


def test_import_sql_binding_and_offline_default(tmp_path, monkeypatch):
    rows = jobs([1, 2])
    cursor = Mock()
    cursor.fetchone.side_effect = [{'inserted': True}, {'inserted': False}]
    report = importer.import_jobs(cursor, rows + rows)
    assert (report.inserted, report.updated, report.skipped) == (1, 1, 2)
    sql, payload = cursor.execute.call_args.args
    assert 'ON CONFLICT (source,source_job_id)' in sql and 'COALESCE' in sql
    assert 'SELECT DISTINCT unnest' in sql and 'collected_at = ' not in sql
    assert payload['original_url'] is None and payload['tech_stack'] == ['Python', 'SQL']
    assert '%(job_title)s' in sql and rows[0]['job_title'] not in sql
    path = tmp_path / 'jobs.csv'
    write_csv(path, rows)
    module = types.ModuleType('app.core.db_connect')
    module.db_cursor = Mock(side_effect=AssertionError('DB access forbidden'))
    monkeypatch.setitem(sys.modules, 'app.core.db_connect', module)
    assert importer.main([str(path)]) == 0
    module.db_cursor.assert_not_called()


def test_preview_apply_verify_and_rollback(tmp_path, monkeypatch):
    path = tmp_path / 'jobs.csv'
    write_csv(path, jobs())
    cursor, events = Mock(), []
    @contextmanager
    def db_cursor(commit=False):
        try:
            yield cursor
            events.append('commit' if commit else 'readonly')
        except Exception:
            events.append('rollback')
            raise
    module = types.ModuleType('app.core.db_connect')
    module.db_cursor = db_cursor
    monkeypatch.setitem(sys.modules, 'app.core.db_connect', module)
    assert importer.main([str(path), '--preview-db']) == 0
    assert 'READ ONLY' in cursor.execute.call_args_list[0].args[0]
    cursor.fetchone.side_effect = [{'inserted': True}, (1,)]
    assert importer.main([str(path), '--apply']) == 0
    cursor.fetchone.side_effect = [{'inserted': True}, None]
    with pytest.raises(RuntimeError):
        importer.main([str(path), '--apply'])
    assert events == ['readonly', 'commit', 'rollback']


def test_stats_adapter_and_snapshot(monkeypatch):
    from backend.app.routers import career_insights as api
    from backend.app.services.career_insight_stats import summarize
    now = datetime(2026, 11, 20, tzinfo=timezone.utc)
    row = dict(source='itchaeyong', source_id='1', job_roles=['백엔드'], specialties=['dev'],
        tech_stacks=['Python'], preferences=[], certifications=[], company='합성 회사',
        career='신입', location='서울', job_category='dev', collected_at=now,
        posted_at=None, collection_year=2026, collection_quarter=4)
    connection = Mock()
    connection.__enter__ = Mock(return_value=connection)
    connection.__exit__ = Mock(return_value=False)
    cursor = Mock()
    cursor.__enter__ = Mock(return_value=cursor)
    cursor.__exit__ = Mock(return_value=False)
    connection.cursor.return_value = cursor
    cursor.fetchall.return_value = [row]
    monkeypatch.setattr(api, 'connect', lambda: connection)
    monkeypatch.setenv('CAREER_INSIGHTS_DB_SOURCE', 'itchaeyong')
    rows = api.get_rows('db')
    assert 'FROM itchaeyong_job_postings' in cursor.execute.call_args.args[0]
    result = summarize(rows, source='itchaeyong')
    assert result['companies'] == [{'name': '합성 회사', 'count': 1}]
    assert result['experience'] == [{'name': '신입', 'count': 1}]
    assert result['locations'] == [{'name': '서울', 'count': 1}]
    assert result['trend_basis'] == 'collection_snapshot' and result['posting_trend'] == []
    row['posted_at'] = datetime(2026, 8, 1, tzinfo=timezone.utc)
    result = summarize([row])
    assert result['posting_trend'] == [{'id': '2026-Q3', 'count': 1}]
    assert result['trend'] == [{'id': '2026-Q4', 'count': 1}]
