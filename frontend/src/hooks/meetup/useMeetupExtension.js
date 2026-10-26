import { useCallback, useMemo, useRef, useState } from 'react'

const SEOUL_TIMEZONE = 'Asia/Seoul'

function getDatePart(value) {
  if (!value) return ''

  const text = String(value)
  const matched = text.match(/^(\d{4})-(\d{2})-(\d{2})/)

  if (matched) {
    return `${matched[1]}-${matched[2]}-${matched[3]}`
  }

  return ''
}

function addDays(dateText, days) {
  if (!dateText) return ''

  const [year, month, day] = dateText.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))

  date.setUTCDate(date.getUTCDate() + days)

  const y = date.getUTCFullYear()
  const m = String(date.getUTCMonth() + 1).padStart(2, '0')
  const d = String(date.getUTCDate()).padStart(2, '0')

  return `${y}-${m}-${d}`
}

function formatSeoulDateTimeLocal(value) {
  if (!value) return ''

  const date = new Date(value)

  if (Number.isNaN(date.getTime())) {
    return String(value).slice(0, 16)
  }

  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: SEOUL_TIMEZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date)

  const values = Object.fromEntries(
    parts.map((part) => [part.type, part.value]),
  )

  return `${values.year}-${values.month}-${values.day}T${values.hour}:${values.minute}`
}

function toSeoulAwareIso(value) {
  const text = String(value ?? '').trim()

  if (!text) return ''

  // datetime-local 입력은 시간대가 없으므로
  // 서비스 정책의 기준 시간대(Asia/Seoul)를 명시한다.
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(text)) {
    return `${text}:00+09:00`
  }

  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(text)) {
    return `${text}+09:00`
  }

  return text
}

function createRequestKey() {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID()
  }

  return `extend-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`
}

function getExtensionCount(meetup) {
  const count = Number(meetup?.extension_count ?? 0)

  return Number.isFinite(count)
    ? Math.min(Math.max(count, 0), 2)
    : 0
}

export default function useMeetupExtension({
  meetup,
  submitExtension,
  onSuccess,
}) {
  const [open, setOpen] = useState(false)
  const [newStart, setNewStart] = useState('')
  const [newEnd, setNewEnd] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submittingRef = useRef(false)

  // 동일한 본문을 네트워크 문제로 재시도할 때는 같은 request_key를 유지하고,
  // 입력 내용이 바뀌면 새 request_key를 사용한다.
  const requestRef = useRef({
    signature: '',
    key: '',
  })

  const oldStart =
    meetup?.starts_at ??
    meetup?.meeting_start ??
    ''

  const oldEnd =
    meetup?.ends_at ??
    meetup?.meeting_end ??
    ''

  const extensionWindow = meetup?.extension_window || {}

  const fallbackBaseDate = getDatePart(
    formatSeoulDateTimeLocal(oldStart),
  )

  const minDate =
    extensionWindow.earliest_start_date ||
    addDays(fallbackBaseDate, 1)

  const maxDate =
    extensionWindow.latest_start_date ||
    addDays(fallbackBaseDate, 14)

  const extensionCount = getExtensionCount(meetup)

  const remainingExtensions = useMemo(() => {
    const serverValue = Number(
      extensionWindow.remaining_extensions,
    )

    if (Number.isFinite(serverValue)) {
      return Math.min(Math.max(serverValue, 0), 2)
    }

    return Math.max(0, 2 - extensionCount)
  }, [extensionCount, extensionWindow.remaining_extensions])

  const scheduleVersion = Number(
    meetup?.schedule_version ?? 0,
  )

  const reset = useCallback(() => {
    setNewStart('')
    setNewEnd(formatSeoulDateTimeLocal(oldEnd))
    setError('')
    setBusy(false)
    submittingRef.current = false
    requestRef.current = {
      signature: '',
      key: '',
    }
  }, [oldEnd])

  const openModal = useCallback(() => {
    reset()
    setOpen(true)
  }, [reset])

  const closeModal = useCallback(() => {
    if (submittingRef.current) return

    setOpen(false)
    reset()
  }, [reset])

  const validate = useCallback(() => {
    if (remainingExtensions <= 0) {
      return '사용 가능한 연장 횟수가 없습니다.'
    }

    if (!Number.isInteger(scheduleVersion) || scheduleVersion < 1) {
      return '최신 일정 버전을 확인할 수 없습니다. 상세 정보를 다시 불러와주세요.'
    }

    if (!newStart) {
      return '새 시작 일시를 선택해주세요.'
    }

    if (!newEnd) {
      return '새 종료 일시를 입력해주세요.'
    }

    const newStartDate = getDatePart(newStart)

    if (
      !newStartDate ||
      (minDate && newStartDate < minDate) ||
      (maxDate && newStartDate > maxDate)
    ) {
      return `새 시작일은 서버가 허용한 범위(${minDate || '-'} ~ ${maxDate || '-'})에서 선택해주세요.`
    }

    const startTime = new Date(
      toSeoulAwareIso(newStart),
    ).getTime()

    const endTime = new Date(
      toSeoulAwareIso(newEnd),
    ).getTime()

    if (
      Number.isNaN(startTime) ||
      Number.isNaN(endTime)
    ) {
      return '시작·종료 일시 형식을 다시 확인해주세요.'
    }

    if (endTime <= startTime) {
      return '새 종료 일시는 새 시작 일시보다 뒤여야 합니다.'
    }

    return ''
  }, [
    maxDate,
    minDate,
    newEnd,
    newStart,
    remainingExtensions,
    scheduleVersion,
  ])

  const submit = useCallback(async () => {
    if (submittingRef.current) return null

    const validationError = validate()

    if (validationError) {
      setError(validationError)
      return null
    }

    if (typeof submitExtension !== 'function') {
      setError('프로젝트 연장 기능이 연결되지 않았습니다.')
      return null
    }

    const startsAt = toSeoulAwareIso(newStart)
    const endsAt = toSeoulAwareIso(newEnd)

    const signature = JSON.stringify({
      starts_at: startsAt,
      ends_at: endsAt,
      schedule_version: scheduleVersion,
    })

    if (
      requestRef.current.signature !== signature ||
      !requestRef.current.key
    ) {
      requestRef.current = {
        signature,
        key: createRequestKey(),
      }
    }

    const payload = {
      starts_at: startsAt,
      ends_at: endsAt,
      schedule_version: scheduleVersion,
      request_key: requestRef.current.key,
    }

    submittingRef.current = true
    setBusy(true)
    setError('')

    try {
      const response = await submitExtension(payload)

      await onSuccess?.(response ?? null)

      setOpen(false)

      return response ?? null
    } catch (err) {
      setError(
        err?.message ||
          '프로젝트 연장을 처리하지 못했습니다.',
      )

      return null
    } finally {
      submittingRef.current = false
      setBusy(false)
    }
  }, [
    newEnd,
    newStart,
    onSuccess,
    scheduleVersion,
    submitExtension,
    validate,
  ])

  return {
    open,
    newStart,
    newEnd,
    error,
    busy,

    oldStart,
    oldEnd,
    minDate,
    maxDate,
    extensionCount,
    remainingExtensions,
    scheduleVersion,
    extensionWindow,

    setNewStart,
    setNewEnd,
    openModal,
    closeModal,
    submit,
  }
}
