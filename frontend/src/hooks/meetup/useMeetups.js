import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { meetupApi } from '../../services/meetupApi'
import { meetupErrorMessage } from '../../utils/meetupForm'
import { normalizeMemberCount } from '../../utils/meetup'
import { createMeetupRequestGate } from '../../utils/meetupRequest'


// =========================================================
// 공통 유틸리티
// =========================================================

// 신규 프로젝트 신청 상태 확인
function getApplicationStatus(meetup) {
  return String(
    meetup?.my_application?.application_status ?? '',
  ).toUpperCase()
}


// 참여 신청 상태 확인
function hasActiveApplication(meetup) {
  return ['ACCEPTED', 'WAITING'].includes(
    getApplicationStatus(meetup),
  )
}


// 신규 프로젝트·스터디 여부 확인
// 기존 스터디를 category 문자열만으로 신규 프로그램으로 판단하지 않는다.
function isProgramDetail(meetup) {
  if (!meetup || typeof meetup !== 'object') {
    return false
  }

  return (
    Object.prototype.hasOwnProperty.call(
      meetup,
      'permissions',
    ) ||
    Object.prototype.hasOwnProperty.call(
      meetup,
      'my_application',
    ) ||
    meetup.lifecycle_status != null ||
    meetup.schedule_version != null
  )
}


// 기존 모임 참여 여부 확인
function isLegacyMemberJoined(
  memberList,
  currentMemberId,
) {
  if (currentMemberId == null) {
    return false
  }

  const targetId = String(currentMemberId)

  return memberList.some((member) => {
    const rowMemberId =
      member?.member_id ??
      member?.id

    return (
      rowMemberId != null &&
      String(rowMemberId) === targetId
    )
  })
}


// 모임 유형에 따라 참여 상태 계산
function resolveJoinedState(
  meetup,
  memberList,
  currentMemberId,
) {
  if (isProgramDetail(meetup)) {
    return hasActiveApplication(meetup)
  }

  return isLegacyMemberJoined(
    memberList,
    currentMemberId,
  )
}


// 프로젝트 일정 버전 확인
function getScheduleVersion(meetup) {
  const version = Number(meetup?.schedule_version)

  return Number.isInteger(version) && version >= 1
    ? version
    : null
}


// API 오류 메시지 처리
function getErrorMessage(error, fallback) {
  return meetupErrorMessage(error, fallback)
}


// =========================================================
// 모임 Hook
// =========================================================

export default function useMeetups({
  currentMemberId = null,
} = {}) {

  // =========================================================
  // React Router
  // =========================================================

  const { pathname } = useLocation()
  const navigate = useNavigate()

  // 이미 처리한 URL을 기억
  const handledPath = useRef(null)

  // 이전 상세 조회 응답이 새 화면을 덮지 않도록 관리
  const detailRequest = useRef(0)
  const detailAbortController = useRef(null)


  // =========================================================
  // State
  // =========================================================

  const [meetups, setMeetups] = useState([])
  const [selectedMeetup, setSelectedMeetup] = useState(null)
  const selectedRef = useRef(null)
  selectedRef.current = selectedMeetup

  const [view, setView] = useState('list')

  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [busy, setBusyState] = useState(false)
  const busyRef = useRef(false)
  const setBusy = (value) => { busyRef.current = value; setBusyState(value) }

  const [members, setMembers] = useState([])
  const [memberCount, setMemberCount] = useState(0)

  // 댓글 상태 유지
  const [comments, setComments] = useState([])
  const [commentsLoading, setCommentsLoading] = useState(false)
  const [listRequests] = useState(createMeetupRequestGate)
  const memberRef = useRef(currentMemberId)
  memberRef.current = currentMemberId

  // 현재 회원의 모임 참여 여부
  const [joined, setJoined] = useState(false)

  const [error, setError] = useState('')
  const [actionMessage, setActionMessage] = useState('')


  // =========================================================
  // 1. 모임 목록 조회
  // =========================================================

  const loadMeetups = async ({ force = false } = {}) => {
    const member = currentMemberId
    const request = listRequests.get(member, () => meetupApi.list(), { force })
    const isCurrent = () => request.isCurrent() && memberRef.current === member
    setLoading(true)

    try {
      const data = await request.promise
      if (!isCurrent()) return

      setMeetups(
        Array.isArray(data) ? data : [],
      )

    } catch (err) {
      if (!isCurrent()) return
      console.error(err)

      setError(
        getErrorMessage(
          err,
          '모임 목록을 불러오지 못했습니다.',
        ),
      )

    } finally {
      if (isCurrent()) setLoading(false)
    }
  }


  // =========================================================
  // 2. 로그인 회원 변경
  // =========================================================

  useEffect(() => {
    // 기존 상세 조회 무효화
    detailRequest.current += 1
    detailAbortController.current?.abort()
    detailAbortController.current = null

    // URL을 다시 처리할 수 있도록 초기화
    handledPath.current = null

    // 이전 회원의 정보 초기화
    setSelectedMeetup(null)

    setMembers([])
    setMemberCount(0)
    setComments([])
    setCommentsLoading(false)

    setJoined(false)

    setView('list')
    setDetailLoading(false)

    setError('')
    setActionMessage('')

    // 모임 목록 새로 조회
    loadMeetups()

  }, [currentMemberId])


  // =========================================================
  // 3. 참여자 / 참여 인원 / 참여 상태 조회
  // =========================================================

  const hasIntegratedParticipation = (detail) => {
    return (
      detail &&
      typeof detail === 'object' &&
      Array.isArray(detail.members) &&
      detail.participation &&
      typeof detail.participation === 'object'
    )
  }


  const applyParticipation = (
    detail,
    memberList,
    countData = null,
  ) => {
    const normalizedMembers = Array.isArray(memberList)
      ? memberList
      : []

    setMembers(normalizedMembers)

    const integratedCount =
      detail?.participation?.current_members ??
      (countData == null ? detail?.participant_count : null)

    setMemberCount(
      integratedCount != null
        ? Number(integratedCount)
        : normalizeMemberCount(countData),
    )

    setJoined(
      resolveJoinedState(
        detail,
        normalizedMembers,
        currentMemberId,
      ),
    )
  }


  const loadParticipation = async (
    recruitId,
    detail,
    { signal, isCurrent = () => true } = {},
  ) => {
    // 신규 프로젝트·스터디는 상세 응답에 참여자/인원 정보가 통합되어 있다.
    // 이 경우 /members, /count를 추가 호출하지 않는다.
    if (hasIntegratedParticipation(detail)) {
      if (!isCurrent()) {
        return
      }

      applyParticipation(
        detail,
        detail.members,
        detail.participation,
      )
      return
    }

    // 기존 운동·게임·공동구매·옛 스터디는 기존 API를 유지한다.
    const [memberData, countData] = await Promise.all([
      meetupApi.members(recruitId, { signal }),
      meetupApi.count(recruitId, { signal }),
    ])

    if (!isCurrent()) {
      return
    }

    const memberList = Array.isArray(memberData)
      ? memberData
      : memberData?.members || []

    applyParticipation(
      detail,
      memberList,
      countData,
    )
  }


  // =========================================================
  // 4. 모임 상세 정보 갱신
  // =========================================================

  const fetchDetailSnapshot = async (
    recruitId,
    { showLoading = false } = {},
  ) => {
    const requestId = ++detailRequest.current

    // 이전 상세 요청이 진행 중이면 실제 네트워크 요청도 취소한다.
    detailAbortController.current?.abort()
    setCommentsLoading(false)

    const controller = new AbortController()
    detailAbortController.current = controller
    let commentTask = null

    if (showLoading) {
      setDetailLoading(true)
    }

    try {
      const detail = await meetupApi.detail(
        recruitId,
        { signal: controller.signal },
      )

      if (requestId !== detailRequest.current) {
        return null
      }

      await loadParticipation(
        recruitId,
        detail,
        {
          signal: controller.signal,
          isCurrent: () => requestId === detailRequest.current,
        },
      )

      if (requestId !== detailRequest.current) {
        return null
      }

      // 상세는 먼저 표시하고 댓글은 별도로 갱신한다. 이전 모임의 늦은 응답은 무시한다.
      setSelectedMeetup(detail)
      setCommentsLoading(true)
      commentTask = meetupApi.comments(recruitId, { signal: controller.signal })
        .then((data) => {
          if (requestId === detailRequest.current) {
            setComments(Array.isArray(data) ? data : [])
          }
        })
        .catch((error) => {
          if (error.name !== 'AbortError' && requestId === detailRequest.current) {
            setError('댓글을 불러오지 못했어요. 모임 정보는 계속 확인할 수 있어요.')
          }
        })
        .finally(() => {
          if (requestId === detailRequest.current) setCommentsLoading(false)
          if (detailAbortController.current === controller) {
            detailAbortController.current = null
          }
        })
      return detail
    } catch (err) {
      if (err?.name === 'AbortError') {
        return null
      }

      throw err
    } finally {
      if (
        !commentTask && detailAbortController.current === controller
      ) {
        detailAbortController.current = null
      }

      if (
        showLoading &&
        requestId === detailRequest.current
      ) {
        setDetailLoading(false)
      }
    }
  }


  const refreshDetail = async (recruitId) => {
    return fetchDetailSnapshot(recruitId)
  }


  const refreshAfterAction = async (
    recruitId,
    message,
  ) => {
    await refreshDetail(recruitId)
    await loadMeetups({ force: true })

    if (message) {
      setActionMessage(message)
    }
  }


  // =========================================================
  // 5. 모임 상세 화면 열기
  // =========================================================

  const openMeetup = async (
    meetup,
    changeUrl = true,
  ) => {
    const recruitId = Number(meetup?.recruit_id)

    if (
      !Number.isSafeInteger(recruitId) ||
      recruitId <= 0
    ) {
      return
    }

    setError('')
    setActionMessage('')
    setSelectedMeetup(null)
    setMembers([])
    setMemberCount(0)
    setComments([])
    setCommentsLoading(false)
    setJoined(false)
    setView('list')

    try {
      const detail = await fetchDetailSnapshot(
        recruitId,
        { showLoading: true },
      )

      if (!detail) {
        return
      }

      setView('detail')

      if (changeUrl) {
        const path = `/meetup/${recruitId}`
        handledPath.current = path
        navigate(path)
      }
    } catch (err) {
      console.error(err)

      setError(
        getErrorMessage(
          err,
          '모임 정보를 불러오지 못했습니다.',
        ),
      )
    }
  }


  // =========================================================
  // 6. 모임 목록으로 돌아가기
  // =========================================================

  const goBack = (changeUrl = true) => {

    // 기존 상세 요청 무효화
    detailRequest.current += 1
    detailAbortController.current?.abort()
    detailAbortController.current = null

    setDetailLoading(false)

    // 선택한 모임 초기화
    setSelectedMeetup(null)

    setMembers([])
    setMemberCount(0)
    setComments([])
    setCommentsLoading(false)

    setJoined(false)

    setView('list')

    setError('')
    setActionMessage('')

    // 목록 URL 이동
    if (changeUrl) {
      handledPath.current = '/meetup'

      navigate('/meetup')
    }
  }


  // =========================================================
  // 7. URL 변경 및 새로고침 복원
  // =========================================================

  useEffect(() => {

    // 동일 URL 중복 처리 방지
    if (handledPath.current === pathname) {
      return
    }

    handledPath.current = pathname

    // 모임 목록 화면
    if (
      pathname === '/meetup' ||
      pathname === '/meetup/'
    ) {
      goBack(false)
      return
    }

    // 모임 상세 URL
    // 예시: /meetup/8
    const match = pathname.match(
      /^\/meetup\/([1-9]\d*)\/?$/
    )

    if (match) {
      const recruitId = Number(match[1])

      if (
        Number.isSafeInteger(recruitId) &&
        recruitId > 0
      ) {
        // URL의 모임 ID로 상세 정보 복원
        openMeetup(
          { recruit_id: recruitId },
          false,
        )

        return
      }
    }

    // 잘못된 모임 URL 처리
    detailRequest.current += 1

    setSelectedMeetup(null)

    setMembers([])
    setMemberCount(0)
    setComments([])
    setCommentsLoading(false)

    setJoined(false)

    setDetailLoading(false)
    setView('list')

    setError('올바르지 않은 모임 주소입니다.')

  }, [pathname, currentMemberId])


  // =========================================================
  // 8. 모임 작성 화면 열기
  // =========================================================

  const openWrite = () => {

    // 이전 상세 조회 무효화
    detailRequest.current += 1
    detailAbortController.current?.abort()
    detailAbortController.current = null

    setDetailLoading(false)

    setSelectedMeetup(null)

    setMembers([])
    setMemberCount(0)
    setComments([])
    setCommentsLoading(false)

    setJoined(false)

    setError('')
    setActionMessage('')

    setView('editor')
  }


  // =========================================================
  // 9. 모임 수정 화면 열기
  // =========================================================

  const openEdit = async () => {
    if (!selectedMeetup?.recruit_id) {
      return
    }

    setDetailLoading(true)

    setError('')
    setActionMessage('')

    try {
      const detail = await meetupApi.detail(
        selectedMeetup.recruit_id,
      )

      setSelectedMeetup(detail)

      setView('editor')

    } catch (err) {
      console.error(err)

      setError(
        getErrorMessage(
          err,
          '모임 정보를 다시 불러오지 못했습니다.',
        ),
      )

    } finally {
      setDetailLoading(false)
    }
  }


  // =========================================================
  // 10. 모임 수정 취소
  // =========================================================

  const backToDetail = () => {
    setView('detail')
  }


  // =========================================================
  // 11. 모임 생성
  // =========================================================

  const createMeetup = async (payload) => {
    if (busyRef.current) return null

    setBusy(true)

    setError('')
    setActionMessage('')

    let created = null
    try {
      created = await meetupApi.create(payload)

      setActionMessage('모임이 만들어졌어요.')
      // 생성 후 목록 갱신
      await loadMeetups({ force: true })

      if (created?.recruit_id) {
        const detail = await refreshDetail(
          created.recruit_id,
        )

        if (!detail) {
          return created
        }

        // 생성한 모임 상세 표시
        setView('detail')

        // 생성한 모임 URL로 이동
        const path = `/meetup/${created.recruit_id}`

        handledPath.current = path

        navigate(path)

      } else {
        setView('list')
      }

      return created

    } catch (err) {
      console.error(err)

      if (created?.recruit_id) {
        setView('list')
        setError('모임은 저장됐지만 상세 정보를 불러오지 못했어요. 목록에서 다시 열어주세요.')
        return created
      }
      throw err

    } finally {
      setBusy(false)
    }
  }


  // =========================================================
  // 12. 모임 수정
  // =========================================================

  const updateMeetup = async (payload) => {

    if (!selectedMeetup || busyRef.current) {
      return null
    }

    setBusy(true)

    setError('')
    setActionMessage('')

    let saved = false
    try {
      const updated = await meetupApi.update(
        selectedMeetup.recruit_id,
        payload,
      )

      saved = true
      // 수정된 상세 정보 다시 조회
      await refreshDetail(
        selectedMeetup.recruit_id,
      )

      // 모임 목록도 갱신
      await loadMeetups({ force: true })

      setView('detail')
      setActionMessage('모임을 수정했어요.')

      return updated

    } catch (err) {
      console.error(err)

      if (saved) {
        setView('detail')
        setError('수정은 저장됐지만 최신 정보를 불러오지 못했어요. 새로고침해주세요.')
        return true
      }
      throw err

    } finally {
      setBusy(false)
    }
  }


  // =========================================================
  // 13. 모임 게시글 삭제
  // =========================================================

  const deleteMeetup = async () => {

    if (
      !selectedMeetup || busyRef.current
    ) {
      return
    }

    setBusy(true)

    setError('')
    setActionMessage('')

    try {
      // 모임 게시글 논리 삭제
      await meetupApi.remove(
        selectedMeetup.recruit_id,
      )

      // 이전 상세 조회 무효화
      detailRequest.current += 1

      // 상세 정보 초기화
      setSelectedMeetup(null)

      setMembers([])
      setMemberCount(0)
      setComments([])
    setCommentsLoading(false)

      setJoined(false)

      // 목록 새로고침
      await loadMeetups({ force: true })

      setView('list')

      // 삭제 후 목록으로 이동
      const path = '/meetup'

      handledPath.current = path

      navigate(path, { replace: true })
      setActionMessage('모임을 삭제했어요.')
      return true

    } catch (err) {
      console.error(err)

      setError(
        getErrorMessage(
          err,
          '모임 게시글을 삭제하지 못했습니다.',
        ),
      )

    } finally {
      setBusy(false)
    }
  }


  // =========================================================
  // 14. 좋아요
  // =========================================================

  const toggleLike = async () => {

    if (!selectedMeetup || busyRef.current) {
      return null
    }

    setBusy(true)
    setError('')

    try {
      const result = selectedMeetup.liked_by_me
        ? await meetupApi.unlike(
            selectedMeetup.recruit_id,
          )
        : await meetupApi.like(
            selectedMeetup.recruit_id,
          )

      // 상세 좋아요 상태 갱신
      setSelectedMeetup((prev) => prev?.recruit_id === result.recruit_id ? {
        ...prev,
        like_count: result.like_count,
        liked_by_me: result.liked_by_me,
      } : prev)

      // 목록 좋아요 상태 갱신
      setMeetups((prev) =>
        prev.map((meetup) =>
          meetup.recruit_id === result.recruit_id
            ? {
                ...meetup,
                like_count: result.like_count,
                liked_by_me: result.liked_by_me,
              }
            : meetup,
        ),
      )

      return result

    } catch (err) {
      console.error(err)

      setError(
        getErrorMessage(
          err,
          '좋아요 상태를 변경하지 못했습니다.',
        ),
      )

      return null

    } finally {
      setBusy(false)
    }
  }


  // Social writes are serialized, use server results, and retain drafts on failure.
  const toggleScrap = async () => {
    if (!selectedMeetup || busyRef.current) return null
    setBusy(true)
    setError('')
    const id = selectedMeetup.recruit_id
    try {
      const result = await meetupApi[selectedMeetup.scrapped_by_me ? 'unscrap' : 'scrap'](selectedMeetup.recruit_id)
      setSelectedMeetup((prev) => prev?.recruit_id === id ? { ...prev, scrapped_by_me: result.scrapped_by_me } : prev)
      setActionMessage(result.scrapped_by_me ? '스크랩에 저장했어요.' : '스크랩을 해제했어요.')
      return result
    } catch (err) {
      setError(getErrorMessage(err, '스크랩을 변경하지 못했어요.'))
      return null
    } finally { setBusy(false) }
  }

  const changeComment = async (kind, ...args) => {
    if (!selectedMeetup || busyRef.current) return null
    const id = selectedMeetup.recruit_id
    setBusy(true)
    setError('')
    try {
      const result = await meetupApi[kind](id, ...args)
      const rows = await meetupApi.comments(id)
      if (selectedRef.current?.recruit_id === id) setComments(rows)
      setActionMessage(kind === 'deleteComment' ? '댓글을 삭제했어요.' : '댓글을 저장했어요.')
      return result || true
    } catch (err) {
      setError(getErrorMessage(err, '댓글을 처리하지 못했어요. 작성한 내용을 확인하고 다시 시도해주세요.'))
      return null
    } finally { setBusy(false) }
  }

  // =========================================================
  // 15. 모임 신청 / 신청 취소 / 중도이탈
  // =========================================================

  const changeParticipation = async (
    join,
    payload = null,
  ) => {

    if (!selectedMeetup || busyRef.current) {
      return null
    }

    // 중도이탈 여부
    const isWithdrawal =
      !join &&
      selectedMeetup?.permissions?.can_withdraw === true

    // 중도이탈 확인
    if (isWithdrawal) {
      const confirmed = window.confirm(
        '모임 시작 후 중도이탈로 처리됩니다.\n\n' +
        '중도이탈이 누적 3회 이상이면 이후 모든 종류의 모임에 새로 신청할 수 없습니다. ' +
        '시작 전 신청 취소는 집계하지 않으며, 제한 전에 접수된 유효 신청은 유지됩니다.\n\n' +
        '정말 중도이탈할까요?',
      )

      if (!confirmed) {
        return null
      }
    }

    setBusy(true)

    setError('')
    setActionMessage('')

    try {
      // 신청 또는 신청 취소
      const result = join
        ? await meetupApi.join(
            selectedMeetup.recruit_id,
            payload,
          )
        : await meetupApi.cancelJoin(
            selectedMeetup.recruit_id,
          )

      // 참여 상태 다시 조회
      await refreshDetail(
        selectedMeetup.recruit_id,
      )

      await loadMeetups({ force: true })

      if (join) {
        const resultStatus = String(
          result?.application_status ?? '',
        ).toUpperCase()

        if (resultStatus === 'WAITING') {
          setActionMessage(
            result?.message ||
            '대기 신청이 정상 접수되었습니다.',
          )

        } else if (resultStatus === 'ACCEPTED') {
          setActionMessage(
            result?.message ||
            '모임 참여가 확정되었습니다.',
          )

        } else if (result?.message) {
          setActionMessage(result.message)
        }

      } else if (isWithdrawal) {
        setActionMessage(
          '모임에서 중도이탈했습니다.',
        )

      } else {
        setActionMessage(
          result?.message ||
          '신청이 취소되었습니다.',
        )
      }

      return result

    } catch (err) {
      console.error(err)

      const message = getErrorMessage(
        err,
        join
          ? '모임 신청을 처리하지 못했습니다.'
          : '신청 변경을 처리하지 못했습니다.',
      )

      setError(message)

      // 프로젝트 신청 모달에서 오류 표시
      if (join && payload != null) {
        throw err
      }

      return null

    } finally {
      setBusy(false)
    }
  }


  // =========================================================
  // 16. 모임 활동 / 후기 작성
  // =========================================================

  const createActivity = async (payload) => {
    if (!selectedMeetup?.recruit_id || busyRef.current) {
      return null
    }

    setBusy(true)
    setError('')
    setActionMessage('')

    try {
      const result = await meetupApi.addActivity(
        selectedMeetup.recruit_id,
        payload,
      )

      // 권한/상태가 변경될 수 있으므로 작성 후 상세을 다시 확인한다.
      await refreshDetail(selectedMeetup.recruit_id)

      setActionMessage(
        payload?.activity_type === 'REVIEW'
          ? '후기가 등록되었습니다.'
          : '활동 기록이 등록되었습니다.',
      )

      return result
    } catch (err) {
      console.error(err)

      setError(
        getErrorMessage(
          err,
          payload?.activity_type === 'REVIEW'
            ? '후기를 등록하지 못했습니다.'
            : '활동 기록을 등록하지 못했습니다.',
        ),
      )

      throw err
    } finally {
      setBusy(false)
    }
  }


  // =========================================================
  // 17. 프로젝트 연장
  // =========================================================

  const extendProject = async (payload) => {

    if (
      !selectedMeetup?.recruit_id ||
      busyRef.current
    ) {
      return null
    }

    setBusy(true)

    setError('')
    setActionMessage('')

    try {
      const result = await meetupApi.extendProject(
        selectedMeetup.recruit_id,
        payload,
      )

      await refreshAfterAction(
        selectedMeetup.recruit_id,
        '프로젝트 일정이 연장되었습니다.',
      )

      return result

    } catch (err) {
      console.error(err)

      setError(
        getErrorMessage(
          err,
          '프로젝트 일정을 연장하지 못했습니다.',
        ),
      )

      // 연장 모달에서 오류 처리
      throw err

    } finally {
      setBusy(false)
    }
  }


  // =========================================================
  // 18. 프로젝트 예외 시작
  // =========================================================

  const chooseExceptionStart = async () => {

    if (
      !selectedMeetup?.recruit_id ||
      busyRef.current
    ) {
      return null
    }

    const scheduleVersion = getScheduleVersion(
      selectedMeetup,
    )

    if (!scheduleVersion) {
      setError(
        '최신 일정 버전을 확인할 수 없습니다. 상세 정보를 다시 불러와주세요.',
      )

      return null
    }

    const confirmed = window.confirm(
      '필수 기술이 부족한 현재 확정 구성으로 시작하도록 결정할까요?\n\n' +
      '이 결정은 기술 조건만 예외로 처리하며, ' +
      '프로젝트는 예정 시작 시각에 실제 시작됩니다.',
    )

    if (!confirmed) {
      return null
    }

    setBusy(true)

    setError('')
    setActionMessage('')

    try {
      const result = await meetupApi.chooseExceptionStart(
        selectedMeetup.recruit_id,
        {
          schedule_version: scheduleVersion,
        },
      )

      await refreshAfterAction(
        selectedMeetup.recruit_id,
        '현재 확정 구성으로 시작하도록 결정했습니다. 실제 시작은 예정 시작 시각에 처리됩니다.',
      )

      return result

    } catch (err) {
      console.error(err)

      setError(
        getErrorMessage(
          err,
          '현재 구성 시작 결정을 처리하지 못했습니다.',
        ),
      )

      return null

    } finally {
      setBusy(false)
    }
  }


  // =========================================================
  // 19. 프로젝트 취소
  // =========================================================

  const cancelProject = async () => {

    if (
      !selectedMeetup?.recruit_id ||
      busyRef.current
    ) {
      return null
    }

    // 취소 사유 입력
    const reason = window.prompt(
      '프로젝트 취소 사유를 입력해주세요.',
      '',
    )

    if (reason == null) {
      return null
    }

    const trimmedReason = reason.trim()

    if (!trimmedReason) {
      setError(
        '프로젝트 취소 사유를 입력해주세요.',
      )

      return null
    }

    const confirmed = window.confirm(
      '프로젝트를 취소할까요?\n' +
      '기존 참여·신청 이력은 서버에 유지됩니다.',
    )

    if (!confirmed) {
      return null
    }

    setBusy(true)

    setError('')
    setActionMessage('')

    try {
      const result = await meetupApi.cancelProject(
        selectedMeetup.recruit_id,
        {
          reason: trimmedReason,
        },
      )

      await refreshAfterAction(
        selectedMeetup.recruit_id,
        '프로젝트가 취소되었습니다.',
      )

      return result

    } catch (err) {
      console.error(err)

      setError(
        getErrorMessage(
          err,
          '프로젝트를 취소하지 못했습니다.',
        ),
      )

      return null

    } finally {
      setBusy(false)
    }
  }


  // =========================================================
  // 20. 프로젝트 중도 종료
  // =========================================================

  const endProjectEarly = async () => {

    if (
      !selectedMeetup?.recruit_id ||
      busyRef.current
    ) {
      return null
    }

    // 중도 종료 사유 입력
    const reason = window.prompt(
      '프로젝트 중도 종료 사유를 입력해주세요.',
      '',
    )

    if (reason == null) {
      return null
    }

    const trimmedReason = reason.trim()

    if (!trimmedReason) {
      setError(
        '중도 종료 사유를 입력해주세요.',
      )

      return null
    }

    const confirmed = window.confirm(
      '프로젝트를 중도 종료할까요?\n' +
      '중도 종료는 정상 완료와 구분되어 기록됩니다.',
    )

    if (!confirmed) {
      return null
    }

    setBusy(true)

    setError('')
    setActionMessage('')

    try {
      const result = await meetupApi.abortProject(
        selectedMeetup.recruit_id,
        {
          reason: trimmedReason,
        },
      )

      await refreshAfterAction(
        selectedMeetup.recruit_id,
        '프로젝트가 중도 종료되었습니다.',
      )

      return result

    } catch (err) {
      console.error(err)

      setError(
        getErrorMessage(
          err,
          '프로젝트를 중도 종료하지 못했습니다.',
        ),
      )

      return null

    } finally {
      setBusy(false)
    }
  }


  // =========================================================
  // 21. 외부 컴포넌트에 제공할 값
  // =========================================================

  return {
    // 모임 데이터
    meetups,
    selectedMeetup,

    // 화면 상태
    view,

    // 로딩 상태
    loading,
    detailLoading,
    busy,

    // 참여자
    members,
    memberCount,
    joined,

    // 댓글
    comments,
    commentsLoading,

    // 메시지
    error,
    actionMessage,

    // 화면 이동
    openMeetup,
    goBack,
    backToDetail,

    // 생성 및 수정
    openWrite,
    openEdit,
    createMeetup,
    updateMeetup,
    deleteMeetup,

    // 참여
    changeParticipation,

    // 좋아요 / 스크랩 / 댓글
    toggleLike,
    toggleScrap,
    addComment: (...args) => changeComment('addComment', ...args),
    editComment: (...args) => changeComment('editComment', ...args),
    deleteComment: (...args) => changeComment('deleteComment', ...args),
    dismissNotice: () => { setError(''); setActionMessage('') },

    // 활동 / 후기
    createActivity,

    // 프로젝트 관리
    extendProject,
    chooseExceptionStart,
    cancelProject,
    endProjectEarly,
  }
}
