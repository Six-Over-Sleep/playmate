"""DB 없이 모임 XP 조건과 중복 범위 검증: python -m unittest tests/test_meetup_xp_policy.py"""
import unittest
from types import SimpleNamespace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from backend.app.services.meetup_xp_service import _identity, MEETUP_XP_RULES
from backend.app.domain.recruit_program import PolicyError


class MeetupXPPolicyTests(unittest.TestCase):
    def setUp(self):
        self.program = SimpleNamespace(
            recruit_id=42, category='study', lifecycle_status='IN_PROGRESS',
            leader_id=1, starts_at=datetime(2026, 10, 1, tzinfo=ZoneInfo('Asia/Seoul')),
            applications=[SimpleNamespace(member_id=1, status='ACCEPTED')],
        )
        self.activity = SimpleNamespace(
            recruit_id=42, author_member_id=1,
            created_at=datetime(2026, 10, 1, tzinfo=ZoneInfo('Asia/Seoul')),
            payload={'activity_type':'WEEKLY_CHECK', 'week':1, 'body':'주간 학습 인증 내용'},
        )

    def key(self, reward, week=None):
        return _identity(self.program, self.activity, 1, reward, week)

    def test_values(self):
        self.assertEqual(MEETUP_XP_RULES['PARTICIPATION'],10)
        self.assertEqual(MEETUP_XP_RULES['STUDY_WEEKLY'],15)
        self.assertEqual(MEETUP_XP_RULES['PROJECT_COMPLETE'],50)

    def test_week_scoped(self):
        self.assertEqual(self.key('STUDY_WEEKLY',1), self.key('STUDY_WEEKLY'))
        self.activity.payload['week'] = 2
        self.activity.created_at += timedelta(days=7)
        self.assertNotEqual(self.key('STUDY_WEEKLY',2), 'MEETUP:42:1:STUDY_WEEKLY:W1')
        with self.assertRaises(PolicyError):
            self.key('STUDY_WEEKLY',1)

    def test_participation_one_per_meetup(self):
        self.assertEqual(self.key('PARTICIPATION'), 'MEETUP:42:1:PARTICIPATION:ONCE')

    def test_participation_proof_is_valid(self):
        self.program.category='project'
        self.activity.payload={'activity_type':'PARTICIPATION_PROOF', 'body':'실제 참여 인증 자료'}
        self.assertTrue(self.key('PARTICIPATION').endswith('PARTICIPATION:ONCE'))

    def test_reject_other_member_activity(self):
        self.activity.author_member_id = 3
        with self.assertRaises(PolicyError): self.key('PARTICIPATION')

    def test_completion_not_automatic(self):
        with self.assertRaises(PolicyError): self.key('STUDY_COMPLETE')
        self.program.lifecycle_status = 'COMPLETED'
        self.assertEqual(self.key('STUDY_COMPLETE'), 'MEETUP:42:1:STUDY_COMPLETE:COMPLETE')

    def test_review_after_completion(self):
        self.activity.payload = {'activity_type':'REVIEW','body':'참여 후기'}
        with self.assertRaises(PolicyError): self.key('REVIEW')
        self.program.lifecycle_status = 'COMPLETED'
        self.assertTrue(self.key('REVIEW').endswith(':REVIEW:REVIEW'))

    def test_project_final_link_and_leader(self):
        self.program.category = 'project'
        self.program.lifecycle_status = 'COMPLETED'
        self.activity.payload = {'activity_type':'OUTPUT','submission_stage':'FINAL',
                                 'body':'프로젝트 최종 결과물', 'links':[]}
        with self.assertRaises(PolicyError): self.key('PROJECT_COMPLETE')
        self.activity.payload['links']=['https://github.com/test/project']
        self.assertTrue(self.key('PROJECT_COMPLETE').endswith(':PROJECT_COMPLETE:COMPLETE'))
        self.assertTrue(self.key('PROJECT_LEADER').endswith(':PROJECT_LEADER:LEADER'))
        self.program.leader_id = 2
        with self.assertRaises(PolicyError): self.key('PROJECT_LEADER')

    def test_interim_and_no_auto_complete(self):
        self.program.category = 'project'
        self.activity.payload = {'activity_type':'OUTPUT','submission_stage':'INTERIM',
                                 'body':'중간 결과물'}
        self.assertEqual(self.key('PROJECT_INTERIM'), 'MEETUP:42:1:PROJECT_INTERIM:INTERIM')
        with self.assertRaises(PolicyError): self.key('PROJECT_COMPLETE')

    def test_unsupported_award(self):
        with self.assertRaises(PolicyError): self.key('PROJECT_EXCELLENT')

if __name__ == '__main__': unittest.main()
