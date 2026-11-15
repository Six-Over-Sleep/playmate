const LEVEL_UPDATED_EVENT = 'playmate:mypage-level-updated'

// 출석 등으로 레벨이 바뀌면 같은 화면의 다른 레벨 표시(상단 미리보기 등)에 새 값을 알립니다.
export function notifyMyLevelUpdated(level, target = globalThis) {
  target.dispatchEvent(new CustomEvent(LEVEL_UPDATED_EVENT, { detail: level }))
}

// 구독을 해제하는 함수를 돌려줍니다.
export function onMyLevelUpdated(listener, target = globalThis) {
  const handler = (event) => listener(event.detail)
  target.addEventListener(LEVEL_UPDATED_EVENT, handler)
  return () => target.removeEventListener(LEVEL_UPDATED_EVENT, handler)
}
