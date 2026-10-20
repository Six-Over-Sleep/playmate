import {
  getCardSchedule,
  getCategoryMeta,
  getMeetupStatus,
} from '../../utils/meetup'

// 모임의 카테고리, 일정, 모집 상태와 인원을 표시하는 목록 카드.
export default function MeetupCard({ meetup, featured = false, onClick }) {
  const category = getCategoryMeta(meetup.category)
  const status = getMeetupStatus(meetup)

  // 목록 API의 participant_count를 우선 사용하고, 없을 때만 대체 필드를 확인함.
  // ??를 사용해 실제 참여 인원인 0도 그대로 유지함.
  const currentCount =
    meetup.participant_count ??
    meetup.member_count ??
    meetup.current_count ??
    meetup.joined_count ??
    0

  const capacity = meetup.capacity ?? '-'

  return (
    <article
      className={[
        'meetup-card',
        featured ? 'meetup-card-featured' : '',
        status.className !== 'open' ? 'meetup-card-closed' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      onClick={onClick}
      tabIndex={0}
      role="button"
      onKeyDown={(event) => {
        // 마우스 클릭 외에 Enter와 Space 키로도 상세 화면을 열 수 있도록 함.
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onClick?.()
        }
      }}
    >
      <div className="meetup-card-top">
        <span className="meetup-category">
          {category.icon} {category.label}
        </span>
      </div>

      <div className="meetup-card-content">
        <h3>{meetup.title || '제목 없는 모임'}</h3>
        <p>{meetup.body || ''}</p>
      </div>

      <p className="meetup-card-schedule">{getCardSchedule(meetup)}</p>

      <div className="meetup-card-bottom">
        <strong className="meetup-card-count">
          {currentCount} / {capacity}명
        </strong>

        <span className={`meetup-status ${status.className}`}>
          {status.label}
        </span>
      </div>
    </article>
  )
}
