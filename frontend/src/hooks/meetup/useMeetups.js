import { useEffect, useState } from 'react'
import { meetupApi } from '../../services/meetupApi'
import { normalizeMemberCount } from '../../utils/meetup'

export default function useMeetups() {
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

      const withCounts = await Promise.all(
        data.map(async (meetup) => {
          try {
            const countData = await meetupApi.count(meetup.recruit_id)

            return {
              ...meetup,
              participant_count: normalizeMemberCount(countData),
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

      setMeetups(withCounts)
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

  const loadParticipation = async (recruitId) => {
    const [memberData, countData] = await Promise.all([
      meetupApi.members(recruitId),
      meetupApi.count(recruitId),
    ])

    const memberList = Array.isArray(memberData)
      ? memberData
      : memberData?.members || []

    setMembers(memberList)
    setMemberCount(normalizeMemberCount(countData))

    setJoined(
      memberList.some(
        (member) => Number(member?.member_id ?? member?.id) === -1,
      ),
    )
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

  const backToDetail = () => {
    setView('detail')
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
      await meetupApi.update(selectedMeetup.recruit_id, payload)

      const detail = await meetupApi.detail(selectedMeetup.recruit_id)

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
    if (!selectedMeetup || !window.confirm('이 모임을 삭제할까요?')) {
      return
    }

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
      if (join) {
        await meetupApi.join(selectedMeetup.recruit_id)
      } else {
        await meetupApi.cancelJoin(selectedMeetup.recruit_id)
      }

      setJoined(join)

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

  return {
    meetups,
    selectedMeetup,
    view,
    loading,
    detailLoading,
    busy,
    members,
    memberCount,
    joined,
    error,

    openMeetup,
    goBack,
    backToDetail,
    openWrite,
    openEdit,
    createMeetup,
    updateMeetup,
    deleteMeetup,
    changeParticipation,
  }
}
