"""All HTML, jobs and database connections in this module are synthetic fixtures."""
import csv
import json
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'crawler/saramin_crawler'))
sys.path.insert(0, str(ROOT / 'database/scripts'))
from crawler import SaraminWebCrawler
from parser import parse_listing
from saramin_csv import FIELDS, read_csv, write_csv, reserve_path
from import_saramin_jobs import import_jobs
import import_saramin_csv as importer
import collect_saramin_jobs as collector


def html(ids, title='백엔드 개발자 Python'):
    return ''.join(f'<li><a href="/zf_user/jobs/relay/view?rec_idx={i}">{title}</a></li>' for i in ids)


def fake_crawler(pages):
    crawler = SaraminWebCrawler(check_robots=False)
    crawler._get = Mock(side_effect=pages)
    return crawler


def test_500_limit_and_page_params():
    c = fake_crawler([html(range(1, 301)), html(range(250, 601))])
    jobs = c.crawl(max_pages=10)
    assert len(jobs) == len({j['source_id'] for j in jobs}) == 500
    assert c._get.call_count == 2
    assert [call.kwargs['params']['page'] for call in c._get.call_args_list] == [1, 2]
    assert c.report['target_reached'] and c.report['duplicate_count'] == 51
    assert c.report['status'] == 'completed'


@pytest.mark.parametrize('pages, reason, count', [
    ([html([1]), html([1])], 'repeated_page', 1),
    ([''], 'empty_page', 0),
    ([html([1], '영업관리'), html([2])], 'target_reached', 1),
])
def test_page_stops(pages, reason, count):
    c = fake_crawler(pages)
    assert len(c.crawl(target_count=1 if reason == 'target_reached' else 500)) == count
    assert c.report['stop_reason'] == reason
    if reason == 'target_reached':
        assert c.report['filtered_count'] == 1


@pytest.mark.parametrize('status', [401, 403, 429, 302])
def test_restrictions_stop_all_requests(status):
    c = SaraminWebCrawler(check_robots=False)
    c.session.get = Mock(return_value=types.SimpleNamespace(status_code=status))
    assert c.crawl(max_pages=10) == []
    assert c.session.get.call_count == 1
    assert c.report['status'] == 'stopped'


def test_network_error_checkpoint_resume(tmp_path):
    path = tmp_path / 'partial.csv'
    c = fake_crawler([html([1, 2]), requests.ConnectionError('offline')])
    c.crawl(checkpoint=lambda jobs: write_csv(path, jobs))
    assert len(list(read_csv(path))) == 2
    resumed = fake_crawler([html([1, 2, 3, 4])])
    rows = resumed.crawl(target_count=3, initial_jobs=read_csv(path))
    assert len(rows) == 3 and resumed.report['duplicate_count'] == 2
    assert resumed.report['resumed_count'] == 2


def test_request_budget_and_robots():
    c = SaraminWebCrawler()
    c.session.get = Mock(return_value=types.SimpleNamespace(status_code=200,
        text='User-agent: *\nAllow: /', raise_for_status=lambda: None))
    c.crawl(max_requests=1)
    assert c.request_count == c.session.get.call_count == 1
    assert c.report['status'] == 'stopped'
    c = SaraminWebCrawler()
    c.session.get = Mock(return_value=types.SimpleNamespace(status_code=200,
        text='User-agent: *\nDisallow: /', raise_for_status=lambda: None))
    c.crawl()
    assert c.session.get.call_count == 1 and 'PermissionError' in c.report['stop_reason']


def test_detail_restriction_preserves_listing(tmp_path):
    c = fake_crawler([html([1, 2]), RuntimeError('HTTP 429')])
    rows = c.crawl(details=True)
    assert len(rows) == 1 and rows[0]['detail_status'] == 'unavailable'
    assert c._get.call_count == 2 and c.report['status'] == 'stopped'


@pytest.mark.parametrize('title, role', [
    ('AI 엔지니어', 'AI엔지니어'), ('머신러닝 엔지니어', 'AI엔지니어'),
    ('클라우드 엔지니어', '클라우드엔지니어'), ('QA 엔지니어', 'QA/테스터'),
    ('풀스택 개발자', '풀스택'), ('DevOps engineer', 'DevOps'),
    ('시스템 엔지니어', 'SE(시스템엔지니어)'), ('보안 엔지니어', '정보보안'),
])
def test_roles(title, role):
    assert role in parse_listing(html([1], title))[0]['job_roles']


def test_unknown_role_not_invented():
    assert parse_listing(html([1], 'Python AWS 담당자')) == []


def test_multiple_roles_preserved():
    page = '<li><a href="/zf_user/jobs/relay/view?rec_idx=1">프론트엔드 개발</a><div class="job_sector"><a>백엔드/서버개발</a></div></li>'
    row = parse_listing(page)[0]
    assert set(row['job_roles']) == {'프론트엔드', '백엔드/서버개발'}
    assert row['role_classification_source'] == 'tag_and_title'


def test_max_pages_and_interrupt(tmp_path):
    c = fake_crawler([html([1])])
    assert len(c.crawl(max_pages=1)) == 1
    assert c.report['stop_reason'] == 'max_pages' and c.report['status'] == 'partial'
    path = tmp_path / 'interrupt.csv'
    c = fake_crawler([html([1]), KeyboardInterrupt()])
    c.crawl(checkpoint=lambda rows: write_csv(path, rows))
    assert len(list(read_csv(path))) == 1 and c.report['status'] == 'stopped'


def test_csv_roundtrip_and_preserve(tmp_path):
    path = tmp_path / 'jobs.csv'
    jobs = parse_listing(html([1, 2], '백엔드 개발자, "한글" Python'))
    reserve_path(path)
    write_csv(path, jobs)
    assert path.read_bytes().startswith(b'\xef\xbb\xbf')
    assert next(csv.reader(path.open(encoding='utf-8-sig'))) == list(FIELDS)
    loaded = list(read_csv(path))
    assert loaded == [{k: job[k] for k in FIELDS} for job in jobs]
    assert loaded[0]['company'] is None
    assert loaded[0]['tech_stacks'] == ['Python']
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        reserve_path(path)
    bad = dict(jobs[0], job_roles='invalid')
    with pytest.raises(ValueError):
        write_csv(path, [bad])
    assert path.read_bytes() == before


@pytest.mark.parametrize('field, value', [('source_id', 'bad'), ('job_roles', []),
    ('collection_quarter', 9), ('collected_at', 'bad'), ('preferences', 'invalid')])
def test_invalid_csv_fields(tmp_path, field, value):
    path = tmp_path / 'bad.csv'
    job = parse_listing(html([1]))[0]
    job[field] = value
    with pytest.raises((ValueError, TypeError)):
        write_csv(path, [job])


def test_missing_header(tmp_path):
    path = tmp_path / 'bad.csv'
    path.write_text('source_id,title\n1,test', encoding='utf-8-sig')
    with pytest.raises(ValueError, match='헤더'):
        list(read_csv(path))


def test_import_mapping_and_dedupe():
    jobs = parse_listing(html([1, 2]))
    cursor = Mock()
    cursor.fetchone.side_effect = [{'inserted': True}, {'inserted': False}]
    result = import_jobs(cursor, [jobs[0], jobs[0], jobs[1]])
    assert (result.inserted, result.updated, result.skipped) == (1, 1, 1)
    sql, payload = cursor.execute.call_args.args
    assert 'ON CONFLICT (source, source_id)' in sql
    assert 'COALESCE(EXCLUDED.company' in sql
    assert 'jsonb_array_elements' in sql
    assert 'collected_at = EXCLUDED' not in sql
    assert payload['job_roles'].adapted == jobs[1]['job_roles']
    assert payload['company'] is None
    assert payload['collected_at'] == jobs[1]['collected_at']


def test_import_default_offline(tmp_path, monkeypatch):
    path = tmp_path / 'jobs.csv'
    write_csv(path, parse_listing(html([1])))
    module = types.ModuleType('app.core.db_connect')
    module.db_cursor = Mock(side_effect=AssertionError('DB 연결 금지'))
    monkeypatch.setitem(sys.modules, 'app.core.db_connect', module)
    assert importer.main([str(path)]) == 0
    module.db_cursor.assert_not_called()


def test_import_apply_rollback_and_preview(tmp_path, monkeypatch):
    path = tmp_path / 'jobs.csv'
    write_csv(path, parse_listing(html([1])))
    cursor = Mock()
    events = []
    @contextmanager
    def db_cursor(commit=False):
        try:
            yield cursor
            events.append('commit' if commit else 'read_only')
        except Exception:
            events.append('rollback')
            raise
    module = types.ModuleType('app.core.db_connect')
    module.db_cursor = db_cursor
    monkeypatch.setitem(sys.modules, 'app.core.db_connect', module)
    assert importer.main([str(path), '--preview-db']) == 0
    assert cursor.execute.call_args_list[0].args == ('SET TRANSACTION READ ONLY',)
    cursor.execute.side_effect = RuntimeError('simulated INSERT failure')
    with pytest.raises(RuntimeError):
        importer.main([str(path), '--apply'])
    assert events == ['read_only', 'rollback']


def test_cli_exports_report_and_existing_file(tmp_path, monkeypatch):
    c = fake_crawler([html([1, 2])])
    monkeypatch.setattr(collector, 'load_crawler', lambda _: lambda **kw: c)
    path, report = tmp_path / 'jobs.csv', tmp_path / 'report.json'
    args = ['--permission-confirmed', '--user-agent', 'TestBot contact=test@example.com',
        '--target-count', '2', '--csv', str(path), '--report', str(report)]
    assert collector.main(args) == 0
    data = json.loads(report.read_text(encoding='utf-8'))
    assert data['target_reached'] and data['csv_rows'] == 2 and len(data['csv_sha256']) == 64
    with pytest.raises(SystemExit):
        collector.main(args)
    assert len(list(read_csv(path))) == 2


def test_cli_permission_gate(monkeypatch):
    factory = Mock()
    monkeypatch.setattr(collector, 'load_crawler', factory)
    with pytest.raises(SystemExit):
        collector.main([])
    factory.assert_not_called()


def test_cli_500_csv_count(tmp_path, monkeypatch):
    c = fake_crawler([html(range(1, 551))])
    monkeypatch.setattr(collector, 'load_crawler', lambda _: lambda **kw: c)
    path, report = tmp_path / '500.csv', tmp_path / 'report.json'
    assert collector.main(['--permission-confirmed', '--user-agent', 'TestBot contact=test@example.com',
        '--csv', str(path), '--report', str(report), '--target-count', '500']) == 0
    assert len(list(read_csv(path))) == 500
    data = json.loads(report.read_text(encoding='utf-8'))
    assert data['unique_count'] == data['csv_rows'] == 500 and data['target_reached']


def test_real_db_context_rolls_back_without_connection(monkeypatch):
    sys.path.insert(0, str(ROOT / 'backend'))
    from app.core import db_connect
    connection = Mock()
    connection.cursor.return_value.__enter__ = Mock(return_value=Mock())
    connection.cursor.return_value.__exit__ = Mock(return_value=False)
    lease = Mock(connection=connection)
    monkeypatch.setattr(db_connect, '_acquire_connection', lambda: lease)
    with pytest.raises(ValueError):
        with db_connect.db_cursor(commit=True):
            raise ValueError('simulated import error')
    connection.rollback.assert_called_once()
    connection.commit.assert_not_called()
    lease.release.assert_called_once()
