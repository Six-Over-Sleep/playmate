
import { useEffect, useRef, useState } from 'react'
import { checkMyAttendance, getMyAttendance } from '../../services/mypageApi'
import { onMyAttendanceUpdated } from '../../utils/attendanceEvents'
import playmateLogo from '../../assets/playmate-logo.png'

export default function Header({
  activeSection,
  onNavigate,
  nickname,
  avatarUrl,
  onLogout,
  isAdmin = false,
}) {
  const [profileOpen, setProfileOpen] = useState(false)
  const [attendance, setAttendance] = useState(null)
  const [attendanceLoading, setAttendanceLoading] = useState(false)
  const [attendanceError, setAttendanceError] = useState('')
  const [attendanceMessage, setAttendanceMessage] = useState('')
  const [checkingAttendance, setCheckingAttendance] = useState(false)
  const [attendanceReloadKey, setAttendanceReloadKey] = useState(0)
  const attendancePending = useRef(false)

  // 메뉴를 열었을 때만 조회합니다. 다른 화면에서 출석해도 상태를 동기화합니다.
  useEffect(() => {
    if (!profileOpen) return undefined

    let active = true
    let requestVersion = 0

    const refreshAttendance = () => {
      const version = ++requestVersion
      setAttendanceLoading(true)
      setAttendanceError('')

      getMyAttendance()
        .then((result) => {
          if (!active || requestVersion !== version) return
          setAttendance(result)
        })
        .catch((error) => {
          if (!active || requestVersion !== version) return
          setAttendanceError(error.message || '출석 현황을 확인하지 못했습니다.')
        })
        .finally(() => {
          if (active && requestVersion === version) setAttendanceLoading(false)
        })
    }

    setAttendance(null)
    setAttendanceMessage('')
    refreshAttendance()

    const unsubscribe = onMyAttendanceUpdated(() => {
      if (!active) return
      // 서버가 POST를 성공 처리했다면 GET이 지연되어도 중복 출석을 허용하지 않습니다.
      setAttendance((previous) => ({ ...previous, attended_today: true }))
      refreshAttendance()
    })

    return () => {
      active = false
      unsubscribe()
    }
  }, [profileOpen, attendanceReloadKey])

  const handleAttendance = async () => {
    if (attendancePending.current || attendance?.attended_today || attendanceLoading) return
    attendancePending.current = true
    setCheckingAttendance(true)
    setAttendanceError('')
    setAttendanceMessage('')

    try {
      const result = await checkMyAttendance()
      const earned = Number(result?.earned_xp || 0) + Number(result?.bonus_xp || 0)
      setAttendanceMessage(
        result?.awarded ? `출석 완료! +${earned} XP` : '오늘은 이미 출석했어요.',
      )
    } catch (error) {
      setAttendanceError(error.message || '출석 처리에 실패했습니다.')
    } finally {
      attendancePending.current = false
      setCheckingAttendance(false)
    }
  }

  const go = (section) => {
    setProfileOpen(false)
    onNavigate?.(section)
  }

  return (
    <header className={`app-header${activeSection !== 'home' ? ' app-header--with-nav' : ''}`}>
      <div className="app-header-inner">
        <a
          className="brand"
          href="/"
          aria-label="PlayMate 홈"
          onClick={(event) => {
            event.preventDefault()
            go('home')
          }}
        >
          <img className="brand-logo" src={playmateLogo} alt="PlayMate" />
        </a>

        {activeSection !== 'home' && (
        <nav className="app-nav" aria-label="주 메뉴">
          {[
            { section: 'board', label: '게시판' },
            { section: 'meetup', label: '모임' },
            { section: 'career', label: '취업' },
            { section: 'growth', label: '성장' },
          ].map(({ section, label }) => (
            <button
              key={section}
              type="button"
              className={activeSection === section ? 'active' : ''}
              onClick={() => go(section)}
            >
              {label}
            </button>
          ))}
          {isAdmin && (
            <button type="button" className={activeSection === 'admin' ? 'active' : ''} onClick={() => go('admin')}>
              ⚙ 관리자
            </button>
          )}
        </nav>
        )}

        <div className="profile-container">
          <span className="header-notification-icon" aria-hidden="true">
            <svg
              className="header-bell-svg"
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              strokeLinejoin="round"
              focusable="false"
            >
              <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
              <path d="M10 21h4" />
            </svg>
          </span>
          <button
            type="button"
            className="profile-avatar"
            aria-label="프로필 메뉴"
            aria-expanded={profileOpen}
            aria-haspopup="menu"
            onClick={() => setProfileOpen((open) => !open)}
          >
            {avatarUrl ? (
              <img
                src={avatarUrl}
                alt=""
                className="profile-avatar-image"
              />
            ) : (
              nickname?.charAt(0) || 'U'
            )}
          </button>

          {profileOpen && (
            <div className="profile-dropdown profile-dropdown--attendance">
              <div className="profile-user-info">
                {avatarUrl ? (
                  <img
                    src={avatarUrl}
                    alt="Discord 프로필 사진"
                    className="profile-user-avatar"
                  />
                ) : (
                  <div className="profile-user-avatar profile-user-fallback">
                    {nickname?.charAt(0) || 'U'}
                  </div>
                )}

                <span className="profile-nickname">
                  {nickname || '사용자'}
                </span>
              </div>

              <hr />

              <section className="profile-attendance" aria-label="오늘의 출석체크">
                <div className="profile-attendance-heading">
                  <strong>📅 오늘의 출석체크</strong>
                  <span className={`profile-attendance-badge${attendance?.attended_today ? ' is-complete' : ''}`}>
                    {attendanceLoading && !attendance ? '확인 중' : attendance?.attended_today ? '출석 완료' : attendanceError && !attendance ? '조회 실패' : '미출석'}
                  </span>
                </div>
                <p className="profile-attendance-description">
                  {attendanceLoading && !attendance
                    ? '출석 현황을 불러오는 중...'
                    : attendance?.attended_today
                      ? `오늘 출석 완료${attendance.streak_days != null ? ` · 연속 ${attendance.streak_days}일` : ''}`
                      : attendance
                        ? `출석하고 XP를 받아보세요${attendance.streak_days ? ` · 연속 ${attendance.streak_days}일` : ''}`
                        : '오늘의 출석 여부를 확인해 주세요.'}
                </p>
                <button
                  type="button"
                  className="profile-attendance-action"
                  onClick={handleAttendance}
                  disabled={checkingAttendance || attendanceLoading || !attendance || attendance.attended_today}
                >
                  {checkingAttendance ? '출석 처리 중...' : attendance?.attended_today ? '✓ 오늘 출석 완료' : '출석체크 하기'}
                </button>
                {attendanceMessage && <p className="profile-attendance-feedback" role="status">{attendanceMessage}</p>}
                {attendanceError && (
                  <div className="profile-attendance-error" role="alert">
                    <span>{attendanceError}</span>
                    {!attendance?.attended_today && !checkingAttendance && (
                      <button type="button" className="profile-attendance-retry" onClick={() => setAttendanceReloadKey((value) => value + 1)}>
                        다시 조회
                      </button>
                    )}
                  </div>
                )}
              </section>

              <hr />

              <button
                type="button"
                onClick={() => go('mypage')}
              >
                마이페이지
              </button>

              <button
                type="button"
                onClick={() => {
                  setProfileOpen(false)
                  onLogout?.()
                }}
              >
                로그아웃
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
