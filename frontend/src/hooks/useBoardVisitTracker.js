import { useEffect, useRef } from 'react'
import { apiRequest } from '../services/apiClient'

function createVisitId() {
  if (globalThis.crypto.randomUUID) return globalThis.crypto.randomUUID()

  // getRandomValues is available in browsers served over ordinary HTTP.
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20),
  ].join('-')
}

/** 현재 보고 있는 게시판이 바뀌었을 때만 방문 횟수를 기록합니다. */
export default function useBoardVisitTracker(boardId) {
  const lastVisit = useRef(null)

  useEffect(() => {
    if (boardId === null || boardId === undefined) {
      lastVisit.current = null
      return
    }

    const key = String(boardId)
    const isSpecial = key === 'hot' || key === 'hall-of-fame'
    const isNormal = /^\d+$/.test(key) && Number(key) > 0

    if (!isSpecial && !isNormal) return

    if (lastVisit.current === key) return
    lastVisit.current = key

    apiRequest('/activity/board-view', {
      method: 'POST',
      credentials: 'include',
      body: JSON.stringify({ board_key: key, visit_id: createVisitId() }),
    }).catch(() => {
      // 통계 기록에 실패해도 게시판 이용은 정상적으로 유지합니다.
    })
  }, [boardId])
}
