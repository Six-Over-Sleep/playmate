"""Issue #88: isolated persistence, profile and write authorization regressions."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import event

from backend.app.domain.recruit_program import PolicyError
from backend.app.models.member import Member
from backend.app.models.recruit import Recruit
from backend.app.models.recruit_program import RecruitSkill
from backend.app.repositories import recruit as legacy_repo
from backend.app.schemas.recruit_program import ProgramCreate, ProgramEdit
from backend.app.services.recruit_dispatch_service import RecruitDispatchService
from backend.app.services.recruit_skill_catalog import DatabaseSkillCatalog


def test_regular_study_has_schedule_before_first_insert_and_round_trips(service, payload):
    start = service.clock() + timedelta(days=7, hours=10)
    local = start.astimezone(timezone(timedelta(hours=9)))
    data = {**payload, 'recruit_mode': 'regular', 'starts_at': start, 'ends_at': start + timedelta(days=28),
            'deadline_at': start - timedelta(hours=24), 'meeting_start': None, 'meeting_end': None,
            'regular_days': [['월','화','수','목','금','토','일'][local.weekday()]],
            'regular_time': local.time().replace(tzinfo=None), 'regular_start_date': local.date()}
    seen = []
    def before_insert(mapper, connection, target):
        seen.append((target.regular_days, target.regular_time, target.regular_start_date))
    event.listen(Recruit, 'before_insert', before_insert)
    try:
        created = service.create(1, ProgramCreate(**data))
    finally:
        event.remove(Recruit, 'before_insert', before_insert)
    assert all(seen[0])
    detail = service.detail(created['recruit_id'], 1)
    assert detail['regular_days'] == data['regular_days']
    assert detail['regular_start_date'] == local.date().isoformat()
    service.edit(created['recruit_id'], 1, ProgramEdit(title='정기 스터디 수정', starts_at=start+timedelta(days=7), ends_at=start+timedelta(days=35)))
    updated = service.detail(created['recruit_id'], 1)
    assert updated['title'] == '정기 스터디 수정'
    assert updated['regular_start_date'] == (local + timedelta(days=7)).date().isoformat()


def test_profiles_are_public_fields_in_both_member_views(service, payload):
    member = service.repository.session.get(Member, 1)
    member.nickname = '실제 닉네임'
    member.profile_image_url = 'https://cdn.discordapp.com/avatars/1/example.png'
    service.repository.session.commit()
    created = service.create(1, ProgramCreate(**payload))
    detail = service.detail(created['recruit_id'], 1)
    members = service.members(created['recruit_id'], 1)
    assert detail['members'][0]['display_name'] == '실제 닉네임'
    assert members[0]['profile_image_url'] == member.profile_image_url
    assert legacy_repo.member_profiles(service.repository.session, [1])[1]['profile_image_url'] == member.profile_image_url


def test_database_catalog_uses_persisted_ids_and_rejects_unknown_and_duplicate(service):
    session = service.repository.session
    RecruitSkill.__table__.create(session.get_bind(), checkfirst=True)
    session.add(RecruitSkill(skill_id=700, skill_code='SQL', name='SQL'))
    session.commit()
    catalog = DatabaseSkillCatalog(session)
    assert catalog.options() == [{'skill_id': 700, 'skill_code': 'SQL', 'name': 'SQL'}]
    catalog.validate([700])
    assert catalog.names([700]) == {'700': 'SQL'}
    for invalid in ([999], [700,700]):
        with pytest.raises(PolicyError): catalog.validate(invalid)


@pytest.mark.parametrize('actor', [None, 2])
def test_legacy_delete_and_edit_reject_non_owner(service, monkeypatch, actor):
    monkeypatch.setattr(legacy_repo, 'find_recruit_with_post', lambda *args: (SimpleNamespace(author_member_id=1), SimpleNamespace()))
    monkeypatch.setattr(service.repository, 'is_program', lambda rid: False)
    def current():
        if actor is None: raise PolicyError('로그인이 필요합니다.', 401)
        return actor
    dispatch = RecruitDispatchService(service, True, current, lambda: actor, current, lambda: actor)
    with pytest.raises(PolicyError) as error: dispatch.delete(7)
    assert error.value.status == (401 if actor is None else 403)
    with pytest.raises(PolicyError): dispatch.update(7, {'title': '변조'})


def test_legacy_group_buy_has_no_meeting_dates_and_regular_timezone_normalizes():
    from backend.app.schemas.recruit import RecruitCreate
    group = RecruitCreate(title='공동구매', body='책 구입', category='group_buy', recruit_mode='short', capacity=3, deadline_at='2030-01-01T19:00:00+09:00')
    assert group.meeting_start is None
    regular = RecruitCreate(title='게임', body='체스', category='game', recruit_mode='regular', capacity=3,
                            regular_days=['월'], regular_time='19:00', regular_start_date='2030-01-07',
                            deadline_at='2030-01-06T10:00:00Z')
    assert regular.deadline_at == datetime(2030, 1, 6, 19)
