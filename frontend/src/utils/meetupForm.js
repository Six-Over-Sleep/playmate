// Form and API errors stay local to Meetup; other pages keep their API contract.
export const fieldAliases = {
  deadline_at: 'recruit_end', starts_at: 'meeting_start',
  skill_ids: 'creator_skill_ids', creator_application: 'creator_skill_ids',
}
export function meetupErrorMessage(error, fallback = '요청을 처리하지 못했어요. 잠시 후 다시 시도해주세요.') {
  if (error?.status === 401) return '로그인 후 이용해주세요.'
  if (error?.status === 403) return '이 작업을 할 수 있는 권한이 없어요.'
  if (error?.status >= 500) return '잠시 연결이 원활하지 않아요. 잠시 후 다시 시도해주세요.'
  const message = error?.data?.detail ?? error?.message
  if (typeof message === 'string' && /서버 응답|백엔드|API 요청 실패/.test(message)) return fallback
  return typeof message === 'string' && /[가-힣]/.test(message)
    ? message.replace(/^Value error,\s*/i, '') : fallback
}
export function serverFieldErrors(error, form) {
  const errors = {}
  const items = error?.data?.detail
  if (Array.isArray(items)) {
    for (const item of items) {
      const path = item.loc?.[0] === 'body' ? item.loc.slice(1) : (item.loc || [])
      const key = path.find((key) => key in form || key in fieldAliases)
      if (key) errors[key === 'starts_at' && form.recruit_mode === 'regular' ? 'regular_start_date' : key === 'ends_at' && form.recruit_mode === 'short' ? 'meeting_end' : (fieldAliases[key] || key)] = item.type === 'missing'
        ? '이 항목을 입력해주세요.'
        : (/[가-힣]/.test(item.msg || '') ? item.msg.replace(/^Value error,\s*/i, '') : '입력값을 확인해주세요.')
    }
  }
  const message = typeof items === 'string' ? items : Array.isArray(items) ? items.map((i) => i.msg).join(' ') : ''
  if (/마감/.test(message)) errors.recruit_end = message.replace(/^Value error,\s*/i, '')
  if (/종료/.test(message)) errors[form.recruit_mode === 'regular' ? 'ends_at' : 'meeting_end'] = '종료 일시는 시작 일시보다 늦어야 해요.'
  if (/시작 24시간/.test(message)) errors[form.recruit_mode === 'regular' ? 'regular_start_date' : 'meeting_start'] = '모임은 시작 24시간 이전에 만들어주세요.'
  return errors
}
export function validateMeetupForm(form, { isEdit = false, program = true, isAdmin = false, now = Date.now() } = {}) {
  const errors = {}
  const required = (key, message) => { if (!String(form[key] ?? '').trim()) errors[key] = message }
  required('title', '모임 제목을 입력해주세요.')
  required('body', '모임 소개를 입력해주세요.')
  const capacity = Number(form.capacity)
  if (!Number.isInteger(capacity) || capacity < (program ? 2 : 1) || (program && capacity > 5)) {
    errors.capacity = program ? '모집 인원은 2~5명으로 입력해주세요.' : '모집 인원은 1명 이상으로 입력해주세요.'
  }
  if (!form.is_online) required('place', '오프라인 모임 장소를 입력해주세요.')
  if (!program || form.meeting_start || (form.regular_start_date && form.regular_time)) required('recruit_end', '모집 마감 일시를 선택해주세요.')
  const regular = form.recruit_mode === 'regular'
  const startKey = regular ? 'regular_start_date' : 'meeting_start'
  const endKey = regular ? 'ends_at' : 'meeting_end'
  const start = regular ? `${form.regular_start_date}T${form.regular_time}:00+09:00` : `${form.meeting_start}:00+09:00`
  const startMs = Date.parse(start)
  if (form.category !== 'group_buy') {
    required(startKey, '모임 시작 일시를 선택해주세요.')
    if (regular) {
      required('regular_time', '모임 시간을 선택해주세요.')
      if (!form.regular_days.length) errors.regular_days = '모임 요일을 하나 이상 선택해주세요.'
      if (form.regular_start_date && !form.regular_days.includes(['일','월','화','수','목','금','토'][new Date(`${form.regular_start_date}T12:00:00Z`).getUTCDay()])) {
        errors[isEdit && program ? 'regular_start_date' : 'regular_days'] = '시작 날짜의 요일을 모임 요일에 포함해주세요.'
      }
    }
    if (!regular || program) {
      required(endKey, '모임 종료 일시를 선택해주세요.')
      if (form[endKey] && Date.parse(`${form[endKey]}:00+09:00`) <= startMs) errors[endKey] = '종료 일시는 시작 일시보다 늦어야 해요.'
    }
    if (!isEdit && startMs <= now + (program ? 86400000 : 0)) errors[startKey] = program ? '시작까지 24시간 넘게 남은 일시를 선택해주세요.' : '미래의 시작 일시를 선택해주세요.'
    if (Date.parse(`${form.recruit_end}:00+09:00`) >= startMs) errors.recruit_end = '모집 마감일은 첫 모임 시작일보다 이전이어야 해요.'
    if (program && Number.isFinite(startMs) && form.recruit_end && Date.parse(`${form.recruit_end}:00+09:00`) !== startMs - 86400000) errors.recruit_end = '프로젝트·스터디 모집은 시작 24시간 전에 마감해요. 시작 일시를 선택하면 자동 설정돼요.'
  }
  if (!isEdit && Date.parse(`${form.recruit_end}:00+09:00`) <= now) errors.recruit_end = '미래의 모집 마감 일시를 선택해주세요.'
  if (form.category === 'study') required('study_topic', '스터디 주제를 입력해주세요.')
  if (form.category === 'project') {
    if (!form.required_skill_ids.length) errors.required_skill_ids = '프로젝트 필수 기술을 하나 이상 선택해주세요.'
    if (!isEdit && !isAdmin && (!form.creator_skill_ids.length || form.creator_skill_ids.some((id) => !form.required_skill_ids.includes(id)))) errors.creator_skill_ids = '필수 기술 중 내가 맡을 기술을 선택해주세요.'
  }
  if (form.category === 'sports') required('sport_name', '운동 종목을 입력해주세요.')
  if (form.category === 'game') required('game_name', '게임 이름을 입력해주세요.')
  if (form.category === 'group_buy') {
    required('product_name', '상품명을 입력해주세요.')
    required('pickup_method', '수령 방법을 입력해주세요.')
    required('estimated_price_per_person', '1인 예상 가격을 입력해주세요.')
    if (form.purchase_url && !/^https?:\/\//i.test(form.purchase_url)) errors.purchase_url = 'http 또는 https로 시작하는 구매 링크를 입력해주세요.'
  }
  return errors
}
export function pickPayload(payload, fields) {
  return Object.fromEntries(fields.filter((key) => key in payload).map((key) => [key, payload[key]]))
}
export const programCreateFields = ['title','body','category','recruit_mode','capacity','starts_at','ends_at','meeting_start','meeting_end','regular_days','regular_time','regular_start_date','deadline_at','required_skill_ids','creator_application','study_type','difficulty','study_topic','study_period','study_method','place','is_online','contact_method']
export const programEditFields = ['title','body','contact_method','capacity','starts_at','ends_at','required_skill_ids']
export const legacyEditFields = ['title','body','capacity','regular_days','regular_time','regular_start_date','meeting_start','meeting_end','deadline_at','place','is_online','sport_name','game_name','study_topic','study_period','study_method','product_name','purchase_url','estimated_price_per_person','pickup_method']

export const legacyCreateFields = [...legacyEditFields, 'category', 'recruit_mode', 'contact_method']

// Keep the server's fixed 24-hour deadline contract when editing from either side.
export function scheduleFromDeadline(form, deadline, { preserveWeekdays = false } = {}) {
  const instant = Date.parse(`${deadline}:00+09:00`)
  if (!Number.isFinite(instant)) return { recruit_end: deadline }
  const start = new Date(instant + 86400000)
  const wallTime = new Date(start.getTime() + 9 * 3600000).toISOString().slice(0, 16)
  if (form.recruit_mode !== 'regular') return { recruit_end: deadline, meeting_start: wallTime }
  const day = ['일', '월', '화', '수', '목', '금', '토'][new Date(`${wallTime.slice(0, 10)}T12:00:00Z`).getUTCDay()]
  return {
    recruit_end: deadline,
    regular_start_date: wallTime.slice(0, 10),
    regular_time: wallTime.slice(11, 16),
    regular_days: preserveWeekdays ? form.regular_days : [...new Set([...form.regular_days, day])],
  }
}
