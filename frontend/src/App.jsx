import { useCallback, useEffect, useState } from 'react'
import { BrowserRouter, useLocation, useNavigate } from 'react-router-dom'

import LoginPage from './pages/auth/LoginPage'
import SignupPage from './pages/auth/SignupPage'
import Header from './components/layout/Header'
import ActivityTracker from './components/admin/ActivityTracker'
import BoardSection from './components/board/BoardSection'
import AdminPage from './pages/admin/AdminPage'
import MeetupSection from './components/meetup/MeetupSection'
import MyPage from './pages/mypage/MyPage'
import CareerPage from './pages/career/CareerPage'
import { apiRequest } from './services/apiClient'
import { getAuthUrl } from './config/api'

const VALID_SECTIONS = ['board', 'career', 'meetup', 'mypage', 'admin']
const SECTION_STORAGE_KEY = 'playmate-section'

function getSavedSection() {
    const savedSection = sessionStorage.getItem(SECTION_STORAGE_KEY)
    return VALID_SECTIONS.includes(savedSection) ? savedSection : 'board'
}

function getSectionFromPath(pathname) {
    const firstPart = pathname.split('/').filter(Boolean)[0]
    return VALID_SECTIONS.includes(firstPart) ? firstPart : null
}

function AppContent() {
    const location = useLocation()
    const navigate = useNavigate()

    const [authView, setAuthView] = useState('checking')
    const [nickname, setNickname] = useState('')
    const [roleCode, setRoleCode] = useState('')
    const [avatarUrl, setAvatarUrl] = useState(null)

    const [savedSection, setSavedSection] = useState(getSavedSection)
    const section = getSectionFromPath(location.pathname) || savedSection
    const meetupMatch = location.pathname.match(/^\/meetup\/(\d+)\/?$/)

    const targetMeetupId = meetupMatch
        ? Number(meetupMatch[1])
        : null
    const [boardKey, setBoardKey] = useState(0)

    // 마이페이지에서 선택한 모임 상세 ID

    useEffect(() => {
        sessionStorage.setItem(SECTION_STORAGE_KEY, section)
    }, [section])

    const enterService = useCallback(() => {
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
                setRoleCode('')
                setAvatarUrl(null)
                setAuthView('signup')
                return
            }

            setNickname(data.member?.nickname || '')
            setRoleCode((data.member?.role_code || '').toUpperCase())
            setAvatarUrl(data.discord_user?.avatar_url || null)
            enterService()
        } catch (error) {
            if (error.status !== 401) console.error(error)
            setNickname('')
            setRoleCode('')
            setAvatarUrl(null)
            setAuthView('login')
        } finally {
            // Discord 인증에 사용한 임시 쿼리 파라미터만 제거
            const url = new URL(window.location.href)
            if (url.searchParams.has('auth') || url.searchParams.has('signup')) {
                url.searchParams.delete('auth')
                url.searchParams.delete('signup')
                window.history.replaceState(
                    window.history.state,
                    '',
                    `${url.pathname}${url.search}${url.hash}`
                )
            }
        }
    }, [enterService])

    useEffect(() => {
        checkAuth()
    }, [checkAuth])

    const handleLogout = async () => {
        if (!window.confirm('정말 로그아웃 하시겠습니까?')) return

        try {
            await apiRequest('/logout', {
                urlBuilder: getAuthUrl,
                method: 'POST',
                credentials: 'include',
            })

            setNickname('')
            setRoleCode('')
            setAvatarUrl(null)
            setSavedSection('board')
            sessionStorage.removeItem(SECTION_STORAGE_KEY)
            navigate('/')
            setAuthView('login')
        } catch (error) {
            console.error(error)
            alert(error.message || '로그아웃 중 오류가 발생했습니다.')
        }
    }

    // 상단 메뉴 이동
    const handleNavigate = (nextSection) => {
        if (!VALID_SECTIONS.includes(nextSection) || (nextSection === 'admin' && roleCode !== 'ADMIN')) {
            return
        }

        console.log('페이지 이동:', nextSection)

        // React Router로 페이지 이동
        navigate(`/${nextSection}`)

        // 현재 카테고리 저장
        setSavedSection(nextSection)
        sessionStorage.setItem(
            SECTION_STORAGE_KEY,
            nextSection
        )

        // 게시판 초기화
        if (nextSection === 'board') {
            setBoardKey((prev) => prev + 1)
        }
    }

    // 모임 관련 댓글/스크랩 클릭 → 해당 모임 상세 화면
    const handleOpenMeetup = (recruitId) => {
        const id = Number(recruitId)

        if (!Number.isSafeInteger(id) || id <= 0) {
            console.error('잘못된 모임 ID:', recruitId)
            return
        }

        setSavedSection('meetup')
        sessionStorage.setItem(SECTION_STORAGE_KEY, 'meetup')

        // 목록이 아니라 해당 모임의 상세 주소로 이동
        navigate(`/meetup/${id}`)
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
        if (section === 'admin' && roleCode !== 'ADMIN') {
            return (
                <main className="service-error">
                    <h1>접근 권한이 없습니다.</h1>
                    <p>관리자 계정만 관리자 페이지에 접근할 수 있습니다.</p>
                    <button className="button purple" onClick={() => navigate('/board')}>
                        게시판으로 돌아가기
                    </button>
                </main>
            )
        }
        return (
            <>
                <Header
                    activeSection={section}
                    onNavigate={handleNavigate}
                    nickname={nickname}
                    avatarUrl={avatarUrl}
                    isAdmin={roleCode === 'ADMIN'}
                    onLogout={handleLogout}
                />

                <ActivityTracker />

                {section === 'board' && (
                    <BoardSection resetVersion={boardKey} />
                )}

                {section === 'admin' && roleCode === 'ADMIN' && <AdminPage />}

                {section === 'career' && <CareerPage />}

                {section === 'meetup' && (
                    <MeetupSection targetMeetupId={targetMeetupId} />
                )}

                {section === 'mypage' && (
                    <MyPage onOpenMeetup={handleOpenMeetup} />
                )}
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

export default function App() {
    return (
        <BrowserRouter>
            <AppContent />
        </BrowserRouter>
    )
}
