import { useEffect, useMemo, useState } from 'react'

import { normalizeCategory } from '../../utils/meetup'

function activityOptions(meetup) {
  const category = normalizeCategory(meetup?.category)

  if (category === 'study') {
    return [
      { value: 'WEEKLY_CHECK', label: '주간 활동 인증' },
      { value: 'PARTICIPATION_PROOF', label: '참여 인증' },
    ]
  }

  if (category === 'project') {
    return [
      { value: 'OUTPUT', label: '프로젝트 결과물' },
      { value: 'PARTICIPATION_PROOF', label: '참여 인증' },
    ]
  }

  return [
    { value: 'PARTICIPATION_PROOF', label: '참여 인증' },
  ]
}

function parseLinks(value) {
  return String(value ?? '')
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean)
}

export default function MeetupActivityModal({
  open = false,
  mode = 'activity',
  meetup,
  busy = false,
  onClose,
  onSubmit,
}) {
  const options = useMemo(
    () => activityOptions(meetup),
    [meetup],
  )

  const isReview = mode === 'review'

  const [activityType, setActivityType] = useState(
    options[0]?.value || 'PARTICIPATION_PROOF',
  )
  const [week, setWeek] = useState('1')
  const [submissionStage, setSubmissionStage] = useState('INTERIM')
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [links, setLinks] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return

    setActivityType(
      isReview
        ? 'REVIEW'
        : options[0]?.value || 'PARTICIPATION_PROOF',
    )
    setWeek('1')
    setSubmissionStage('INTERIM')
    setTitle('')
    setBody('')
    setLinks('')
    setError('')
  }, [open, isReview, options])

  if (!open) return null

  const handleSubmit = async (event) => {
    event.preventDefault()

    const trimmedTitle = title.trim()
    const trimmedBody = body.trim()

    if (!trimmedTitle || !trimmedBody) {
      setError('제목과 내용을 입력해주세요.')
      return
    }

    const payload = {
      activity_type: isReview ? 'REVIEW' : activityType,
      title: trimmedTitle,
      body: trimmedBody,
      links: parseLinks(links),
      attachment_ids: [],
    }

    if (!isReview && activityType === 'WEEKLY_CHECK') {
      const parsedWeek = Number(week)

      if (!Number.isInteger(parsedWeek) || parsedWeek < 1) {
        setError('주차는 1 이상의 숫자로 입력해주세요.')
        return
      }

      payload.week = parsedWeek
    }

    if (!isReview && activityType === 'OUTPUT') {
      payload.submission_stage = submissionStage
    }

    setError('')

    try {
      const result = await onSubmit?.(payload)

      if (result) {
        onClose?.()
      }
    } catch (submitError) {
      setError(
        submitError?.message ||
          (isReview
            ? '후기를 등록하지 못했습니다.'
            : '활동 기록을 등록하지 못했습니다.'),
      )
    }
  }

  return (
    <div
      className="meetup-modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) {
          onClose?.()
        }
      }}
    >
      <section
        className="meetup-modal meetup-activity-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="meetup-activity-modal-title"
      >
        <div className="meetup-modal-header">
          <div>
            <h2 id="meetup-activity-modal-title">
              {isReview ? '모임 후기 작성' : '모임 활동 작성'}
            </h2>
            <p>
              {isReview
                ? '정상 종료된 모임의 참여 후기를 작성해주세요.'
                : '진행 중인 모임의 활동 내용을 기록해주세요.'}
            </p>
          </div>

          <button
            type="button"
            className="meetup-modal-close"
            onClick={onClose}
            disabled={busy}
            aria-label="닫기"
          >
            ×
          </button>
        </div>

        <form
          className="meetup-activity-form"
          onSubmit={handleSubmit}
        >
          {!isReview && options.length > 1 && (
            <label className="meetup-form-field">
              <span>활동 종류</span>
              <select
                value={activityType}
                onChange={(event) =>
                  setActivityType(event.target.value)
                }
                disabled={busy}
              >
                {options.map((option) => (
                  <option
                    key={option.value}
                    value={option.value}
                  >
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          )}

          {!isReview && activityType === 'WEEKLY_CHECK' && (
            <label className="meetup-form-field">
              <span>주차</span>
              <input
                type="number"
                min="1"
                step="1"
                value={week}
                onChange={(event) => setWeek(event.target.value)}
                disabled={busy}
              />
            </label>
          )}

          {!isReview && activityType === 'OUTPUT' && (
            <label className="meetup-form-field">
              <span>결과물 단계</span>
              <select
                value={submissionStage}
                onChange={(event) =>
                  setSubmissionStage(event.target.value)
                }
                disabled={busy}
              >
                <option value="INTERIM">중간 결과물</option>
                <option value="FINAL">최종 결과물</option>
              </select>
            </label>
          )}

          <label className="meetup-form-field">
            <span>제목</span>
            <input
              type="text"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder={
                isReview
                  ? '후기 제목을 입력해주세요.'
                  : '활동 제목을 입력해주세요.'
              }
              disabled={busy}
            />
          </label>

          <label className="meetup-form-field">
            <span>내용</span>
            <textarea
              rows="7"
              value={body}
              onChange={(event) => setBody(event.target.value)}
              placeholder={
                isReview
                  ? '모임을 진행하며 느낀 점을 작성해주세요.'
                  : '진행한 활동이나 인증 내용을 작성해주세요.'
              }
              disabled={busy}
            />
          </label>

          <label className="meetup-form-field">
            <span>관련 링크 (선택)</span>
            <textarea
              rows="3"
              value={links}
              onChange={(event) => setLinks(event.target.value)}
              placeholder={'https://...\n링크가 여러 개면 줄바꿈으로 구분해주세요.'}
              disabled={busy}
            />
          </label>

          {error && (
            <div
              className="meetup-form-error"
              role="alert"
            >
              {error}
            </div>
          )}

          <div className="meetup-modal-actions">
            <button
              type="button"
              className="meetup-cancel-button"
              onClick={onClose}
              disabled={busy}
            >
              취소
            </button>

            <button
              type="submit"
              className="meetup-join-button"
              disabled={busy}
            >
              {busy
                ? '등록 중...'
                : isReview
                  ? '후기 등록'
                  : '활동 등록'}
            </button>
          </div>
        </form>
      </section>
    </div>
  )
}
