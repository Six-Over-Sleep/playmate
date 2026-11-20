"""Synthetic HTML only. Challenge/normal fixtures imitate structure; they are not saved site responses."""
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import types
from unittest.mock import Mock
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'database/scripts'))
sys.path.insert(0, str(ROOT / 'crawler'))
from itchaeyong_crawler.page_check import (classify_page, redact_html, NORMAL_PAGE, CHALLENGE_PAGE,
    UNKNOWN_PAGE)
from itchaeyong_crawler.crawler import ItchaeyongCrawler
from itchaeyong_csv import write_csv, read_csv
import collect_itchaeyong_jobs as collector
import import_itchaeyong_csv as importer
import diagnose_itchaeyong_html as diagnoser

ROBOTS = 'User-agent: *\nAllow: /\nDisallow: /api/\n'
PASSIVE_JSD = ('''<script>(function(){var d=document.createElement('script');d.innerHTML="window.__CF$cv$params='''
    '''{r:'8f1a2b3c',t:'MTczMjA5'};var a=document.createElement('script');a.nonce='';'''
    '''a.src='/cdn-cgi/challenge-platform/scripts/jsd/main.js';";})();</script>''')
CHALLENGE = '''<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title>
<meta http-equiv="refresh" content="390"></head><body><div class="main-wrapper" role="main">
<h1 class="zone-name-title h1">itchaeyong.com</h1>
<h2 id="challenge-running" class="h2">Checking if the site connection is secure</h2>
<noscript>Enable JavaScript and cookies to continue</noscript>
<form id="challenge-form" action="/jobs/dev?__cf_chl_f_tk=SECRETTOKEN" method="POST">
<input type="hidden" name="md" value="x"></form></div>
<script>(function(){window._cf_chl_opt={cvId: '3',cZone: "itchaeyong.com",cRay: 'SECRETRAY'};
var cpo=document.createElement('script');cpo.src='/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1?ray=SECRETRAYID';})();
</script></body></html>'''


def page(ids, next_page=None, extra='', title='개발 채용공고 | IT 채용 레이더'):
    cards = ''.join(f'''<article><a href="/companies/c{i}">합성 회사 {i}</a>
        <h3><a href="/jobs/job-{i}">합성 백엔드 공고 {i}</a></h3>
        <p>백엔드 · 경력 3년 이상 · 서울 · 정규직</p><p>기술 스택: Python, SQL</p></article>''' for i in ids)
    nav = f'<nav><a href="/jobs/dev?page={next_page}">다음</a></nav>' if next_page else ''
    return (f'<!DOCTYPE html><html><head><title>{title}</title></head><body><header><a href="/jobs/dev">개발</a>'
        f'</header><main>{cards}{nav}</main>{extra}</body></html>')


def response(text, status=200, content_type='text/html; charset=utf-8'):
    return types.SimpleNamespace(status_code=status, text=text,
        headers={'Content-Type': content_type, 'Set-Cookie': '__cf_bm=SECRETCOOKIE'})


def live_crawler(bodies, monkeypatch, **kwargs):
    """Runs the real request()/classification path with a fake session."""
    monkeypatch.setattr('itchaeyong_crawler.crawler.time.sleep', lambda _: None)
    session = Mock(headers={})
    session.get.side_effect = [response(ROBOTS, content_type='text/plain')] + [
        b if isinstance(b, types.SimpleNamespace) else response(b) for b in bodies]
    return ItchaeyongCrawler('TestBot contact=test@example.com', session=session, **kwargs), session


def test_normal_page_classified_by_links():
    check = classify_page(page([1, 2, 2]))
    assert check['verdict'] == NORMAL_PAGE and check['job_link_count'] == 2
    assert check['title'] == '개발 채용공고 | IT 채용 레이더' and check['challenge_evidence'] == []


def test_challenge_strings_in_comment_and_passive_script_are_not_a_block():
    noisy = page([1], extra='<!-- cf-chl- /cdn-cgi/challenge <title>Just a moment</title> -->' + PASSIVE_JSD)
    check = classify_page(noisy)
    assert check['verdict'] == NORMAL_PAGE and check['challenge_evidence'] == []
    assert check['passive_evidence'] == ['script:passive cdn-cgi jsd']


def test_real_challenge_structure():
    check = classify_page(CHALLENGE)
    assert check['verdict'] == CHALLENGE_PAGE and check['job_link_count'] == 0
    assert {'title:Just a moment...', 'id:challenge-running', 'id:challenge-form',
        'form:__cf_chl action', 'script:challenge-platform orchestrate'} <= set(check['challenge_evidence'])


@pytest.mark.parametrize('html', ['', '<html><body><main><p>점검 중입니다</p></main></body></html>',
    '<html><head><title>IT 채용 레이더</title></head><body><div id="__next"></div></body></html>'])
def test_undeterminable_page_is_unknown(html):
    assert classify_page(html)['verdict'] == UNKNOWN_PAGE


def test_title_is_read_from_title_element_only():
    body_text = page([1]).replace('<main>', '<main><h1>Just a moment... 잠시 후 마감되는 공고</h1>')
    assert classify_page(body_text)['verdict'] == NORMAL_PAGE
    assert classify_page('<html><head><title>Attention Required! | Cloudflare</title></head>'
        '<body><div id="cf-wrapper"></div></body></html>')['verdict'] == CHALLENGE_PAGE
    # Conflicting signals are not resolved by guessing.
    assert classify_page(page([1], title='Just a moment...'))['verdict'] == UNKNOWN_PAGE


def test_job_link_extraction_rules():
    html = ('<main><a href="/jobs/abc_1">a</a><a href="https://itchaeyong.com/jobs/abc_1/">dup</a>'
        '<a href="/jobs/dev">list</a><a href="/jobs/dev?page=2">p2</a><a href="https://evil.example/jobs/x">x</a>'
        '<a href="/api/jobs">api</a><a href="/jobs/zz-9">b</a></main>')
    assert classify_page(html)['job_link_count'] == 2


def test_detail_page_kinds():
    detail = '<html><head><title>합성 공고</title></head><body><main><h1>합성 공고</h1></main></body></html>'
    assert classify_page(detail, 'detail')['verdict'] == NORMAL_PAGE
    assert classify_page(CHALLENGE, 'detail')['verdict'] == CHALLENGE_PAGE
    assert classify_page('<html><body></body></html>', 'detail')['verdict'] == UNKNOWN_PAGE


def test_crawl_normal_page_with_noise_collects_and_paginates(monkeypatch):
    noisy = PASSIVE_JSD + '<!-- /cdn-cgi/challenge -->'
    c, session = live_crawler([page([1, 2], 2, noisy), page([2, 3], extra=noisy)], monkeypatch)
    rows = c.crawl(target_count=5, details=False)
    assert [r['source_job_id'] for r in rows] == ['job-1', 'job-2', 'job-3']
    assert session.get.call_args_list[2].args == ('https://itchaeyong.com/jobs/dev?page=2',)
    assert c.report['duplicate_count'] == 1 and c.report['stop_reason'] == 'last_page'
    assert [p['page_verdict'] for p in c.report['pages']] == [NORMAL_PAGE, NORMAL_PAGE]
    assert not any(t['challenge_html'] for t in c.report['http_responses'])


def test_crawl_real_challenge_stops_without_parsing(monkeypatch):
    c, session = live_crawler([CHALLENGE], monkeypatch)
    assert c.crawl(details=False) == []
    assert c.report['status'] == 'stopped' and 'CHALLENGE_PAGE' in c.report['stop_reason']
    assert c.report['pages'] == [] and session.get.call_count == 2
    trace = c.report['http_responses'][1]
    assert trace['page_verdict'] == CHALLENGE_PAGE and trace['html_title'] == 'Just a moment...'
    assert 'SECRET' not in json.dumps(c.report)


def test_crawl_unknown_and_parser_mismatch_are_not_success(monkeypatch):
    c, _ = live_crawler(['<html><body><main><p>점검</p></main></body></html>'], monkeypatch)
    c.crawl(details=False)
    assert c.report['status'] == 'stopped' and c.report['stop_reason'].startswith('UNKNOWN_PAGE')
    assert 'challenge' not in c.report['stop_reason']
    flat = '<html><body><main><div><a href="/jobs/x1">카드</a></div></main></body></html>'
    c, _ = live_crawler([flat], monkeypatch)
    c.crawl(details=False)
    assert c.report['stop_reason'] == '파서 불일치: 공고 링크 1개, 추출 0건'


def test_unverified_detail_keeps_listing_row(monkeypatch):
    c, _ = live_crawler([page([1]), '<html><body></body></html>'], monkeypatch)
    rows = c.crawl(target_count=1)
    assert len(rows) == 1 and rows[0]['detail_status'] == 'unverified_page'
    assert rows[0]['company_name'] == '합성 회사 1'


def test_debug_html_is_redacted_and_reused_offline(tmp_path, monkeypatch):
    c, _ = live_crawler([CHALLENGE], monkeypatch, debug_dir=tmp_path / 'debug')
    c.crawl(details=False)
    saved = sorted((tmp_path / 'debug').glob('*.html'))
    assert [p.name for p in saved] == ['001_robots_txt_200.html', '002_jobs_dev_200.html']
    text = saved[1].read_text(encoding='utf-8')
    assert 'SECRET' not in text and 'Just a moment' in text
    monkeypatch.setattr(diagnoser, 'DEBUG_DIR', tmp_path / 'debug')
    monkeypatch.setattr(diagnoser, 'ROOT', tmp_path)
    monkeypatch.setattr(diagnoser, 'ItchaeyongCrawler', Mock(side_effect=AssertionError('network forbidden')))
    assert diagnoser.main([]) == 2
    report = json.loads(next((tmp_path / 'data/itchaeyong/reports').glob('*.json')).read_text(encoding='utf-8'))
    assert report['network_requests_made'] == 0 and report['page']['verdict'] == CHALLENGE_PAGE
    assert report['page']['parser_executed'] is False
    normal = tmp_path / 'debug' / '003_jobs_dev_200.html'
    normal.write_text(page([1, 2], 2, PASSIVE_JSD), encoding='utf-8')
    assert diagnoser.main(['--html', str(normal)]) == 0
    assert redact_html(PASSIVE_JSD).count('8f1a2b3c') == 0


def test_diagnose_without_saved_html_does_not_fetch(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(diagnoser, 'DEBUG_DIR', tmp_path / 'none')
    monkeypatch.setattr(diagnoser, 'ItchaeyongCrawler', Mock(side_effect=AssertionError('network forbidden')))
    assert diagnoser.main([]) == 1
    assert '저장된 디버그 HTML 없음' in capsys.readouterr().out
    with pytest.raises(SystemExit):
        diagnoser.main(['--fetch'])


def test_cli_zero_rows_reports_failure_not_saved(tmp_path, monkeypatch, capsys):
    c, _ = live_crawler([CHALLENGE], monkeypatch)
    monkeypatch.setattr(collector, 'ItchaeyongCrawler', lambda **_: c)
    path, report = tmp_path / 'itchaeyong_jobs_x.csv', tmp_path / 'report.json'
    code = collector.main(['--permission-confirmed', '--user-agent', 'TestBot', '--target-count', '1',
        '--list-only', '--csv', str(path), '--report', str(report)])
    out = capsys.readouterr().out
    assert code == 2 and '수집 실패: 실제 채용공고 0건' in out and 'CSV 데이터 없음' in out
    assert '실패 원인: 접근 제한 challenge HTML' in out and 'CSV 저장 완료' not in out
    assert not path.exists() and (tmp_path / 'itchaeyong_EMPTY_x.csv').exists()
    data = json.loads(report.read_text(encoding='utf-8'))
    assert data['csv_kind'] == 'empty_diagnostic' and data['csv_rows'] == 0


@pytest.mark.parametrize('flags', [[], ['--preview-db'], ['--apply']])
def test_zero_row_csv_never_reaches_db(tmp_path, monkeypatch, flags):
    path = tmp_path / 'empty.csv'
    write_csv(path, [])
    assert list(read_csv(path)) == []
    module = types.ModuleType('app.core.db_connect')
    module.db_cursor = Mock(side_effect=AssertionError('DB access forbidden'))
    monkeypatch.setitem(sys.modules, 'app.core.db_connect', module)
    assert importer.main([str(path), *flags]) == 2
    module.db_cursor.assert_not_called()
