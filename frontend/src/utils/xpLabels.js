const LABELS = {
  ATTEND: '일일 출석',
  ATTEND_7: '7일 연속 출석',
  ATTEND_30: '30일 연속 출석',
  ATTEND_STREAK_7: '7일 연속 출석',
  ATTEND_STREAK_30: '30일 연속 출석',
  // 백엔드가 실제로 기록하는 연속 출석·가이드·회수 유형
  STREAK_7: '7일 연속 출석 보너스',
  STREAK_30: '30일 연속 출석 보너스',
  CAREER_GUIDE: '커리어 가이드 작성',
  REVOKE: 'XP 회수',
  POST: '게시글 작성',
  COMMENT: '댓글 작성',
  REPLY: '대댓글 작성',
  POST_LIKE: '게시글 좋아요 받음',
  CAREER_DOCUMENT: '취업 서류 후기',
  CAREER_INTERVIEW: '면접 후기',
  CAREER_SUCCESS: '취업 성공 후기',
  CAREER_ADJUST: '취업 후기 XP 정산',
  CAREER_SPEC_PUBLIC: '취업 스펙 최초 공개',
  MEETUP_PARTICIPATION: '모임 참여 인증',
  MEETUP_STUDY_WEEKLY: '스터디 주간 인증',
  MEETUP_PROJECT_INTERIM: '프로젝트 중간 결과물',
  MEETUP_STUDY_COMPLETE: '스터디 완료',
  MEETUP_PROJECT_COMPLETE: '프로젝트 완료',
  MEETUP_REVIEW: '모임 후기',
  MEETUP_PROJECT_LEADER: '프로젝트 팀장 보상',
}

// 연속 출석 보너스 기준일은 xp_award_policies의 STREAK_<일수> 행으로 늘어날 수 있다.
const STREAK_PATTERN = /^STREAK_([1-9][0-9]*)$/

export function xpActivityLabel(activityType) {
  if (LABELS[activityType]) return LABELS[activityType]
  const streak = STREAK_PATTERN.exec(activityType || '')
  if (streak) return `${streak[1]}일 연속 출석 보너스`
  return activityType || '기타 활동'
}
