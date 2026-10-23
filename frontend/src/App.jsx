
import { useCallback, useEffect, useState } from 'react'

import LoginPage from './pages/auth/LoginPage'
import SignupPage from './pages/auth/SignupPage'
import Header from './components/layout/Header'
import BoardSection from './components/board/BoardSection'
import MeetupSection from './components/meetup/MeetupSection'
import MyPage from './pages/mypage/MyPage'

// 취업 카테고리 페이지
import CareerPage from './pages/career/CareerPage'

import { apiRequest } from './services/apiClient'
import { getAuthUrl } from './config/api'

export default function App() {
  const [authView, setAuthView] = useState('checking')
  const [section, setSection] = useState('board')
  const [boardKey, setBoardKey] = useState(0)
  const [nickname, setNickname] = useState('')
  const [avatarUrl, setAvatarUrl] = useState(null)

  // 서비스 진입
  const enterService = useCallback(() => {
    setSection('board')
    setAuthView('board')
  }, [])

  // 로그인 상태 확인
  const checkAuth = useCallback(async () => {
    try {
      const data = await apiRequest('/me', {
        urlBuilder: getAuthUrl,
        credentials: 'include',
      })

      if (data.signup_required) {
        setNickname('')
        setAvatarUrl(null)
        setAuthView('signup')
        return
      }

      setNickname(data.member?.nickname || '')
      setAvatarUrl(data.discord_user?.avatar_url || null)
      enterService()
    } catch (error) {
      if (error.status !== 401) {
        console.error(error)
      }

      setNickname('')
      setAvatarUrl(null)
      setAuthView('login')
    } finally {
      const url = new URL(window.location.href)

      if (url.searchParams.has('auth') || url.searchParams.has('signup')) {
        url.searchParams.delete('auth')
        url.searchParams.delete('signup')

        window.history.replaceState(
          {},
          '',
          `${url.pathname}${url.search}${url.hash}`,
        )
      }
    }
  }, [enterService])

  // 로그아웃
  const handleLogout = async () => {
    if (!window.confirm('정말 로그아웃 하시겠습니까?')) return

    try {
      await apiRequest('/logout', {
        urlBuilder: getAuthUrl,
        method: 'POST',
        credentials: 'include',
      })

      setNickname('')
      setAvatarUrl(null)
      setAuthView('login')
    } catch (error) {
      console.error(error)
      alert(error.message || '로그아웃 중 오류가 발생했습니다.')
    }
  }

  useEffect(() => {
    checkAuth()
  }, [checkAuth])

  // 상단 메뉴 이동
  const handleNavigate = (nextSection) => {
    setSection(nextSection)

    if (nextSection === 'board') {
      setBoardKey((prev) => prev + 1)
    }
  }

  // 로그인 확인 중
  if (authView === 'checking') {
    return (
      <main className="service-error">
        <p>로그인 상태를 확인하는 중...</p>
      </main>
    )
  }

  // 회원가입 화면
  if (authView === 'signup') {
    return (
      <SignupPage
        onBack={() => setAuthView('login')}
        onComplete={checkAuth}
      />
    )
  }

  // 로그인 후 서비스 화면
  if (authView === 'board') {
    return (
      <>
        {/* 공통 헤더 */}
        <Header
          activeSection={section}
          onNavigate={handleNavigate}
          nickname={nickname}
          avatarUrl={avatarUrl}
          onLogout={handleLogout}
        />

        {/* 게시판 */}
        {section === 'board' && (
          <BoardSection resetVersion={boardKey} />
        )}

        {/* 취업 카테고리 - 신규 추가 */}
        {section === 'career' && (
          <CareerPage />
        )}

        {/* 모임 */}
        {section === 'meetup' && (
          <MeetupSection />
        )}

        {/* 마이페이지 */}
        {section === 'mypage' && (
          <MyPage />
        )}
      </>
    )
  }

  // 로그인 화면
  return (
    <LoginPage
      onSignup={() => setAuthView('signup')}
      onDevEnter={enterService}
    />
  )
}
