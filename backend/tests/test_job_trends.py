import copy
from collections import Counter
from contextlib import contextmanager
from datetime import timedelta, timezone
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from database.scripts.generate_job_trends_mock import generate, QUARTERS
from app.services import job_trends_service as service
from app.services.job_trends_catalog import FIELDS, ROLES


def test_sample_and_official_shape():
    payload = generate(sample=True)
    fixture = json.loads((ROOT / 'database/fixtures/job_trends_sample.json').read_text(encoding='utf-8'))
    assert payload == fixture
    rows, report = service.parse_response(payload, 'mock')
    assert len(rows) == 5 and report.failed == 0
    assert rows[0]['salary_code'] is None
    assert rows[1]['keyword_text'] is None
    assert rows[3]['company_name'] is None
    assert rows[2]['job_code'] == '84,235'
    assert rows[0]['salary_min_manwon'] is None
    assert set(service.classify_roles(rows[4])) == {'llm_engineer', 'ai_agent_developer'}
    assert 'requirements_text' not in rows[0]['raw_payload']


def test_catalog():
    assert len(FIELDS) == len({code for code, _ in FIELDS}) == 8
    assert len(ROLES) == len({code for _, code, _ in ROLES}) == 30
    assert Counter(field for field, _, _ in ROLES) == {code: 9 if code == 'data_ai' else 3 for code, _ in FIELDS}


def test_full_deterministic_quarters():
    assert generate() == generate()
    rows, report = service.parse_response(generate(), 'mock')
    assert len(rows) == len({row['source_job_id'] for row in rows}) == 467
    assert report.failed == 0
    counts = Counter()
    for row in rows:
        posted = row['posted_at'].astimezone(timezone(timedelta(hours=9)))
        counts[f'{posted.year}-Q{(posted.month - 1) // 3 + 1}'] += 1
    assert counts == QUARTERS


@pytest.mark.parametrize('job', [{'id': '1'}, {'id': 1, 'company': None, 'position': None, 'salary': None}])
def test_missing_nested_fields(job):
    row = service.normalize_job(job, 'saramin')
    assert row['source_job_id'] == '1'
    assert row['title'] is row['is_active'] is row['posted_at'] is None


@pytest.mark.parametrize('payload', [{'code': 2, 'message': 'invalid'}, {'result': {'code': 2}}, {}, {'jobs': {'job': []}}])
def test_error_response(payload):
    with pytest.raises(service.SaraminResponseError):
        service.parse_response(payload, 'mock')


def test_duplicate_invalid_empty():
    payload = generate(sample=True)
    payload['jobs']['job'].extend([copy.deepcopy(payload['jobs']['job'][0]), {}, {'id': 'bad', 'active': 9}])
    payload['jobs']['count'] = payload['jobs']['total'] = 8
    rows, report = service.parse_response(payload, 'mock')
    assert len(rows) == 5
    assert (report.duplicate, report.skipped, report.failed) == (1, 1, 2)
    assert service.load_response({'jobs': {'count': 0, 'start': 0, 'total': '0', 'job': []}}, 'mock').success == 0


def test_keyword_provenance_and_no_substring():
    row = service.normalize_job({'id': '1', 'keyword': 'JavaScript, Python', 'position': {'title': 'Java 개발자'}}, 'mock')
    assert service.keyword_mentions(row, [('java', 'Java'), ('python', 'Python')]) == [('java', 'title'), ('python', 'api_keyword')]
    assert service.classify_roles(service.normalize_job({'id': '2', 'position': {'title': 'AI 서비스 채용'}}, 'mock')) == []


def test_load_commit_and_failure_report(monkeypatch):
    events = []
    @contextmanager
    def cursor(**kwargs):
        assert kwargs == {'commit': True}
        try:
            yield object()
            events.append('commit')
        except Exception:
            events.append('rollback')
            raise
    monkeypatch.setattr(service, 'db_cursor', cursor)
    monkeypatch.setattr(service.repository, 'save_postings', lambda cursor, rows: (2, 3))
    report = service.load_response(generate(sample=True), 'mock')
    assert (report.success, report.duplicate) == (5, 3)
    def fail(cursor, rows):
        raise RuntimeError('db failure')
    monkeypatch.setattr(service.repository, 'save_postings', fail)
    with pytest.raises(service.JobTrendsLoadError) as caught:
        service.load_response(generate(sample=True), 'mock')
    assert caught.value.report.failed == 5 and caught.value.report.success == 0
    assert events == ['commit', 'rollback']
