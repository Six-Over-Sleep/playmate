import useActivityTracker from '../../hooks/useActivityTracker'

/** 로그인한 회원에게만 활동 시간 측정을 적용합니다. */
export default function ActivityTracker() {
  useActivityTracker()
  return null
}
