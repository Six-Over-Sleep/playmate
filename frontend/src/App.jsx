import { useCallback, useEffect, useState } from 'react'
import {
  BrowserRouter,
  useLocation,
  useNavigate,
} from 'react-router-dom'

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

const VALID_SECTIONS = [
  'board',
  'career',
  'meetup',
  'mypage',
  'admin',
]

const SECTION_STORAGE_KEY = 'playmate-section'

function getSavedSection() {
  const savedSection = sessionStorage.getItem(
    SECTION_STORAGE_KEY,
  )

  return VALID_SECTIONS.includes(savedSection)
    ? savedSection
    : 'board'
}

function getSectionFromPath(pathname) {
  const firstPart = pathname
    .split('/')
    .filter(Boolean)[0]

  return VALID_SECTIONS.includes(firstPart)
    ? firstPart
    : null
}

function AppContent() {
  const location = useLocation()
  const navigate = useNavigate()

  // =========================================================
  // 인증 / 회원 상태
  // =========================================================

  const [authView, setAuthView] = useState('checking')

  const [nickname, setNickname] = useState('')
  const [roleCode, setRoleCode] = useState('')

  // 과정 게시판 분류에는 관리자 작성 권한이 아닌
  // 실제 소속 정보를 사용합니다.
  const [memberCourse, setMemberCourse] = useState(null)
  const [memberCohort, setMemberCohort] = useState(null)

  const [avatarUrl, setAvatarUrl] = useState(null)

  // 개발용 관리자 직접 진입 여부
  const [devAdminMode, setDevAdminMode] = useState(false)

  // =========================================================
  // 화면 상태
  // =========================================================

  const [savedSection, setSavedSection] = useState(
    getSavedSection,
  )

  const section =
    getSectionFromPath(location.pathname) ||
    savedSection

  const meetupMatch =
    location.pathname.match(
      /^\/meetup\/(\d+)\/?$/,
    )

  const targetMeetupId = meetupMatch
    ? Number(meetupMatch[1])
    : null

  const [boardKey, setBoardKey] = useState(0)

  // =========================================================
  // 현재 섹션 저장
  // =========================================================

  useEffect(() => {
    sessionStorage.setItem(
      SECTION_STORAGE_KEY,
      section,
    )
  }, [section])

  // =========================================================
  // 서비스 진입
  // =========================================================

  const enterService = useCallback(() => {
    setAuthView('board')
  }, [])

  // =========================================================
  // 로그인 상태 확인
  // =========================================================

  const checkAuth = useCallback(async () => {
    // 개발 관리자 모드에서는 실제 인증 확인 생략
    if (devAdminMode) {
      return
    }

    try {
      const data = await apiRequest('/me', {
        urlBuilder: getAuthUrl,
        credentials: 'include',
      })

      // 추가 회원가입 정보가 필요한 경우
      if (data.signup_required) {
        setNickname('')
        setRoleCode('')
        setMemberCourse(null)
        setMemberCohort(null)
        setAvatarUrl(null)

        setAuthView('signup')

        return
      }

      // 로그인 회원 정보 저장
      setNickname(
        data.member?.nickname || '',
      )

      setRoleCode(
        (
          data.member?.role_code || ''
        ).toUpperCase(),
      )

      setMemberCourse(
        data.member?.course ?? null,
      )

      setMemberCohort(
        data.member?.cohort ?? null,
      )

      setAvatarUrl(
        data.discord_user?.avatar_url ||
          null,
      )

      enterService()

    } catch (error) {
      if (error.status !== 401) {
        console.error(error)
      }

      setNickname('')
      setRoleCode('')
      setMemberCourse(null)
      setMemberCohort(null)
      setAvatarUrl(null)

      setAuthView('login')

    } finally {
      // Discord 인증에 사용한 임시 쿼리 파라미터 제거
      const url =
        new URL(window.location.href)

      if (
        url.searchParams.has('auth') ||
        url.searchParams.has('signup')
      ) {
        url.searchParams.delete('auth')
        url.searchParams.delete('signup')

        window.history.replaceState(
          window.history.state,
          '',
          `${url.pathname}${url.search}${url.hash}`,
        )
      }
    }
  }, [
    enterService,
    devAdminMode,
  ])

  useEffect(() => {
    checkAuth()
  }, [checkAuth])

  // =========================================================
  // 개발 환경 관리자 진입
  // =========================================================

  const handleDevAdmin = () => {
    if (!import.meta.env.DEV) {
      return
    }

    // 개발용 관리자 상태
    setDevAdminMode(true)

    setRoleCode('ADMIN')
    setNickname('관리자')

    setMemberCourse(null)
    setMemberCohort(null)
    setAvatarUrl(null)

    // 관리자 페이지로 바로 가지 않고 게시판으로 진입
    setSavedSection('board')

    sessionStorage.setItem(
      SECTION_STORAGE_KEY,
      'board',
    )

    navigate('/board')

    setAuthView('board')
  }

  // =========================================================
  // 로그아웃
  // =========================================================

  const handleLogout = async () => {
    if (
      !window.confirm(
        '정말 로그아웃 하시겠습니까?',
      )
    ) {
      return
    }

    // 개발 관리자 모드
    if (devAdminMode) {
      setDevAdminMode(false)

      setNickname('')
      setRoleCode('')
      setMemberCourse(null)
      setMemberCohort(null)
      setAvatarUrl(null)

      setSavedSection('board')

      sessionStorage.removeItem(
        SECTION_STORAGE_KEY,
      )

      navigate('/')

      setAuthView('login')

      return
    }

    try {
      await apiRequest('/logout', {
        urlBuilder: getAuthUrl,
        method: 'POST',
        credentials: 'include',
      })

      setNickname('')
      setRoleCode('')
      setMemberCourse(null)
      setMemberCohort(null)
      setAvatarUrl(null)

      setSavedSection('board')

      sessionStorage.removeItem(
        SECTION_STORAGE_KEY,
      )

      navigate('/')

      setAuthView('login')

    } catch (error) {
      console.error(error)

      alert(
        error.message ||
          '로그아웃 중 오류가 발생했습니다.',
      )
    }
  }

  // =========================================================
  // 상단 메뉴 이동
  // =========================================================

  const handleNavigate = (
    nextSection,
  ) => {
    if (
      !VALID_SECTIONS.includes(
        nextSection,
      ) ||
      (
        nextSection === 'admin' &&
        roleCode !== 'ADMIN'
      )
    ) {
      return
    }

    navigate(`/${nextSection}`)

    setSavedSection(nextSection)

    sessionStorage.setItem(
      SECTION_STORAGE_KEY,
      nextSection,
    )

    // 게시판 초기화
    if (nextSection === 'board') {
      setBoardKey(
        (prev) => prev + 1,
      )
    }
  }

  // =========================================================
  // 모임 상세 이동
  // =========================================================

  const handleOpenMeetup = (
    recruitId,
  ) => {
    const id = Number(recruitId)

    if (
      !Number.isSafeInteger(id) ||
      id <= 0
    ) {
      console.error(
        '잘못된 모임 ID:',
        recruitId,
      )

      return
    }

    setSavedSection('meetup')

    sessionStorage.setItem(
      SECTION_STORAGE_KEY,
      'meetup',
    )

    navigate(`/meetup/${id}`)
  }

  // =========================================================
  // 마이페이지 활동 → 원본 게시글
  // =========================================================

  const handleOpenActivityPost = (
    item,
  ) => {
    if (!item) {
      return
    }

    const recruitId =
      Number(item.recruit_id)

    const postId =
      Number(item.post_id)

    const boardId =
      Number(item.board_id)

    const postType =
      String(
        item.post_type || '',
      )
        .trim()
        .toUpperCase()

    // 모임 게시글
    if (
      Number.isSafeInteger(
        recruitId,
      ) &&
      recruitId > 0
    ) {
      handleOpenMeetup(recruitId)

      return
    }

    if (
      postType === 'RECRUIT'
    ) {
      return
    }

    if (
      !Number.isSafeInteger(postId) ||
      postId <= 0
    ) {
      return
    }

    const categoryByName = {
      '취준도감': 'reviews',
      '취준 도감': 'reviews',
      '커리어 톡톡': 'talk',
      '현직자 라운지': 'lounge',
      '커리어 연구소': 'lab',
    }

    const category =
      String(
        item.career_category ||
          item.category_code ||
          categoryByName[
            item.board_name
          ] ||
          '',
      )
        .trim()
        .toLowerCase()

    const careerCategories = [
      'reviews',
      'talk',
      'lounge',
      'lab',
    ]

    const isCareer =
      postType === 'CAREER' ||
      careerCategories.includes(
        category,
      )

    let url
    let nextSection

    // 취업 게시글
    if (isCareer) {
      if (
        !careerCategories.includes(
          category,
        )
      ) {
        alert(
          '취업 게시글의 카테고리 정보를 확인할 수 없습니다.',
        )

        return
      }

      nextSection = 'career'

      url =
        `/career/${category}/${postId}`

    // 일반 게시판
    } else if (
      Number.isSafeInteger(
        boardId,
      ) &&
      boardId > 0
    ) {
      nextSection = 'board'

      url =
        `/board/${boardId}/posts/${postId}`

    } else {
      alert(
        '원본 게시글의 위치를 확인할 수 없습니다.',
      )

      return
    }

    setSavedSection(nextSection)

    sessionStorage.setItem(
      SECTION_STORAGE_KEY,
      nextSection,
    )

    navigate(url)
  }

  // =========================================================
  // 로그인 상태 확인 중
  // =========================================================

  if (
    authView === 'checking'
  ) {
    return (
      <main className="service-error">
        <p>
          로그인 상태를 확인하는 중...
        </p>
      </main>
    )
  }

  // =========================================================
  // 회원가입
  // =========================================================

  if (
    authView === 'signup'
  ) {
    return (
      <SignupPage
        onBack={() =>
          setAuthView('login')
        }
        onComplete={checkAuth}
      />
    )
  }

  // =========================================================
  // 서비스
  // =========================================================

  if (
    authView === 'board'
  ) {
    // 관리자 페이지 접근 방어
    if (
      section === 'admin' &&
      roleCode !== 'ADMIN'
    ) {
      return (
        <main className="service-error">
          <h1>
            접근 권한이 없습니다.
          </h1>

          <p>
            관리자 계정만 관리자 페이지에 접근할 수 있습니다.
          </p>

          <button
            className="button purple"
            onClick={() =>
              navigate('/board')
            }
          >
            게시판으로 돌아가기
          </button>
        </main>
      )
    }

    return (
      <>
        <Header
          activeSection={section}
          onNavigate={
            handleNavigate
          }
          nickname={nickname}
          avatarUrl={avatarUrl}
          isAdmin={
            roleCode === 'ADMIN'
          }
          onLogout={handleLogout}
        />

        <ActivityTracker />

        {section === 'board' && (
          <BoardSection
            resetVersion={
              boardKey
            }
            memberCourse={
              memberCourse
            }
            memberCohort={
              memberCohort
            }
          />
        )}

        {section === 'admin' &&
          roleCode === 'ADMIN' && (
            <AdminPage />
          )}

        {section === 'career' && (
          <CareerPage />
        )}

        {section === 'meetup' && (
          <MeetupSection
            targetMeetupId={
              targetMeetupId
            }
          />
        )}

        {section === 'mypage' && (
          <MyPage
            onOpenMeetup={
              handleOpenMeetup
            }
            onOpenPost={
              handleOpenActivityPost
            }
            avatarUrl={avatarUrl}
          />
        )}
      </>
    )
  }

  // =========================================================
  // 로그인 화면
  // =========================================================

  return (
    <LoginPage
      onSignup={() =>
        setAuthView('signup')
      }
      onDevAdmin={
        handleDevAdmin
      }
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