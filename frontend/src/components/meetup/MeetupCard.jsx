import {
  getCardSchedule,
  getCategoryMeta,
  getMeetupStatus,
  getRequiredSkills,
  isMissingSkill,
  normalizeCategory,
} from '../../utils/meetup'

// 모임의 카테고리, 일정, 모집 상태와 인원,
// 프로젝트 기술 또는 스터디 정보를 표시하는 목록 카드.
export default function MeetupCard({
  meetup,
  featured = false,
  onClick,
}) {
  const category = getCategoryMeta(meetup.category)
  const normalizedCategory = normalizeCategory(meetup.category)
  const status = getMeetupStatus(meetup)

  // 목록 API의 participant_count를 우선 사용하고,
  // 없을 때만 기존 응답의 대체 필드를 확인함.
  // ??를 사용해 실제 참여 인원인 0도 그대로 유지함.
  const currentCount =
    meetup.participant_count ??
    meetup.member_count ??
    meetup.current_count ??
    meetup.joined_count ??
    0

  const capacity = meetup.capacity ?? '-'

  /*
   * 취소·마감·완료처럼 실제 모집이 끝난 카드만
   * 기존 closed 스타일을 적용함.
   *
   * READY, 정원 충족(full)은 대기/예정 상태일 수 있으므로
   * 모집 종료 카드처럼 흐리게 처리하지 않음.
   */
  const isInactive = [
    'closed',
    'deadline',
    'completed',
  ].includes(status.className)

  // 프로젝트 목록에서 사용할 필수 기술.
  const requiredSkills =
    normalizedCategory === 'project'
      ? getRequiredSkills(meetup)
      : []

  // 카드가 너무 길어지는 것을 막기 위해 최대 3개까지만 표시.
  const visibleSkills = requiredSkills.slice(0, 3)
  const hiddenSkillCount = Math.max(
    requiredSkills.length - visibleSkills.length,
    0,
  )

  // 목록 API와 기존 detail 구조 모두 대응.
  const studyTopic =
    meetup.study_topic ??
    meetup.detail?.study_topic ??
    ''

  const studyDifficulty =
    meetup.difficulty ??
    meetup.detail?.difficulty ??
    ''

  const studyType =
    meetup.study_type ??
    meetup.detail?.study_type ??
    ''

  const getDifficultyLabel = (value) => {
    const difficulty = String(value ?? '').toUpperCase()

    if (difficulty === 'BEGINNER') {
      return '기초'
    }

    if (difficulty === 'ADVANCED') {
      return '심화'
    }

    return value || ''
  }

  const getStudyTypeLabel = (value) => {
    const type = String(value ?? '').toUpperCase()

    if (type === 'TECHNOLOGY') {
      return '기술 공부'
    }

    if (type === 'CERTIFICATE') {
      return '자격증'
    }

    return value || ''
  }

  return (
    <article
      className={[
        'meetup-card',
        featured ? 'meetup-card-featured' : '',
        isInactive ? 'meetup-card-closed' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      onClick={onClick}
      tabIndex={0}
      role="button"
      onKeyDown={(event) => {
        // 마우스 클릭 외에 Enter와 Space 키로도
        // 상세 화면을 열 수 있도록 함.
        if (
          event.key === 'Enter' ||
          event.key === ' '
        ) {
          event.preventDefault()
          onClick?.()
        }
      }}
    >
      <div className="meetup-card-top">
        <span className="meetup-category">
          {category.icon} {category.label}
        </span>

        <span
          className={`meetup-status ${status.className}`}
        >
          {status.label}
        </span>
      </div>

      <div className="meetup-card-content">
        <h3>{meetup.title || '제목 없는 모임'}</h3>

        {meetup.body && (
          <p>{meetup.body}</p>
        )}
      </div>

      {/* 프로젝트 필수 기술 */}
      {normalizedCategory === 'project' &&
        requiredSkills.length > 0 && (
          <div className="meetup-card-skills">
            {visibleSkills.map((skill) => {
              const skillId =
                skill?.skill_id ??
                skill?.id ??
                skill

              const skillName =
                skill?.skill_name ??
                skill?.name ??
                String(skill)

              const missing = isMissingSkill(
                meetup,
                skill,
              )

              return (
                <span
                  key={skillId}
                  className={[
                    'meetup-skill-chip',
                    missing
                      ? 'meetup-skill-missing'
                      : 'meetup-skill-filled',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                >
                  {skillName}
                </span>
              )
            })}

            {hiddenSkillCount > 0 && (
              <span className="meetup-skill-more">
                +{hiddenSkillCount}
              </span>
            )}
          </div>
        )}

      {/* 스터디 주제·종류·난이도 */}
      {normalizedCategory === 'study' &&
        (studyTopic ||
          studyType ||
          studyDifficulty) && (
          <div className="meetup-card-study-info">
            {studyTopic && (
              <span className="meetup-study-topic">
                {studyTopic}
              </span>
            )}

            {studyType && (
              <span className="meetup-study-meta">
                {getStudyTypeLabel(studyType)}
              </span>
            )}

            {studyDifficulty && (
              <span className="meetup-study-meta">
                {getDifficultyLabel(
                  studyDifficulty,
                )}
              </span>
            )}
          </div>
        )}

      <p className="meetup-card-schedule">
        {getCardSchedule(meetup)}
      </p>

      <div className="meetup-card-bottom">
        <strong className="meetup-card-count">
          {currentCount} / {capacity}명

          {/* 목록 API의 like_count를 참여 인원 옆에 표시 */}
          <span className="meetup-card-like">
            ♡ {meetup.like_count ?? 0}
          </span>
        </strong>
      </div>
    </article>
  )
}