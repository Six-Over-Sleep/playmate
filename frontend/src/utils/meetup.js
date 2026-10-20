// 목록 카테고리 선택 항목
export const CATEGORY_OPTIONS = [
  { value: 'all', label: '전체' },
  { value: 'sports', label: '🏃 운동' },
  { value: 'game', label: '🎮 게임' },
  { value: 'study', label: '📖 스터디' },
  { value: 'group_buy', label: '🛒 공동구매' },
]

// 작성 화면 카테고리 선택 항목
export const EDITOR_CATEGORY_OPTIONS = CATEGORY_OPTIONS.filter(
  (item) => item.value !== 'all',
)

// 정기 모임 요일 목록
export const WEEKDAYS = ['월', '화', '수', '목', '금', '토', '일']

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

// 카테고리 별칭 통일
export function normalizeCategory(value) {
  if (!value) return ''

  const category = String(value).toLowerCase()

  if (['sports', 'sport', 'exercise', '운동'].includes(category)) {
    return 'sports'
  }

  if (['game', 'gaming', '게임'].includes(category)) {
    return 'game'
  }

  if (['study', '스터디'].includes(category)) {
    return 'study'
  }

  if (['group_buy', 'groupbuy', 'purchase', '공동구매'].includes(category)) {
    return 'group_buy'
  }

  return category
}

// 카테고리 아이콘과 표시 이름
export function getCategoryMeta(value) {
  const key = String(value ?? '').toLowerCase()

  return (
    CATEGORY_META[key] ?? {
      icon: '👥',
      label: value || '모임',
    }
  )
}

// 날짜·시간 표시 형식 변환
export function formatDateTime(value, fallback = '') {
  if (!value) return fallback

  const date = new Date(value)

  if (Number.isNaN(date.getTime())) {
    return String(value)
  }

  const month = String(date.getMonth() + 1).padStart(2, '0')

  const day = String(date.getDate()).padStart(2, '0')

  const hour = String(date.getHours()).padStart(2, '0')

  const minute = String(date.getMinutes()).padStart(2, '0')

  return `${month}/${day} ${hour}:${minute}`
}

// 날짜 표시 형식 변환
export function formatDateOnly(value) {
  if (!value) return ''

  const raw = String(value).slice(0, 10)
  const parts = raw.split('-')

  if (parts.length === 3) {
    return `${parts[0]}.${parts[1]}.${parts[2]}`
  }

  return raw
}

// 시간 표시 형식 변환
export function formatTime(value) {
  if (!value) return ''

  return String(value).slice(0, 5)
}

// 정기·단기 모임별 일정 문구
export function getMeetingSchedule(meetup) {
  const mode = String(meetup?.recruit_mode ?? '').toLowerCase()

  if (mode === 'regular') {
    const days = Array.isArray(meetup?.regular_days) ? meetup.regular_days : []

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

    const end = meetup?.meeting_end ? formatDateTime(meetup.meeting_end) : ''

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

// 모임 방식 표시 이름
export function getMeetingType(meetup) {
  const mode = String(meetup?.recruit_mode ?? '').toLowerCase()

  if (mode === 'short' || mode === '단기' || mode === '단기 모임') {
    return '단기 모임'
  }

  return '정기 모임'
}

// 온라인 여부와 장소 표시 문구
export function getPlace(meetup) {
  if (meetup?.is_online) {
    return '온라인'
  }

  const mode = String(meetup?.recruit_mode ?? '').toLowerCase()

  const place = meetup?.place?.trim?.() || meetup?.place

  if (mode === 'online') {
    return '온라인'
  }

  if (!place) {
    return '장소 협의'
  }

  return `${place} (오프라인)`
}

// 모임 상태·모집 마감·정원 기준 상태 판별
export function getMeetupStatus(meetup, currentCount = null) {
  const raw = String(meetup?.state ?? meetup?.status ?? 'OPEN').toUpperCase()

  const current = Number(
    currentCount ??
      meetup?.participant_count ??
      meetup?.member_count ??
      meetup?.current_count ??
      meetup?.joined_count ??
      0,
  )

  const capacity = Number(meetup?.capacity ?? 0)

  if (['CANCELLED', 'CANCELED'].includes(raw)) {
    return {
      className: 'closed',
      label: '취소',
    }
  }

  if (['EXPIRED', 'DEADLINE'].includes(raw)) {
    return {
      className: 'deadline',
      label: '기한마감',
    }
  }

  if (raw === 'FULL' || (capacity > 0 && current >= capacity)) {
    return {
      className: 'closed',
      label: '정원마감',
    }
  }

  if (raw === 'CLOSED') {
    return {
      className: 'closed',
      label: '모집마감',
    }
  }

  return {
    className: 'open',
    label: '모집중',
  }
}

// 모집 종료 여부
export function isClosedMeetup(meetup) {
  return getMeetupStatus(meetup).className !== 'open'
}

// 목록 카드의 일정·장소 표시 문구
export function getCardSchedule(meetup) {
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

  if (place) {
    return place
  }

  return '일정 협의'
}

// 참여자 이름과 기본 표시 이름
export function getMemberName(member, index) {
  return (
    member?.nickname ||
    member?.name ||
    member?.member_name ||
    member?.username ||
    `참여자 ${index + 1}`
  )
}

// 배열·문자열 형태의 요일 목록 변환
export function normalizeRegularDays(value) {
  if (Array.isArray(value)) {
    return value
  }

  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)

      if (Array.isArray(parsed)) {
        return parsed
      }
    } catch {
      return value
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean)
    }
  }

  return []
}

// 날짜·시간 입력 필드 형식 변환
export function toDateTimeLocal(value) {
  if (!value) return ''

  return String(value).slice(0, 16)
}

// 시간 입력 필드 형식 변환
export function toTimeValue(value) {
  if (!value) return ''

  return String(value).slice(0, 5)
}

// API 응답별 참여 인원수 추출
export function normalizeMemberCount(data) {
  if (typeof data === 'number') {
    return data
  }

  return Number(
    data?.current_members ??
      data?.count ??
      data?.member_count ??
      data?.current_count ??
      data?.participant_count ??
      0,
  )
}
