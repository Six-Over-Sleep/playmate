import { useEffect } from 'react'

import { formatDateTime } from '../../utils/meetup'

export default function MeetupExtensionModal({
  meetup,
  extension,
}) {
  const {
    open = false,
    newStart = '',
    newEnd = '',
    error = '',
    busy = false,

    oldStart = '',
    oldEnd = '',
    minDate = '',
    maxDate = '',
    extensionCount = 0,
    remainingExtensions = 0,

    setNewStart,
    setNewEnd,
    closeModal,
    submit,
  } = extension || {}

  useEffect(() => {
    if (!open) return undefined

    const previousOverflow = document.body.style.overflow

    const handleKeyDown = (event) => {
      if (event.key === 'Escape' && !busy) {
        closeModal?.()
      }
    }

    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', handleKeyDown)

    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [busy, closeModal, open])

  if (!open) return null

  const minDateTime = minDate
    ? `${minDate}T00:00`
    : undefined

  const maxDateTime = maxDate
    ? `${maxDate}T23:59`
    : undefined

  return (
    <div
      className="meetup-extension-overlay"
      role="presentation"
      onMouseDown={(event) => {
        if (
          event.target === event.currentTarget &&
          !busy
        ) {
          closeModal?.()
        }
      }}
    >
      <section
        className="meetup-extension-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="meetup-extension-title"
      >
        <header className="meetup-extension-header">
          <div>
            <span>프로젝트 일정 연장</span>
            <h2 id="meetup-extension-title">
              {meetup?.title || '프로젝트'}
            </h2>
          </div>

          <button
            type="button"
            onClick={closeModal}
            disabled={busy}
            aria-label="연장 창 닫기"
          >
            ×
          </button>
        </header>

        <div className="meetup-extension-body">
          <div className="meetup-extension-count">
            <strong>
              연장 {extensionCount} / 2회 사용
            </strong>
            <span>
              남은 연장 {remainingExtensions}회
            </span>
          </div>

          <div className="meetup-extension-schedule">
            <div>
              <span>기존 시작</span>
              <strong>
                {oldStart
                  ? formatDateTime(oldStart)
                  : '정보 없음'}
              </strong>
            </div>

            <div>
              <span>기존 종료</span>
              <strong>
                {oldEnd
                  ? formatDateTime(oldEnd)
                  : '정보 없음'}
              </strong>
            </div>
          </div>

          <div className="meetup-extension-range">
            새 시작일은 기존 시작일 다음 날부터 14일 이내인{' '}
            <strong>
              {minDate || '-'} ~ {maxDate || '-'}
            </strong>{' '}
            범위에서 선택할 수 있습니다. 날짜·시간·최종 가능 여부는 서버가
            다시 검증합니다.
          </div>

          <div className="meetup-extension-form">
            <label>
              <span>새 시작 일시</span>
              <input
                type="datetime-local"
                value={newStart}
                min={minDateTime}
                max={maxDateTime}
                onChange={(event) =>
                  setNewStart?.(event.target.value)
                }
                disabled={busy}
              />
            </label>

            <label>
              <span>새 종료 일시</span>
              <input
                type="datetime-local"
                value={newEnd}
                onChange={(event) =>
                  setNewEnd?.(event.target.value)
                }
                disabled={busy}
              />
              <small>
                기존 종료일이 새 시작일보다 빠르거나 같아지면 반드시 새
                종료 일시를 입력해야 합니다.
              </small>
            </label>
          </div>

          <div className="meetup-extension-notice">
            <p>
              기존 확정·대기 신청과 신청 순서는 유지됩니다.
            </p>
            <p>
              연장 후 새 모집 마감 전까지 기존 프로젝트의 기술·자리 규칙으로
              대기자가 다시 검토될 수 있습니다.
            </p>
            <p>
              최대 2회까지만 연장할 수 있으며 3번째 연장은 허용되지 않습니다.
            </p>
          </div>

          {error && (
            <div
              className="meetup-extension-error"
              role="alert"
            >
              {error}
            </div>
          )}
        </div>

        <footer className="meetup-extension-footer">
          <button
            type="button"
            className="secondary"
            onClick={closeModal}
            disabled={busy}
          >
            닫기
          </button>

          <button
            type="button"
            className="primary"
            onClick={submit}
            disabled={
              busy ||
              remainingExtensions <= 0
            }
          >
            {busy ? '처리 중...' : '연장 확인'}
          </button>
        </footer>
      </section>
    </div>
  )
}
