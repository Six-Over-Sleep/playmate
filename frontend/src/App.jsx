import { useCallback, useEffect, useState } from 'react'
import LoginPage from './pages/auth/LoginPage'
import SignupPage from './pages/auth/SignupPage'
import Header from './components/layout/Header'
import BoardSection from './components/board/BoardSection'
import MeetupSection from './components/meetup/MeetupSection'
import { apiRequest } from './services/apiClient'
import { getAuthUrl } from './config/api'

export default function App() {
  const [authView, setAuthView] = useState('checking')
  const [section, setSection] = useState('board')
  const [boardKey, setBoardKey] = useState(0)
  const [nickname, setNickname] = useState('')
  const [avatarUrl, setAvatarUrl] = useState(null)

  const enterService = useCallback(() => {
    setSection('board')
    setAuthView('board')
  }, [])

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

  const handleNavigate = (nextSection) => {
    setSection(nextSection)

    if (nextSection === 'board') {
      setBoardKey((prev) => prev + 1)
    }
  }

  if (authView === 'checking') {
    return (
      <main className="service-error">
        <p>로그인 상태를 확인하는 중...</p>
      </main>
    )
  }

  if (authView === 'signup') {
    return (
      <SignupPage
        onBack={() => setAuthView('login')}
        onComplete={checkAuth}
      />
    )
  }

  if (authView === 'board') {
    return (
      <>
        <Header
          activeSection={section}
          onNavigate={handleNavigate}
          nickname={nickname}
          avatarUrl={avatarUrl}
          onLogout={handleLogout}
        />

        {section === 'board' && <BoardSection resetVersion={boardKey} />}

        {section === 'meetup' && <MeetupSection />}
      </>
    )
  }

  return (
    <LoginPage
      onSignup={() => setAuthView('signup')}
      onDevEnter={enterService}
    />
  )
}
