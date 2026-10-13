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
  if (!value) return '일정 협의'

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)

  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hour = String(date.getHours()).padStart(2, '0')
  const minute = String(date.getMinutes()).padStart(2, '0')

  return `${month}/${day} ${hour}:${minute}`
}


function formatTime(value) {
  if (!value) return ''
  return String(value).slice(0, 5)
}

function getMeetingSchedule(meetup) {
  const mode = String(meetup?.recruit_mode ?? '').toLowerCase()

  if (mode === 'regular') {
    const days = Array.isArray(meetup?.regular_days)
      ? meetup.regular_days
      : []

    const time = formatTime(meetup?.regular_time)

    if (days.length > 0 && time) {
      return `${days.join(' · ')} ${time}`
    }

    if (days.length > 0) {
      return days.join(' · ')
    }

    if (time) {
      return time
    }
  }

  if (mode === 'short') {
    const start = meetup?.meeting_start
      ? formatDateTime(meetup.meeting_start)
      : ''

    const end = meetup?.meeting_end
      ? formatDateTime(meetup.meeting_end)
      : ''

    if (start && end) {
      return `${start} ~ ${end}`
    }

    if (start) {
      return start
    }
  }

  if (meetup?.meeting_datetime) {
    return formatDateTime(meetup.meeting_datetime)
  }

  return '일정 협의'
}

function getMeetingType(meetup) {
  const mode = String(meetup?.recruit_mode ?? '').toLowerCase()

  if (mode === 'short' || mode === '단기' || mode === '단기 모임') {
    return '단기 모임'
  }

  return '정기 모임'
}

function getPlace(meetup) {
  if (meetup?.is_online) return '온라인'

  const mode = String(meetup?.recruit_mode ?? '').toLowerCase()
  const place = meetup?.place?.trim?.() || meetup?.place

  if (mode === 'online') return '온라인'
  if (!place) return '장소 협의'

  return `${place} (오프라인)`
}

function getStatus(meetup, currentCount) {
  const raw = String(meetup?.state ?? meetup?.status ?? 'OPEN').toUpperCase()
  const capacity = Number(meetup?.capacity ?? 0)

  if (['CANCELLED', 'CANCELED'].includes(raw)) {
    return { className: 'closed', label: '취소' }
  }

  if (['EXPIRED', 'DEADLINE'].includes(raw)) {
    return { className: 'deadline', label: '기한마감' }
  }

  if (raw === 'FULL' || (capacity > 0 && Number(currentCount) >= capacity)) {
    return { className: 'closed', label: '정원마감' }
  }

  if (raw === 'CLOSED') {
    return { className: 'closed', label: '모집마감' }
  }

  return { className: 'open', label: '모집중' }
}

function getMemberName(member, index) {
  return (
    member?.nickname ||
    member?.name ||
    member?.member_name ||
    member?.username ||
    `참여자 ${index + 1}`
  )
}

export default function MeetupDetailPage({
  meetup,
  members = [],
  memberCount,
  joined = false,
  busy = false,
  actionMessage = '',
  onBack,
  onEdit,
  onDelete,
  onJoin,
  onCancelJoin,
}) {
  if (!meetup) {
    return (
      <main className="meetup-detail-page">
        <div className="meetup-detail-loading">모임 정보를 불러오는 중이에요.</div>
      </main>
    )
  }

  const category = getCategoryMeta(meetup.category)
  const detail = meetup?.detail || {}

  const currentCount =
    memberCount ??
    meetup.participant_count ??
    meetup.member_count ??
    meetup.current_count ??
    meetup.joined_count ??
    members.length ??
    0

  const capacity = meetup.capacity ?? '-'
  const status = getStatus(meetup, currentCount)

  const ownerId =
    meetup.owner_id ??
    meetup.member_id ??
    meetup.created_by ??
    meetup.writer_id

  const isHostMember = (member) => {
    if (member?.is_host || member?.is_owner) return true

    const id = member?.member_id ?? member?.id
    return ownerId != null && id != null && String(id) === String(ownerId)
  }

  const canJoin = status.className === 'open' && Number(currentCount) < Number(capacity)

  return (
    <main className="meetup-detail-page">
      <button
        type="button"
        className="meetup-back-button"
        onClick={onBack}
      >
        ← 목록으로
      </button>

      <article className="meetup-detail-card">
        <div className="meetup-detail-top">
          <div className="meetup-detail-badges">
            <span className="meetup-category-badge">
              {category.icon} {category.label}
            </span>

            <span className="meetup-mode-badge">
              {getMeetingType(meetup)}
            </span>

            {meetup.deadline_at && (
              <span className="meetup-deadline-text">
                · {formatDateTime(meetup.deadline_at)} 모집 마감
              </span>
            )}
          </div>

          <span className={`meetup-status ${status.className}`}>
            {status.label}
          </span>
        </div>

        <h1>{meetup.title || '제목 없는 모임'}</h1>

        <div className="meetup-summary-grid">
          <div className="meetup-summary-item">
            <span>일시</span>
            <strong>{getMeetingSchedule(meetup)}</strong>
          </div>

          <div className="meetup-summary-item">
            <span>장소</span>
            <strong>{getPlace(meetup)}</strong>
          </div>

          <div className="meetup-summary-item">
            <span>모집 인원</span>
            <strong className="meetup-capacity-value">
              {currentCount} / {capacity}명
            </strong>
          </div>
        </div>

        <div className="meetup-detail-body">
          {meetup.body || '등록된 모임 설명이 없습니다.'}
        </div>

        {(detail.sport_name ||
          detail.game_name ||
          detail.study_topic ||
          detail.study_period ||
          detail.study_method ||
          detail.product_name ||
          detail.purchase_url ||
          detail.estimated_price_per_person ||
          detail.pickup_method) && (
          <section className="meetup-extra-section">
            <h2>모임 상세 정보</h2>

            <div className="meetup-extra-grid">
              {['sports', 'sport', 'exercise'].includes(
                String(meetup.category ?? '').toLowerCase(),
              ) &&
                detail.sport_name && (
                  <div className="meetup-extra-item">
                    <span className="meetup-extra-label">종목</span>
                    <span className="meetup-extra-value">
                      {detail.sport_name}
                    </span>
                  </div>
                )}

              {['game', 'gaming'].includes(
                String(meetup.category ?? '').toLowerCase(),
              ) &&
                detail.game_name && (
                  <div className="meetup-extra-item">
                    <span className="meetup-extra-label">게임명</span>
                    <span className="meetup-extra-value">
                      {detail.game_name}
                    </span>
                  </div>
                )}

              {String(meetup.category ?? '').toLowerCase() === 'study' && (
                <>
                  {detail.study_topic && (
                    <div className="meetup-extra-item">
                      <span className="meetup-extra-label">스터디 주제</span>
                      <span className="meetup-extra-value">
                        {detail.study_topic}
                      </span>
                    </div>
                  )}

                  {detail.study_period && (
                    <div className="meetup-extra-item">
                      <span className="meetup-extra-label">스터디 기간</span>
                      <span className="meetup-extra-value">
                        {detail.study_period}
                      </span>
                    </div>
                  )}

                  {detail.study_method && (
                    <div className="meetup-extra-item full">
                      <span className="meetup-extra-label">스터디 방식</span>
                      <span className="meetup-extra-value">
                        {detail.study_method}
                      </span>
                    </div>
                  )}
                </>
              )}

              {['group_buy', 'groupbuy', 'purchase'].includes(
                String(meetup.category ?? '').toLowerCase(),
              ) && (
                <>
                  {detail.product_name && (
                    <div className="meetup-extra-item">
                      <span className="meetup-extra-label">상품명</span>
                      <span className="meetup-extra-value">
                        {detail.product_name}
                      </span>
                    </div>
                  )}

                  {detail.estimated_price_per_person != null && (
                    <div className="meetup-extra-item">
                      <span className="meetup-extra-label">예상 1인 가격</span>
                      <span className="meetup-extra-value">
                        {Number(detail.estimated_price_per_person).toLocaleString()}원
                      </span>
                    </div>
                  )}

                  {detail.pickup_method && (
                    <div className="meetup-extra-item">
                      <span className="meetup-extra-label">수령 방법</span>
                      <span className="meetup-extra-value">
                        {detail.pickup_method}
                      </span>
                    </div>
                  )}

                  {detail.purchase_url && (
                    <div className="meetup-extra-item">
                      <span className="meetup-extra-label">구매 링크</span>
                      <span className="meetup-extra-value">
                        <a
                          href={detail.purchase_url}
                          target="_blank"
                          rel="noreferrer"
                          onClick={(event) => event.stopPropagation()}
                        >
                          {detail.purchase_url}
                        </a>
                      </span>
                    </div>
                  )}
                </>
              )}
            </div>
          </section>
        )}

        <section className="meetup-member-section">
          <h2>참여 멤버 ({currentCount})</h2>

          {members.length > 0 ? (
            <ul className="meetup-member-list">
              {members.map((member, index) => (
                <li key={member.member_id ?? member.id ?? index}>
                  <div className="meetup-member-info">
                    <span
                      className="meetup-member-avatar"
                      aria-hidden="true"
                    />
                    <span>{getMemberName(member, index)}</span>
                  </div>

                  {isHostMember(member) && (
                    <span className="meetup-host-badge">모임장</span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <div className="meetup-member-empty">
              아직 참여 멤버 정보가 없어요.
            </div>
          )}
        </section>

        {actionMessage && (
          <div className="meetup-action-message">
            {actionMessage}
          </div>
        )}

        <footer className="meetup-detail-footer">
          {(onEdit || onDelete) && (
            <div className="meetup-owner-actions">
              {onEdit && (
                <button type="button" onClick={onEdit}>
                  수정
                </button>
              )}

              {onDelete && (
                <button
                  type="button"
                  className="delete"
                  onClick={onDelete}
                >
                  삭제
                </button>
              )}
            </div>
          )}

          <div className="meetup-action-buttons">
            {joined ? (
              <button
                type="button"
                className="meetup-cancel-button"
                onClick={onCancelJoin}
                disabled={busy}
              >
                {busy ? '처리 중...' : '참여 취소'}
              </button>
            ) : (
              <button
                type="button"
                className="meetup-join-button"
                onClick={onJoin}
                disabled={busy || !canJoin}
              >
                {busy
                  ? '처리 중...'
                  : canJoin
                    ? '참여하기'
                    : status.label}
              </button>
            )}
          </div>
        </footer>
      </article>
    </main>
  )
}
