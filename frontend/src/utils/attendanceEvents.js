const ATTENDANCE_UPDATED_EVENT = 'playmate:attendance-updated'

// 출석이 서버에 기록된 뒤, 다른 화면의 상태를 다시 조회하도록 알립니다.
export function notifyMyAttendanceUpdated(result, target = globalThis) {
  target.dispatchEvent(new CustomEvent(ATTENDANCE_UPDATED_EVENT, { detail: result }))
}

export function onMyAttendanceUpdated(listener, target = globalThis) {
  const handler = (event) => listener(event.detail)
  target.addEventListener(ATTENDANCE_UPDATED_EVENT, handler)
  return () => target.removeEventListener(ATTENDANCE_UPDATED_EVENT, handler)
}
