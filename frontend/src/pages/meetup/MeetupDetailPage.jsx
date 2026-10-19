import MeetupMemberList from '../../components/meetup/MeetupMemberList'
import {
  formatDateOnly,
  formatDateTime,
  getCategoryMeta,
  getMeetingSchedule,
  getMeetingType,
  getMeetupStatus,
  getPlace,
} from '../../utils/meetup'

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
        <div className="meetup-detail-loading">
          모임 정보를 불러오는 중이에요.
        </div>
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
  const status = getMeetupStatus(meetup, currentCount)

  const ownerId =
    meetup.owner_id ?? meetup.member_id ?? meetup.created_by ?? meetup.writer_id

  const canJoin =
    status.className === 'open' && Number(currentCount) < Number(capacity)

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

            <span className="meetup-mode-badge">{getMeetingType(meetup)}</span>

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

        <section className="meetup-extra-section">
          <h2>모임 상세 정보</h2>

          <div className="meetup-extra-grid">
            <div className="meetup-extra-item">
              <span className="meetup-extra-label">시작일</span>
              <span className="meetup-extra-value">
                {String(meetup.recruit_mode ?? '').toLowerCase() === 'short'
                  ? meetup.meeting_start
                    ? formatDateTime(meetup.meeting_start)
                    : '미입력'
                  : meetup.regular_start_date
                    ? formatDateOnly(meetup.regular_start_date)
                    : '미입력'}
              </span>
            </div>
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
                  <span className="meetup-extra-value">{detail.game_name}</span>
                </div>
              )}

            {String(meetup.category ?? '').toLowerCase() === 'study' && (
              <>
                <div className="meetup-extra-item">
                  <span className="meetup-extra-label">스터디 기간</span>
                  <span className="meetup-extra-value">
                    {detail.study_period?.trim() || '미입력'}
                  </span>
                </div>

                {detail.study_topic && (
                  <div className="meetup-extra-item full">
                    <span className="meetup-extra-label">스터디 주제</span>
                    <span className="meetup-extra-value">
                      {detail.study_topic}
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
                      {Number(
                        detail.estimated_price_per_person,
                      ).toLocaleString()}
                      원
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

        <MeetupMemberList
          members={members}
          currentCount={currentCount}
          ownerId={ownerId}
        />

        {actionMessage && (
          <div className="meetup-action-message">{actionMessage}</div>
        )}

        <footer className="meetup-detail-footer">
          {(onEdit || onDelete) && (
            <div className="meetup-owner-actions">
              {onEdit && (
                <button
                  type="button"
                  onClick={onEdit}
                >
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
                {busy ? '처리 중...' : canJoin ? '참여하기' : status.label}
              </button>
            )}
          </div>
        </footer>
      </article>
    </main>
  )
}
