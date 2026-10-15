import { useCallback, useEffect, useState } from 'react'
import LoginPage from './pages/auth/LoginPage'
import SignupPage from './pages/auth/SignupPage'
import MeetupPage from './pages/meetup/MeetupPage'
import MeetupDetailPage from './pages/meetup/MeetupDetailPage'
import MeetupEditorPage from './pages/meetup/MeetupEditorPage'
import { meetupApi } from './services/meetupApi'
import Header from './components/layout/Header'
import BoardSection from './components/board/BoardSection'

const API_BASE_URL = 'http://localhost:8000'

export default function App() {
  const [authView, setAuthView] = useState('checking')
  const [section, setSection] = useState('board')
  const [boardKey, setBoardKey] = useState(0)

  const enterService = useCallback(() => {
    setSection('board')
    setAuthView('board')
  }, [])

  const checkAuth = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/auth/me`, {
        credentials: 'include',
      })

      if (response.status === 401) {
        setAuthView('login')
        return
      }

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail || '로그인 상태를 확인하지 못했습니다.')
      }

      if (data.signup_required) {
        setAuthView('signup')
        return
      }

      enterService()
    } catch (error) {
      console.error(error)
      setAuthView('login')
    } finally {
      const url = new URL(window.location.href)

      if (url.searchParams.has('auth') || url.searchParams.has('signup')) {
        url.searchParams.delete('auth')
        url.searchParams.delete('signup')
        window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
      }
    }
  }, [enterService])

  useEffect(() => {
    checkAuth()
  }, [checkAuth])

  const handleNavigate = (nextSection) => {
    setSection(nextSection)

    // 게시판 메뉴는 목록으로 돌아가되 컴포넌트를 재마운트해 다시 조회하지 않는다.
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
        onComplete={enterService}
      />
    )
  }

  if (authView === 'board') {
    return (
      <>
        <Header
          activeSection={section}
          onNavigate={handleNavigate}
        />

        {section === 'board' && (
          <BoardSection resetVersion={boardKey} />
        )}

        {section === 'meetup' && (
          <MeetupSection />
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

function MeetupSection() {
  const [meetups, setMeetups] = useState([])
  const [selectedMeetup, setSelectedMeetup] = useState(null)
  const [view, setView] = useState('list')
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [members, setMembers] = useState([])
  const [memberCount, setMemberCount] = useState(0)
  const [joined, setJoined] = useState(false)
  const [error, setError] = useState('')

  const normalizeCount = (data) => {
    if (typeof data === 'number') return data
    return Number(data?.current_members ?? data?.count ?? data?.member_count ?? data?.current_count ?? data?.participant_count ?? 0)
  }

  const loadMeetups = async () => {
    setLoading(true)
    try {
      const data = await meetupApi.list()
      const withCounts = await Promise.all(data.map(async (meetup) => {
        try {
          return { ...meetup, participant_count: normalizeCount(await meetupApi.count(meetup.recruit_id)) }
        } catch (err) {
          console.error(err)
          return { ...meetup, participant_count: 0 }
        }
      }))
      setMeetups(withCounts)
    } catch (err) {
      console.error(err)
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadMeetups() }, [])

  const loadParticipation = async (recruitId) => {
    const [memberData, countData] = await Promise.all([meetupApi.members(recruitId), meetupApi.count(recruitId)])
    const memberList = Array.isArray(memberData) ? memberData : memberData?.members || []
    setMembers(memberList)
    setMemberCount(normalizeCount(countData))
    setJoined(memberList.some((member) => Number(member?.member_id ?? member?.id) === -1))
  }

  const openMeetup = async (meetup) => {
    setDetailLoading(true)
    setError('')
    try {
      const detail = await meetupApi.detail(meetup.recruit_id)
      setSelectedMeetup(detail)
      await loadParticipation(meetup.recruit_id)
      setView('detail')
    } catch (err) {
      console.error(err)
      setError(err.message)
    } finally {
      setDetailLoading(false)
    }
  }

  const goBack = () => {
    setSelectedMeetup(null)
    setMembers([])
    setMemberCount(0)
    setJoined(false)
    setView('list')
    setError('')
  }

  const openWrite = () => {
    setSelectedMeetup(null)
    setError('')
    setView('editor')
  }

  const openEdit = async () => {
    if (!selectedMeetup?.recruit_id) return
    setDetailLoading(true)
    setError('')
    try {
      setSelectedMeetup(await meetupApi.detail(selectedMeetup.recruit_id))
      setView('editor')
    } catch (err) {
      console.error(err)
      setError(err.message)
    } finally {
      setDetailLoading(false)
    }
  }

  const createMeetup = async (payload) => {
    setBusy(true)
    setError('')
    try {
      const created = await meetupApi.create(payload)
      await loadMeetups()
      if (created?.recruit_id) {
        setSelectedMeetup(await meetupApi.detail(created.recruit_id))
        await loadParticipation(created.recruit_id)
        setView('detail')
      } else {
        setView('list')
      }
    } catch (err) {
      console.error(err)
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const updateMeetup = async (payload) => {
    if (!selectedMeetup) return
    setBusy(true)
    setError('')
    try {
      await meetupApi.update(selectedMeetup.recruit_id, payload)
      setSelectedMeetup(await meetupApi.detail(selectedMeetup.recruit_id))
      await loadParticipation(selectedMeetup.recruit_id)
      await loadMeetups()
      setView('detail')
    } catch (err) {
      console.error(err)
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const deleteMeetup = async () => {
    if (!selectedMeetup || !window.confirm('이 모임을 삭제할까요?')) return
    setBusy(true)
    setError('')
    try {
      await meetupApi.remove(selectedMeetup.recruit_id)
      setSelectedMeetup(null)
      setMembers([])
      setMemberCount(0)
      setJoined(false)
      await loadMeetups()
      setView('list')
    } catch (err) {
      console.error(err)
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const changeParticipation = async (join) => {
    if (!selectedMeetup || busy) return
    setBusy(true)
    setError('')
    try {
      if (join) await meetupApi.join(selectedMeetup.recruit_id)
      else await meetupApi.cancelJoin(selectedMeetup.recruit_id)
      setJoined(join)
      await loadParticipation(selectedMeetup.recruit_id)
      setSelectedMeetup(await meetupApi.detail(selectedMeetup.recruit_id))
      await loadMeetups()
    } catch (err) {
      console.error(err)
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {error && <div className="error-banner" role="alert">{error}</div>}
      {detailLoading && <main className="meetup-page"><p>모임 정보를 불러오는 중...</p></main>}
      {!detailLoading && view === 'list' && <MeetupPage meetups={meetups} loading={loading} onMeetup={openMeetup} onWrite={openWrite} />}
      {!detailLoading && view === 'detail' && selectedMeetup && (
        <MeetupDetailPage
          meetup={selectedMeetup} members={members} memberCount={memberCount} joined={joined} busy={busy}
          onBack={goBack} onEdit={openEdit} onDelete={deleteMeetup}
          onJoin={() => changeParticipation(true)} onCancelJoin={() => changeParticipation(false)}
        />
      )}
      {!detailLoading && view === 'editor' && (
        <MeetupEditorPage
          key={selectedMeetup?.recruit_id ?? 'new'} meetup={selectedMeetup} busy={busy}
          onBack={selectedMeetup ? () => setView('detail') : goBack}
          onSubmit={selectedMeetup ? updateMeetup : createMeetup}
        />
      )}
    </>
  )
}
