import { useEffect } from 'react'
import { apiRequest } from '../services/apiClient'

// 15초마다 활동 여부를 확인하고, 60초 이상 입력이 없으면 일시 중지합니다.
const PING_INTERVAL = 15000
const IDLE_TIMEOUT = 60000

export default function useActivityTracker() {
  useEffect(() => {
    let lastAction = performance.now()
    let pending = false

    // 페이지에서 스크롤·입력·클릭 등 활동이 발생하면 마지막 활동 시간을 갱신합니다.
    const markActive = () => {
      lastAction = performance.now()
    }

    const sendPing = async () => {
      const isVisible = document.visibilityState === 'visible'
      const hasFocus = document.hasFocus()
      const isActive = performance.now() - lastAction < IDLE_TIMEOUT

      if (!isVisible || !hasFocus || !isActive || pending) return

      pending = true

      try {
        await apiRequest('/activity/ping', {
          method: 'POST',
          credentials: 'include',
        })
      } catch {
        // 활동 기록 실패가 커뮤니티 기능 사용에 영향을 주지 않도록 합니다.
      } finally {
        pending = false
      }
    }

    const events = ['pointerdown', 'keydown', 'scroll', 'touchstart']

    events.forEach((eventName) => {
      window.addEventListener(eventName, markActive, { passive: true })
    })
    window.addEventListener('focus', markActive)

    const timer = window.setInterval(sendPing, PING_INTERVAL)

    return () => {
      window.clearInterval(timer)
      events.forEach((eventName) => {
        window.removeEventListener(eventName, markActive)
      })
      window.removeEventListener('focus', markActive)
    }
  }, [])
}
