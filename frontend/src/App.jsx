
import { useCallback, useEffect, useState } from 'react'

import LoginPage from './pages/auth/LoginPage'
import SignupPage from './pages/auth/SignupPage'

import Header from './components/layout/Header'

import BoardSection from './components/board/BoardSection'
import MeetupSection from './components/meetup/MeetupSection'
import MyPage from './pages/mypage/MyPage'
import CareerPage from './pages/career/CareerPage'

import { apiRequest } from './services/apiClient'
import { getAuthUrl } from './config/api'


// =========================================================
// 1. 페이지 설정
// =========================================================

// 실제 App.jsx에서 지원하는 카테고리
const VALID_SECTIONS = [
    'board',
    'career',
    'meetup',
    'mypage',
]

// 마지막으로 방문한 페이지를 저장하는 키
const SECTION_STORAGE_KEY = 'playmate-section'


// =========================================================
// 2. 마지막 방문 페이지 가져오기
// =========================================================

function getSavedSection() {
    const savedSection = sessionStorage.getItem(
        SECTION_STORAGE_KEY
    )

    // 존재하는 카테고리만 복원
    if (VALID_SECTIONS.includes(savedSection)) {
        return savedSection
    }

    // 저장된 값이 없으면 자유 게시판
    return 'board'
}


// =========================================================
// 3. App
// =========================================================

export default function App() {

    // -----------------------------------------------------
    // 로그인 및 사용자 상태
    // -----------------------------------------------------

    const [authView, setAuthView] = useState('checking')

    const [nickname, setNickname] = useState('')

    const [avatarUrl, setAvatarUrl] = useState(null)


    // -----------------------------------------------------
    // 현재 페이지 상태
    // -----------------------------------------------------

    // 새로고침 시 마지막으로 방문한 카테고리 복원
    const [section, setSection] = useState(getSavedSection)

    const [boardKey, setBoardKey] = useState(0)


    // =====================================================
    // 4. 현재 페이지 저장
    // =====================================================

    useEffect(() => {
        sessionStorage.setItem(
            SECTION_STORAGE_KEY,
            section
        )
    }, [section])


    // =====================================================
    // 5. 서비스 진입
    // =====================================================

    const enterService = useCallback(() => {

        // 중요!
        // 기존 setSection('board') 제거
        // 로그인 확인 후에도 기존 페이지를 유지한다.

        setAuthView('board')

    }, [])


    // =====================================================
    // 6. 로그인 상태 확인
    // =====================================================

    const checkAuth = useCallback(async () => {

        try {
            const data = await apiRequest('/me', {
                urlBuilder: getAuthUrl,
                credentials: 'include',
            })

            // 회원가입이 필요한 사용자
            if (data.signup_required) {

                setNickname('')
                setAvatarUrl(null)

                setAuthView('signup')

                return
            }

            // 로그인한 사용자 정보 설정
            setNickname(
                data.member?.nickname || ''
            )

            setAvatarUrl(
                data.discord_user?.avatar_url || null
            )

            // 로그인 성공 후 기존 페이지 유지
            enterService()

        } catch (error) {

            if (error.status !== 401) {
                console.error(error)
            }

            setNickname('')
            setAvatarUrl(null)

            setAuthView('login')

        } finally {

            // Discord 인증 관련 URL 파라미터 정리
            const url = new URL(window.location.href)

            if (
                url.searchParams.has('auth') ||
                url.searchParams.has('signup')
            ) {
                url.searchParams.delete('auth')
                url.searchParams.delete('signup')

                window.history.replaceState(
                    {},
                    '',
                    `${url.pathname}${url.search}${url.hash}`
                )
            }
        }

    }, [enterService])


    // =====================================================
    // 7. 최초 로그인 상태 확인
    // =====================================================

    useEffect(() => {
        checkAuth()
    }, [checkAuth])


    // =====================================================
    // 8. 로그아웃
    // =====================================================

    const handleLogout = async () => {

        if (!window.confirm('정말 로그아웃 하시겠습니까?')) {
            return
        }

        try {
            await apiRequest('/logout', {
                urlBuilder: getAuthUrl,
                method: 'POST',
                credentials: 'include',
            })

            // 사용자 정보 초기화
            setNickname('')
            setAvatarUrl(null)

            // 로그아웃 후 기본 페이지로 초기화
            setSection('board')

            sessionStorage.removeItem(
                SECTION_STORAGE_KEY
            )

            setAuthView('login')

        } catch (error) {

            console.error(error)

            alert(
                error.message ||
                '로그아웃 중 오류가 발생했습니다.'
            )
        }
    }


    // =====================================================
    // 9. 상단 메뉴 이동
    // =====================================================

    const handleNavigate = (nextSection) => {

        // 유효하지 않은 카테고리는 무시
        if (!VALID_SECTIONS.includes(nextSection)) {
            return
        }

        // 현재 카테고리 변경
        setSection(nextSection)

        // 이동한 카테고리 즉시 저장
        sessionStorage.setItem(
            SECTION_STORAGE_KEY,
            nextSection
        )

        // 자유 게시판 이동 시 기존 초기화 동작 유지
        if (nextSection === 'board') {

            setBoardKey((prev) => prev + 1)
        }
    }


    // =====================================================
    // 10. 로그인 상태 확인 중
    // =====================================================

    if (authView === 'checking') {

        return (
            <main className="service-error">
                <p>로그인 상태를 확인하는 중...</p>
            </main>
        )
    }


    // =====================================================
    // 11. 회원가입 화면
    // =====================================================

    if (authView === 'signup') {

        return (
            <SignupPage
                onBack={() => setAuthView('login')}
                onComplete={checkAuth}
            />
        )
    }


    // =====================================================
    // 12. 로그인 후 서비스 화면
    // =====================================================

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


                {/* 자유 게시판 */}
                {section === 'board' && (
                    <BoardSection
                        resetVersion={boardKey}
                    />
                )}


                {/* 취업 카테고리 */}
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


    // =====================================================
    // 13. 로그인 화면
    // =====================================================

    return (
        <LoginPage
            onSignup={() => setAuthView('signup')}
            onDevEnter={enterService}
        />
    )
}
