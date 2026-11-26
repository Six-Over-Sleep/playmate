// Only share an in-flight public metadata read; do not cache results across sessions.
export function createSharedMeetupRead(read) {
  let pending = null
  return () => {
    if (pending) return pending
    const task = Promise.resolve().then(read)
    pending = task
    const clear = () => { if (pending === task) pending = null }
    task.then(clear, clear)
    return task
  }
}

export function programAvailabilityMessage(capabilities) {
  if (!capabilities) return '모임 개설 가능 상태를 확인하고 있어요.'
  if (capabilities.programs_available) return ''
  return capabilities.reason === 'disabled'
    ? '프로젝트·스터디 모임 개설 기능이 현재 비활성화되어 있어요. 운동·게임·공동구매는 이용할 수 있어요.'
    : '프로젝트·스터디 모임 개설을 준비 중이에요. 준비가 끝난 후 다시 이용해주세요.'
}
