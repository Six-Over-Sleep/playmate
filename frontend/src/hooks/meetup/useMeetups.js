import { useEffect, useState } from 'react'
import { meetupApi } from '../../services/meetupApi'
import { normalizeMemberCount } from '../../utils/meetup'

// 모임 데이터와 목록·상세·편집 화면 상태를 관리함.
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
  const [comments, setComments] = useState([])
  const [error, setError] = useState('')

  // 참여 인원수가 포함된 모임 목록을 조회함.
  const loadMeetups = async () => {
    setLoading(true)

    try {
      const data = await meetupApi.list()

      // 목록 API의 참여 인원수를 사용하고 모임별 count 요청을 추가하지 않음.
      setMeetups(data)
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

  // 상세 화면의 참여자 목록과 현재 인원수를 조회함.
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

  // 상세 화면의 댓글 목록을 조회함. 순서와 삭제 자리표시는 서버 응답을 그대로 사용함.
  const loadComments = async (recruitId) => {
    const data = await meetupApi.comments(recruitId)

    setComments(Array.isArray(data) ? data : [])
  }

  // 선택한 모임과 참여 정보를 불러온 뒤 상세 화면을 표시함.
  const openMeetup = async (meetup) => {
    setDetailLoading(true)
    setError('')

    try {
      const detail = await meetupApi.detail(meetup.recruit_id)

      setSelectedMeetup(detail)

      await loadParticipation(meetup.recruit_id)

      await loadComments(meetup.recruit_id)

      setView('detail')
    } catch (err) {
      console.error(err)
      setError(err.message)
    } finally {
      setDetailLoading(false)
    }
  }

  // 선택한 모임과 참여 상태를 비우고 목록으로 돌아감.
  const goBack = () => {
    setSelectedMeetup(null)
    setMembers([])
    setMemberCount(0)
    setJoined(false)
    setComments([])
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

  // 최신 모임 정보를 불러와 수정 화면을 열음.
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

  // 모임 생성 후 목록을 갱신하고 생성한 모임의 상세 화면을 표시함.
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

        setComments([])

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

  // 모임 수정 후 상세 정보와 목록을 갱신함.
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

  // 삭제 확인 후 모임을 삭제하고 목록으로 돌아감.
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
      setComments([])

      await loadMeetups()

      setView('list')
    } catch (err) {
      console.error(err)
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  // 참여·취소 후 참여 정보와 모임 목록을 갱신함.
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

  // 좋아요 여부에 따라 등록·취소하고, 응답의 좋아요 수로 상세와 목록 카드를 함께 갱신함.
  const toggleLike = async () => {
    if (!selectedMeetup || busy) return

    setBusy(true)
    setError('')

    try {
      const result = selectedMeetup.liked_by_me
        ? await meetupApi.unlike(selectedMeetup.recruit_id)
        : await meetupApi.like(selectedMeetup.recruit_id)

      setSelectedMeetup((prev) => ({
        ...prev,
        like_count: result.like_count,
        liked_by_me: result.liked_by_me,
      }))

      // 목록으로 돌아갔을 때 이전 좋아요 수가 남지 않도록 카드 데이터도 맞춤.
      setMeetups((prev) =>
        prev.map((meetup) =>
          meetup.recruit_id === result.recruit_id
            ? { ...meetup, like_count: result.like_count }
            : meetup,
        ),
      )
    } catch (err) {
      console.error(err)
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  // 스크랩 여부에 따라 등록·취소하고 응답의 스크랩 여부로 상세를 갱신함. (스크랩 수는 없음)
  const toggleScrap = async () => {
    if (!selectedMeetup || busy) return

    setBusy(true)
    setError('')

    try {
      const result = selectedMeetup.scrapped_by_me
        ? await meetupApi.unscrap(selectedMeetup.recruit_id)
        : await meetupApi.scrap(selectedMeetup.recruit_id)

      setSelectedMeetup((prev) => ({
        ...prev,
        scrapped_by_me: result.scrapped_by_me,
      }))
    } catch (err) {
      console.error(err)
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  // 댓글·대댓글 작성 후 댓글 목록을 다시 조회함. 성공 여부를 반환해 입력창을 비울지 정함.
  const addComment = async (body, parentCommentId = null) => {
    if (!selectedMeetup || busy) return false

    setBusy(true)
    setError('')

    try {
      await meetupApi.createComment(selectedMeetup.recruit_id, {
        body,
        parent_comment_id: parentCommentId,
      })

      await loadComments(selectedMeetup.recruit_id)

      return true
    } catch (err) {
      console.error(err)
      setError(err.message)

      return false
    } finally {
      setBusy(false)
    }
  }

  // 댓글 수정 후 댓글 목록을 다시 조회함.
  const editComment = async (commentId, body) => {
    if (!selectedMeetup || busy) return false

    setBusy(true)
    setError('')

    try {
      await meetupApi.updateComment(selectedMeetup.recruit_id, commentId, {
        body,
      })

      await loadComments(selectedMeetup.recruit_id)

      return true
    } catch (err) {
      console.error(err)
      setError(err.message)

      return false
    } finally {
      setBusy(false)
    }
  }

  // 삭제 확인 후 댓글을 삭제하고 목록을 다시 조회함.
  // 대댓글이 남은 부모의 자리표시 여부는 서버 목록 응답을 따름.
  const deleteComment = async (commentId) => {
    if (!selectedMeetup || busy || !window.confirm('이 댓글을 삭제할까요?')) {
      return
    }

    setBusy(true)
    setError('')

    try {
      await meetupApi.removeComment(selectedMeetup.recruit_id, commentId)

      await loadComments(selectedMeetup.recruit_id)
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
    comments,
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
    toggleLike,
    toggleScrap,
    addComment,
    editComment,
    deleteComment,
  }
}
