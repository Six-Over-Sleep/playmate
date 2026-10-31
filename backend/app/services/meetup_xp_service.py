"""프로젝트/스터디 개인별 XP 지급·회수 (실제 활동 증빙 + 관리자 확인).

기존 종합 XP 원장(member_xp_history)만 사용한다. 별도 XP 잔액 테이블을 만들지 않는다.
프로그램 신청이나 활동 제출만으로는 지급하지 않으며, 각 회원의 증빙을 검토한 후 승인한다.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from backend.app.domain.recruit_program import PolicyError
from backend.app.models.recruit_program import RecognitionRecord
from backend.app.services.xp_service import calculate_level

KST = ZoneInfo('Asia/Seoul')

# 공식 2.3 기준. 우수 프로젝트는 선정 기준 미정으로 자동 지급하지 않는다.
MEETUP_XP_RULES = {
    'PARTICIPATION': 10,
    'STUDY_WEEKLY': 15,
    'PROJECT_INTERIM': 15,
    'STUDY_COMPLETE': 30,
    'PROJECT_COMPLETE': 50,
    'REVIEW': 10,
    'PROJECT_LEADER': 20,
}


def _identity(program, activity, member_id, reward_type, week=None):
    """스코프별 중복방지 키를 만들며 인원·증빙·종료 조건을 확인한다."""
    if reward_type not in MEETUP_XP_RULES:
        raise PolicyError('지원하지 않거나 선정 기준이 확정되지 않은 모임 보상입니다.', 422)

    application = next(
        (a for a in program.applications if a.member_id == member_id
         and a.status in {'ACCEPTED', 'LEFT'}), None,
    )
    if application is None:
        raise PolicyError('해당 모임의 확정 참여 이력이 없습니다.', 403)
    if activity is None or activity.recruit_id != program.recruit_id:
        raise PolicyError('해당 모임의 활동 기록이 없습니다.', 404)
    if activity.author_member_id != member_id:
        raise PolicyError('다른 회원의 활동 기록으로 개인 XP를 받을 수 없습니다.', 422)

    data = activity.payload or {}
    kind = data.get('activity_type')
    stage = data.get('submission_stage')
    current_week = data.get('week')
    # 사진 업로드 미연결 상태: 제출된 텍스트/URL을 검토자가 실제 증빙과 대조한다.
    if not str(data.get('body') or '').strip():
        raise PolicyError('활동 내용이 없으므로 확인할 수 없습니다.', 422)

    completed = program.lifecycle_status == 'COMPLETED'
    actively_completed = application.status == 'ACCEPTED'
    if reward_type == 'PARTICIPATION':
        is_valid = kind == 'PARTICIPATION_PROOF' or (
            program.category == 'study' and kind == 'WEEKLY_CHECK'
        ) or (
            program.category == 'project' and kind == 'OUTPUT'
            and stage in {'INTERIM', 'FINAL'}
        )
        if not is_valid:
            raise PolicyError('실제 참여를 확인할 개인 인증, 주간 인증 또는 결과물이 필요합니다.', 422)
        scope = 'ONCE'

    elif reward_type == 'STUDY_WEEKLY':
        if program.category != 'study' or kind != 'WEEKLY_CHECK':
            raise PolicyError('스터디 주간 인증 기록만 인정할 수 있습니다.', 422)
        if not isinstance(current_week, int) or current_week < 1:
            raise PolicyError('인증 주차가 올바르지 않습니다.', 422)
        if week is not None and week != current_week:
            raise PolicyError('활동 기록의 주차와 요청한 주차가 다릅니다.', 422)
        # 시작일 기준 7일을 한 주차로 계산해 임의의 높은 주차로 중복 보상을 받지 못하게 한다.
        created = activity.created_at
        if created is None or created.tzinfo is None:
            raise PolicyError('서버에 기록된 인증 날짜가 필요합니다.', 422)
        start_day = program.starts_at.astimezone(KST).date()
        created_day = created.astimezone(KST).date()
        actual_week = (created_day - start_day).days // 7 + 1
        if actual_week < 1 or current_week != actual_week:
            raise PolicyError('활동 날짜와 제출된 인증 주차가 일치하지 않습니다.', 422)
        scope = f'W{current_week}'

    elif reward_type == 'PROJECT_INTERIM':
        if program.category != 'project' or kind != 'OUTPUT' or stage != 'INTERIM':
            raise PolicyError('프로젝트 중간 결과물 기록이 필요합니다.', 422)
        scope = 'INTERIM'

    elif reward_type == 'STUDY_COMPLETE':
        if program.category != 'study' or not completed or not actively_completed:
            raise PolicyError('정상 종료된 스터디의 확정 참여자만 받을 수 있습니다.', 422)
        if kind != 'WEEKLY_CHECK':
            raise PolicyError('해당 회원의 스터디 활동 기록이 필요합니다.', 422)
        scope = 'COMPLETE'

    elif reward_type in {'PROJECT_COMPLETE', 'PROJECT_LEADER'}:
        if program.category != 'project' or not completed or not actively_completed:
            raise PolicyError('정상 종료된 프로젝트의 확정 참여자만 받을 수 있습니다.', 422)
        if kind != 'OUTPUT' or stage != 'FINAL':
            raise PolicyError('해당 회원의 최종 결과물 제출 기록이 필요합니다.', 422)
        # 최종 결과물은 GitHub/발표 자료/시연 자료 등 확인 가능한 링크 필요.
        if not data.get('links'):
            raise PolicyError('프로젝트 완료 보상에는 최종 결과물 링크가 필요합니다.', 422)
        if reward_type == 'PROJECT_LEADER' and program.leader_id != member_id:
            raise PolicyError('선정된 프로젝트 팀장만 팀장 보상을 받을 수 있습니다.', 403)
        scope = 'COMPLETE' if reward_type == 'PROJECT_COMPLETE' else 'LEADER'

    elif reward_type == 'REVIEW':
        if not completed or not actively_completed or kind != 'REVIEW':
            raise PolicyError('정상 종료된 모임의 확정 참여자가 작성한 후기만 인정됩니다.', 422)
        scope = 'REVIEW'

    else:
        raise PolicyError('보상 유형이 올바르지 않습니다.', 422)

    # 주차 이외의 입력 주차는 인정하지 않아 동일 범위를 다른 키로 만드는 우회를 막는다.
    if reward_type != 'STUDY_WEEKLY' and week is not None:
        raise PolicyError('해당 보상에는 주차를 지정할 수 없습니다.', 422)
    key = f'MEETUP:{program.recruit_id}:{member_id}:{reward_type}:{scope}'
    return key


class MeetupXPService:
    """XP + 인정 기록을 동일 DB 트랜잭션에서 갱신한다."""

    def __init__(self, program_service):
        self.program_service = program_service
        self.repository = program_service.repository
        self.session = self.repository.session

    def approve(self, reviewer_id, recruit_id, activity_id, member_id, reward_type, week=None):
        if any(not isinstance(v, int) or isinstance(v, bool) or v <= 0
               for v in (reviewer_id, recruit_id, activity_id, member_id)):
            raise PolicyError('유효한 ID가 필요합니다.', 422)
        with self.program_service.transaction():
            if not self.repository.actor(reviewer_id, lock=True):
                raise PolicyError('관리자만 모임 활동 증빙을 검토할 수 있습니다.', 403)
            if reviewer_id == member_id:
                raise PolicyError('관리자는 자신의 활동에 XP를 직접 승인할 수 없습니다.', 403)
            program = self.repository.load(recruit_id, lock=True)
            self.repository.actor(member_id)
            activity = self.repository.activity(activity_id)
            event_key = _identity(program, activity, member_id, reward_type, week)
            recognition_key = f'xp:{event_key}'
            previous = self.repository.recognition(recognition_key)
            if previous is not None:
                return {
                    'awarded': False,
                    'reason': 'REVOKED' if previous.payload.get('status') == 'INVALIDATED' else 'DUPLICATE',
                    'event_key': event_key,
                }

            xp = MEETUP_XP_RULES[reward_type]
            self.session.execute(text("""
                INSERT INTO member_levels (member_id) VALUES (:member_id)
                ON CONFLICT (member_id) DO NOTHING
            """), {'member_id': member_id})
            total = self.session.execute(text("""
                SELECT total_xp FROM member_levels
                WHERE member_id = :member_id FOR UPDATE
            """), {'member_id': member_id}).scalar_one()

            # 회원+활동범위 UNIQUE로 동시 승인·재요청을 모두 차단한다.
            created = self.session.execute(text("""
                INSERT INTO member_xp_history
                  (member_id, activity_type, source_type, source_id,
                   event_key, xp_change, activity_date)
                VALUES (:member_id, :reward_type, 'RECRUIT', :recruit_id,
                        :event_key, :xp, :today)
                ON CONFLICT (member_id, event_key) DO NOTHING
                RETURNING history_id
            """), {
                'member_id': member_id, 'reward_type': f'MEETUP_{reward_type}',
                'recruit_id': recruit_id, 'event_key': event_key,
                'xp': xp, 'today': datetime.now(KST).date(),
            }).scalar_one_or_none()
            if created is None:
                return {'awarded': False, 'reason': 'DUPLICATE', 'event_key': event_key}

            new_total = int(total) + xp
            self.session.execute(text("""
                UPDATE member_levels
                SET total_xp = :xp, level = :level,
                    updated_at = CURRENT_TIMESTAMP
                WHERE member_id = :member_id
            """), {'member_id': member_id, 'xp': new_total,
                   'level': calculate_level(new_total)})
            self.repository.save_recognition(
                recognition_key, recruit_id, member_id, activity_id,
                {
                    'recognition_key': recognition_key,
                    'reward_type': reward_type, 'event_key': event_key,
                    'status': 'APPROVED', 'reward_status': 'GRANTED',
                    'reviewer_member_id': reviewer_id, 'xp_change': xp,
                    'scope_week': week if reward_type == 'STUDY_WEEKLY' else None,
                    'approved_at': datetime.now(KST).isoformat(),
                }
            )
            return {
                'awarded': True, 'earned_xp': xp, 'event_key': event_key,
                'total_xp': new_total, 'level': calculate_level(new_total),
            }

    def revoke(self, reviewer_id, recruit_id, member_id, reward_type, reason, week=None):
        if any(not isinstance(v, int) or isinstance(v, bool) or v <= 0
               for v in (reviewer_id, recruit_id, member_id)):
            raise PolicyError('유효한 ID가 필요합니다.', 422)
        if not reason or not reason.strip():
            raise PolicyError('XP 회수 사유가 필요합니다.', 422)
        with self.program_service.transaction():
            if not self.repository.actor(reviewer_id, lock=True):
                raise PolicyError('관리자만 모임 XP를 회수할 수 있습니다.', 403)
            if reviewer_id == member_id:
                raise PolicyError('관리자는 자신의 XP를 직접 회수할 수 없습니다.', 403)
            program = self.repository.load(recruit_id, lock=True)
            # 회수에서는 현재 상태가 아닌 과거 승인 기록을 기준으로 검증한다.
            scope = (f'W{week}' if reward_type == 'STUDY_WEEKLY'
                     and isinstance(week, int) and week >= 1
                     else {'PARTICIPATION': 'ONCE', 'PROJECT_INTERIM': 'INTERIM',
                           'STUDY_COMPLETE': 'COMPLETE', 'PROJECT_COMPLETE': 'COMPLETE',
                           'REVIEW': 'REVIEW', 'PROJECT_LEADER': 'LEADER'}.get(reward_type))
            if reward_type not in MEETUP_XP_RULES or scope is None:
                raise PolicyError('회수 대상 XP 유형 또는 주차가 올바르지 않습니다.', 422)
            if reward_type != 'STUDY_WEEKLY' and week is not None:
                raise PolicyError('해당 보상에는 주차를 지정할 수 없습니다.', 422)
            event_key = f'MEETUP:{program.recruit_id}:{member_id}:{reward_type}:{scope}'
            rec = self.repository.recognition(f'xp:{event_key}')
            if rec is None:
                raise PolicyError('해당 모임 보상 지급 내역이 없습니다.', 404)
            if rec.member_id != member_id:
                raise PolicyError('지급 대상자가 일치하지 않습니다.', 422)
            if rec.payload.get('status') == 'INVALIDATED':
                return {'revoked': False, 'reason': 'ALREADY_REVOKED'}
            self.session.execute(text("""
                INSERT INTO member_levels (member_id) VALUES (:member_id)
                ON CONFLICT (member_id) DO NOTHING
            """), {'member_id': member_id})
            total = int(self.session.execute(text("""
                SELECT total_xp FROM member_levels
                WHERE member_id = :member_id FOR UPDATE
            """), {'member_id': member_id}).scalar_one())
            xp = self.session.execute(text("""
                SELECT xp_change FROM member_xp_history
                WHERE member_id = :member_id AND event_key = :event_key
            """), {'member_id': member_id, 'event_key': event_key}).scalar_one_or_none()
            if xp is None or int(xp) <= 0:
                raise PolicyError('원 지급 내역을 확인할 수 없습니다.', 409)
            xp = int(xp)
            new_total = total - xp
            if new_total < 0:
                raise PolicyError('잔여 XP가 부족해 회수할 수 없습니다. 원장 점검이 필요합니다.', 409)
            revoke_key = f'REVOKE:{event_key}'
            created = self.session.execute(text("""
                INSERT INTO member_xp_history
                  (member_id, activity_type, source_type, source_id,
                   event_key, xp_change, activity_date)
                VALUES (:member_id, 'REVOKE', 'RECRUIT', :recruit_id,
                        :revoke_key, :negative_xp, :today)
                ON CONFLICT (member_id, event_key) DO NOTHING
                RETURNING history_id
            """), {
                'member_id': member_id, 'recruit_id': recruit_id,
                'revoke_key': revoke_key, 'negative_xp': -xp,
                'today': datetime.now(KST).date(),
            }).scalar_one_or_none()
            if created is None:
                return {'revoked': False, 'reason': 'ALREADY_REVOKED'}
            self.session.execute(text("""
                UPDATE member_levels
                SET total_xp = :xp, level = :level,
                    updated_at = CURRENT_TIMESTAMP
                WHERE member_id = :member_id
            """), {'member_id': member_id, 'xp': new_total,
                   'level': calculate_level(new_total)})
            rec.payload = {
                **rec.payload, 'status': 'INVALIDATED', 'reward_status': 'REVOKED',
                'revoked_by_member_id': reviewer_id, 'revoke_reason': reason.strip(),
                'revoked_at': datetime.now(KST).isoformat(),
            }
            return {'revoked': True, 'xp_change': -xp,
                    'total_xp': new_total, 'level': calculate_level(new_total)}
