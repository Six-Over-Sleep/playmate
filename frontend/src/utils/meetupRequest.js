// 같은 회원의 진행 중인 목록 요청만 공유한다. 완료된 데이터는 캐시하지 않는다.
export function createMeetupRequestGate() {
  let pending = null
  let latest = null

  return {
    get(key, load, { force = false } = {}) {
      if (!force && pending?.key === key) return pending

      const request = {
        key,
        isCurrent: () => latest === request,
      }
      pending = latest = request
      request.promise = Promise.resolve().then(load)
      const clear = () => {
        if (pending === request) pending = null
      }
      request.promise.then(clear, clear)
      return request
    },
  }
}
