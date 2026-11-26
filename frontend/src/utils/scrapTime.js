// =========================================================
// 스크랩 시각 해석·표시 (Issue #74)
// 공용 DB 세션 시간대가 UTC(GMT)라 시간대 없는 TIMESTAMP(DEFAULT CURRENT_TIMESTAMP)는 UTC 값이다.
// 커리어 댓글 시각(components/career/CareerReactions.jsx)과 같은 규칙으로,
// 시간대 표시가 없으면 UTC로 해석하고 화면에는 한국 시간(Asia/Seoul)으로 보여 준다.
// =========================================================

const HAS_TIMEZONE = /(?:Z|[+-]\d{2}:?\d{2})$/i

const KST_PARTS = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Seoul',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

/** 서버 시각 문자열 → epoch ms. 시간대가 없으면 UTC, 마이크로초는 밀리초까지만 읽는다. 해석 불가면 NaN */
export function parseServerTime(value) {
  if (!value) return Number.NaN
  const text = String(value).trim().replace(' ', 'T').replace(/(\.\d{3})\d+/, '$1')
  return Date.parse(HAS_TIMEZONE.test(text) ? text : `${text}Z`)
}

/** 서버 시각 → 한국 시간 'YYYY-MM-DD HH:mm' (마이페이지 기존 표시 형식과 같음) */
export function formatKstDateTime(value) {
  const time = parseServerTime(value)
  if (Number.isNaN(time)) return '날짜 정보 없음'
  const parts = Object.fromEntries(KST_PARTS.formatToParts(time).map((part) => [part.type, part.value]))
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`
}
