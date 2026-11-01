import { useEffect, useRef } from 'react'
import { apiRequest } from '../services/apiClient'

// 페이지 새로고침 또는 개발 모드 재실행 시 중복 기록을 줄입니다.
const DUPLICATE_WINDOW = 30000

/** 현재 보고 있는 게시판이 바뀌었을 때만 방문 횟수를 기록합니다. */
export default function useBoardVisitTracker(boardId) {
  const lastVisit = useRef({ key: '', time: 0 })

  useEffect(() => {
    if (boardId === null || boardId === undefined) return

    const key = String(boardId)
    const isSpecial = key === 'hot' || key === 'hall-of-fame'
    const isNormal = /^\d+$/.test(key) && Number(key) > 0

    if (!isSpecial && !isNormal) return

    const now = Date.now()

    // React 개발 모드의 Effect 중복 실행을 방지합니다.
    if (
      lastVisit.current.key === key &&
      now - lastVisit.current.time < DUPLICATE_WINDOW
    ) {
      return
    }

    lastVisit.current = { key, time: now }

    apiRequest('/activity/board-view', {
      method: 'POST',
      credentials: 'include',
      body: JSON.stringify({ board_key: key }),
    }).catch(() => {
      // 통계 기록에 실패해도 게시판 이용은 정상적으로 유지합니다.
    })
  }, [boardId])
}
