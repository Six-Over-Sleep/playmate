import {
  getCardSchedule,
  getCategoryMeta,
  getMeetupStatus,
} from '../../utils/meetup'

export default function MeetupCard({ meetup, featured = false, onClick }) {
  const category = getCategoryMeta(meetup.category)
  const status = getMeetupStatus(meetup)

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
