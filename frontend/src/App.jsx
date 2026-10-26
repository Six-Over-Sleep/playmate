
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

    // 마이페이지에서 선택한 게시글 정보
    const [openPostTarget, setOpenPostTarget] = useState(null)

    // 마이페이지에서 선택한 모임 ID
    const [openMeetupTarget, setOpenMeetupTarget] = useState(null)
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

        // 로그인 확인 후 기존 페이지 유지
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

            // 이전 게시글 선택 초기화
            setOpenPostTarget(null)

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

        // 상단 메뉴로 이동할 때 이전 모임 상세 이동 요청 초기화
        setOpenMeetupTarget(null)

        // 이전 게시글 이동 요청 초기화
        setOpenPostTarget(null)

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
    // 10. 마이페이지 게시글 이동
    // =====================================================

    const handleOpenActivityPost = (item) => {
        if (!item?.post_id) return

        console.log(
            '마이페이지 클릭 데이터:',
            JSON.stringify(item, null, 2)
        )        

        // 취업 게시판 이름과 코드 매핑
        const careerBoardNames = {
            '취준 도감': 'reviews',
            '커리어 톡톡': 'talk',
            '현직자 라운지': 'lounge',
            '커리어 연구소': 'lab',
        }

        // API의 게시판 정보 확인
        const boardName = String(item.board_name ?? '').trim()

        const careerCategory =
            item.career_category ||
            item.category_code ||
            careerBoardNames[boardName] ||
            null

        const rawPostType = String(
            item.post_type ?? ''
        ).trim().toUpperCase()

        // 게시글 유형 판별
        const isCareer =
            rawPostType === 'CAREER' ||
            ['reviews', 'talk', 'lounge', 'lab'].includes(careerCategory)

        const isMeetup = rawPostType === 'RECRUIT'

        const isBoard =
            !isCareer &&
            !isMeetup &&
            item.board_id != null

        if (!isCareer && !isMeetup && !isBoard) {
            console.error('카테고리 정보 확인 실패:', item)
            alert('게시글의 카테고리 정보를 확인할 수 없습니다.')
            return
        }

        const target = {
            postId: item.post_id,
            boardId: item.board_id,
            postType: isCareer
                ? 'CAREER'
                : isMeetup
                    ? 'RECRUIT'
                    : rawPostType || 'BOARD',
            careerCategory: isCareer ? careerCategory : null,
        }

        console.log('게시글 이동 대상:', target)

        setOpenPostTarget(target)

        if (isCareer) {
            setSection('career')
        } else if (isMeetup) {
            setSection('meetup')
        } else {
            setSection('board')
        }
    }

    // 마이페이지 내 모임 → 모임 상세 이동
    const handleOpenActivityMeetup = (item) => {
        const recruitId = Number(item?.recruit_id)

        if (!Number.isInteger(recruitId) || recruitId <= 0) {
            alert('모임 정보를 확인할 수 없습니다.')
            return
        }

        setOpenMeetupTarget(recruitId)
        setSection('meetup')
        }

    // =====================================================
    // 11. 로그인 상태 확인 중
    // =====================================================

    if (authView === 'checking') {

        return (
            <main className="service-error">
                <p>로그인 상태를 확인하는 중...</p>
            </main>
        )
    }


    // =====================================================
    // 12. 회원가입 화면
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
    // 13. 로그인 후 서비스 화면
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
                        openPostTarget={openPostTarget}
                    />
                )}


                {/* 취업 카테고리 */}
                {section === 'career' && (
                    <CareerPage
                        openPostTarget={openPostTarget}
                    />
                )}


                {/* 모임 */}
                {section === 'meetup' && (
                <MeetupSection
                    openMeetupTarget={openMeetupTarget}
                />
                )}


                {/* 마이페이지 */}
                {section === 'mypage' && (
                <MyPage
                    onOpenPost={handleOpenActivityPost}
                    onOpenMeetup={handleOpenActivityMeetup}
                />
                )}

            </>
        )
    }


    // =====================================================
    // 14. 로그인 화면
    // =====================================================

    return (
        <LoginPage
            onSignup={() => setAuthView('signup')}
            onDevEnter={enterService}
        />
    )
}
