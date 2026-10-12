const CATEGORY_META = {
  sports: { icon: '🏃', label: '운동' },
  sport: { icon: '🏃', label: '운동' },
  exercise: { icon: '🏃', label: '운동' },
  game: { icon: '🎮', label: '게임' },
  gaming: { icon: '🎮', label: '게임' },
  study: { icon: '📖', label: '스터디' },
  group_buy: { icon: '🛒', label: '공동구매' },
  groupbuy: { icon: '🛒', label: '공동구매' },
  purchase: { icon: '🛒', label: '공동구매' },
}

function getCategoryMeta(value) {
  const key = String(value ?? '').toLowerCase()
  return CATEGORY_META[key] ?? {
    icon: '👥',
    label: value || '모임',
  }
}

function formatDateTime(value) {
  if (!value) return ''

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)

  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hour = String(date.getHours()).padStart(2, '0')
  const minute = String(date.getMinutes()).padStart(2, '0')

  return `${month}/${day} ${hour}:${minute}`
}

function getStatus(meetup) {
  const raw = String(meetup?.state ?? meetup?.status ?? 'OPEN').toUpperCase()

  if (['CANCELLED', 'CANCELED'].includes(raw)) {
    return { className: 'closed', label: '취소' }
  }

  if (['EXPIRED', 'DEADLINE'].includes(raw)) {
    return { className: 'deadline', label: '기한마감' }
  }

  const current = Number(
    meetup?.participant_count ??
      meetup?.member_count ??
      meetup?.current_count ??
      meetup?.joined_count ??
      0,
  )

  const capacity = Number(meetup?.capacity ?? 0)

  if (raw === 'FULL' || (capacity > 0 && current >= capacity)) {
    return { className: 'closed', label: '정원마감' }
  }

  if (raw === 'CLOSED') {
    return { className: 'closed', label: '모집마감' }
  }

  return { className: 'open', label: '모집중' }
}

function getSchedule(meetup) {
  const deadlineText = formatDateTime(
    meetup?.deadline_at || meetup?.recruit_end,
  )

  if (deadlineText) {
    return `${deadlineText} 마감`
  }

  if (meetup?.is_online) {
    return '온라인'
  }

  const place = meetup?.place?.trim?.() || meetup?.place || ''

  if (place) return place

  return '일정 협의'
}

export default function MeetupCard({
  meetup,
  featured = false,
  onClick,
}) {
  const category = getCategoryMeta(meetup.category)
  const status = getStatus(meetup)

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

      <p className="meetup-card-schedule">{getSchedule(meetup)}</p>

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
