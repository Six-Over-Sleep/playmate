import { useEffect, useState } from 'react'
import Header from './components/layout/Header'
import MeetupPage from './pages/meetup/MeetupPage'
import MeetupDetailPage from './pages/meetup/MeetupDetailPage'
import MeetupEditorPage from './pages/meetup/MeetupEditorPage'
import { meetupApi } from './services/meetupApi'
import './styles/meetup.css'

export default function App() {
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

  const loadMeetups = async () => {
    setLoading(true)

    try {
      const data = await meetupApi.list()

      const meetupsWithCount = await Promise.all(
        data.map(async (meetup) => {
          try {
            const countData = await meetupApi.count(meetup.recruit_id)

            return {
              ...meetup,
              participant_count: normalizeCount(countData),
            }
          } catch (err) {
            console.error(err)

            return {
              ...meetup,
              participant_count: 0,
            }
          }
        }),
      )

      setMeetups(meetupsWithCount)
    } catch (err) {
      console.error(err)
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadMeetups()
  }, [])

  const normalizeCount = (data) => {
    if (typeof data === 'number') return data

    return Number(
      data?.current_members ??
      data?.count ??
      data?.member_count ??
      data?.current_count ??
      data?.participant_count ??
      0
    )
  }

  const loadParticipation = async (recruitId) => {
    const [memberData, countData] = await Promise.all([
      meetupApi.members(recruitId),
      meetupApi.count(recruitId),
    ])

    const memberList = Array.isArray(memberData)
      ? memberData
      : memberData?.members || []

    setMembers(memberList)
    setMemberCount(normalizeCount(countData))

    // 현재 백엔드 개발 단계에서 로그인 대신 member_id=-1을 사용 중인 경우
    const hasCurrentMember = memberList.some(
      (member) => Number(member?.member_id ?? member?.id) === -1
    )

    setJoined(hasCurrentMember)
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
      const detail = await meetupApi.detail(selectedMeetup.recruit_id)
      setSelectedMeetup(detail)
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
        const detail = await meetupApi.detail(created.recruit_id)

        setSelectedMeetup(detail)
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
      await meetupApi.update(
        selectedMeetup.recruit_id,
        payload,
      )

      const detail = await meetupApi.detail(
        selectedMeetup.recruit_id,
      )

      setSelectedMeetup(detail)
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
    if (!selectedMeetup) return

    const confirmed = window.confirm(
      '이 모임을 삭제할까요?',
    )

    if (!confirmed) return

    setBusy(true)
    setError('')

    try {
      await meetupApi.remove(
        selectedMeetup.recruit_id,
      )

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

  const joinMeetup = async () => {
    if (!selectedMeetup || busy) return

    setBusy(true)
    setError('')

    try {
      await meetupApi.join(selectedMeetup.recruit_id)

      setJoined(true)
      await loadParticipation(selectedMeetup.recruit_id)

      const detail = await meetupApi.detail(selectedMeetup.recruit_id)
      setSelectedMeetup(detail)

      await loadMeetups()
    } catch (err) {
      console.error(err)
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const cancelJoinMeetup = async () => {
    if (!selectedMeetup || busy) return

    setBusy(true)
    setError('')

    try {
      await meetupApi.cancelJoin(selectedMeetup.recruit_id)

      setJoined(false)
      await loadParticipation(selectedMeetup.recruit_id)

      const detail = await meetupApi.detail(selectedMeetup.recruit_id)
      setSelectedMeetup(detail)

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
      <Header onMeetupHome={goBack} />

      {error && (
        <div className="error-banner">
          {error}
        </div>
      )}

      {detailLoading && (
        <main className="meetup-page">
          <p>모임 정보를 불러오는 중...</p>
        </main>
      )}

      {!detailLoading && view === 'list' && (
        <MeetupPage
          meetups={meetups}
          loading={loading}
          onMeetup={openMeetup}
          onWrite={openWrite}
        />
      )}

      {!detailLoading &&
        view === 'detail' &&
        selectedMeetup && (
          <MeetupDetailPage
            meetup={selectedMeetup}
            members={members}
            memberCount={memberCount}
            joined={joined}
            busy={busy}
            onBack={goBack}
            onEdit={openEdit}
            onDelete={deleteMeetup}
            onJoin={joinMeetup}
            onCancelJoin={cancelJoinMeetup}
          />
        )}

      {!detailLoading && view === 'editor' && (
        <MeetupEditorPage
          key={selectedMeetup?.recruit_id ?? 'new'}
          meetup={selectedMeetup}
          busy={busy}
          onBack={
            selectedMeetup
              ? () => setView('detail')
              : goBack
          }
          onSubmit={
            selectedMeetup
              ? updateMeetup
              : createMeetup
          }
        />
      )}
    </>
  )
}
