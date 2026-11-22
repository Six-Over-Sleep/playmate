"""HTTP validation must reject DB-overflow payloads before touching a stored meetup."""
import pytest
from backend.tests.recruit.test_runtime_api import runtime, json_payload


@pytest.mark.parametrize('field,valid,invalid', [
    ('title', '가' * 100, '가' * 101),
    ('sport_name', '가' * 100, '가' * 101),
    ('place', '가' * 255, '가' * 256),
    ('capacity', 2147483647, 2147483648),
])
def test_legacy_overflow_is_422_and_does_not_change_data(runtime, payload, field, valid, invalid):
    body = dict(title='E2E-TEST', body='소개', category='sports', recruit_mode='short',
                capacity=5, sport_name='러닝', place='테스트 장소',
                deadline_at=payload['starts_at'].isoformat(),
                meeting_start=payload['starts_at'].isoformat(), meeting_end=payload['ends_at'].isoformat())
    rejected = runtime.request('POST', '/api/recruits', json={**body, field: invalid}, member=1)
    assert rejected.status_code == 422
    assert runtime.request('GET', '/api/recruits', member=1).json() == []
    created = runtime.request('POST', '/api/recruits', json={**body, field: valid}, member=1)
    assert created.status_code == 201, created.text
    rid = created.json()['recruit_id']
    before = runtime.request('GET', f'/api/recruits/{rid}', member=1).json()
    rejected = runtime.request('PATCH', f'/api/recruits/{rid}', json={field: invalid}, member=1)
    assert rejected.status_code == 422
    assert runtime.request('GET', f'/api/recruits/{rid}', member=1).json() == before


def test_capabilities_auth_feature_off_and_ready(runtime, monkeypatch):
    assert runtime.request('GET', '/api/recruits/capabilities').status_code == 401
    monkeypatch.setenv('ENABLE_RECRUIT_PROGRAMS', 'false')
    assert runtime.request('GET', '/api/recruits/capabilities', member=1).json() == {
        'programs_enabled': False, 'programs_available': False, 'reason': 'disabled',
    }
    monkeypatch.setenv('ENABLE_RECRUIT_PROGRAMS', 'true')
    assert runtime.request('GET', '/api/recruits/capabilities', member=1).json()['programs_available'] is True


def test_program_title_limit_is_not_a_database_error(runtime, payload):
    rejected = runtime.request('POST', '/api/recruits', json={**json_payload(payload), 'title': '가' * 101}, member=1)
    assert rejected.status_code == 422
    assert runtime.request('GET', '/api/recruits', member=1).json() == []
