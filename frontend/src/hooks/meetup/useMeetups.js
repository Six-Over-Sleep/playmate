import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { meetupApi } from '../../services/meetupApi'
import { normalizeMemberCount } from '../../utils/meetup'


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
  return (
    error?.message ||
    error?.detail ||
    fallback
  )
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


  // =========================================================
  // State
  // =========================================================

  const [meetups, setMeetups] = useState([])
  const [selectedMeetup, setSelectedMeetup] = useState(null)

  const [view, setView] = useState('list')

  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [busy, setBusy] = useState(false)

  const [members, setMembers] = useState([])
  const [memberCount, setMemberCount] = useState(0)

  // 댓글 상태 유지
  const [comments, setComments] = useState([])

  // 현재 회원의 모임 참여 여부
  const [joined, setJoined] = useState(false)

  const [error, setError] = useState('')
  const [actionMessage, setActionMessage] = useState('')


  // =========================================================
  // 1. 모임 목록 조회
  // =========================================================

  const loadMeetups = async () => {
    setLoading(true)

    try {
      const data = await meetupApi.list()

      setMeetups(
        Array.isArray(data) ? data : [],
      )

    } catch (err) {
      console.error(err)

      setError(
        getErrorMessage(
          err,
          '모임 목록을 불러오지 못했습니다.',
        ),
      )

    } finally {
      setLoading(false)
    }
  }


  // =========================================================
  // 2. 로그인 회원 변경
  // =========================================================

  useEffect(() => {
    // 기존 상세 조회 무효화
    detailRequest.current += 1

    // URL을 다시 처리할 수 있도록 초기화
    handledPath.current = null

    // 이전 회원의 정보 초기화
    setSelectedMeetup(null)

    setMembers([])
    setMemberCount(0)
    setComments([])

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

  const loadParticipation = async (
    recruitId,
    detail = null,
    isCurrent = () => true,
  ) => {

    const [
      memberData,
      countData,
    ] = await Promise.all([
      meetupApi.members(recruitId),
      meetupApi.count(recruitId),
    ])

    // 다른 모임으로 이동했다면 이전 응답 무시
    if (!isCurrent()) {
      return
    }

    const memberList = Array.isArray(memberData)
      ? memberData
      : memberData?.members || []

    setMembers(memberList)

    // 신규 프로젝트는 상세 응답의 참여 인원 우선
    const detailCount = detail?.participant_count

    setMemberCount(
      detailCount != null
        ? Number(detailCount)
        : normalizeMemberCount(countData),
    )

    // 모임 유형에 따른 참여 상태 계산
    if (detail) {
      setJoined(
        resolveJoinedState(
          detail,
          memberList,
          currentMemberId,
        ),
      )
    } else {
      setJoined(false)
    }
  }


  // =========================================================
  // 4. 모임 상세 정보 갱신
  // =========================================================

  const refreshDetail = async (recruitId) => {
    const requestId = detailRequest.current

    const detail = await meetupApi.detail(recruitId)

    // 다른 화면으로 이동한 경우 이전 결과 무시
    if (requestId !== detailRequest.current) {
      return null
    }

    await loadParticipation(
      recruitId,
      detail,
      () => requestId === detailRequest.current,
    )

    if (requestId !== detailRequest.current) {
      return null
    }

    setSelectedMeetup(detail)

    return detail
  }


  const refreshAfterAction = async (
    recruitId,
    message,
  ) => {
    await refreshDetail(recruitId)
    await loadMeetups()

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

    // 유효하지 않은 모임 ID 검사
    if (
      !Number.isSafeInteger(recruitId) ||
      recruitId <= 0
    ) {
      return
    }

    // 새로운 상세 조회 요청 번호
    const requestId = ++detailRequest.current

    setDetailLoading(true)

    setError('')
    setActionMessage('')

    // 이전 모임 정보 초기화
    setSelectedMeetup(null)

    setMembers([])
    setMemberCount(0)
    setComments([])

    setJoined(false)
    setView('list')

    try {
      // 모임 상세 API 호출
      const detail = await meetupApi.detail(recruitId)

      // 이전 요청 결과는 무시
      if (requestId !== detailRequest.current) {
        return
      }

      // 참여자 및 참여 상태 조회
      await loadParticipation(
        recruitId,
        detail,
        () => requestId === detailRequest.current,
      )

      // 조회 도중 다른 모임으로 이동했다면 중단
      if (requestId !== detailRequest.current) {
        return
      }

      // 상세 정보 저장
      setSelectedMeetup(detail)

      // 상세 화면 표시
      setView('detail')

      // 게시글 URL 변경
      if (changeUrl) {
        const path = `/meetup/${recruitId}`

        handledPath.current = path

        navigate(path)
      }

    } catch (err) {
      if (requestId !== detailRequest.current) {
        return
      }

      console.error(err)

      setError(
        getErrorMessage(
          err,
          '모임 정보를 불러오지 못했습니다.',
        ),
      )

    } finally {
      if (requestId === detailRequest.current) {
        setDetailLoading(false)
      }
    }
  }


  // =========================================================
  // 6. 모임 목록으로 돌아가기
  // =========================================================

  const goBack = (changeUrl = true) => {

    // 기존 상세 요청 무효화
    detailRequest.current += 1

    setDetailLoading(false)

    // 선택한 모임 초기화
    setSelectedMeetup(null)

    setMembers([])
    setMemberCount(0)
    setComments([])

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

    setDetailLoading(false)

    setSelectedMeetup(null)

    setMembers([])
    setMemberCount(0)
    setComments([])

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

    setBusy(true)

    setError('')
    setActionMessage('')

    try {
      const created = await meetupApi.create(payload)

      // 생성 후 목록 갱신
      await loadMeetups()

      if (created?.recruit_id) {
        // 이전 상세 조회 무효화
        detailRequest.current += 1

        const detail = await meetupApi.detail(
          created.recruit_id,
        )

        // 참여 상태 조회
        await loadParticipation(
          created.recruit_id,
          detail,
        )

        // 생성한 모임 상세 표시
        setSelectedMeetup(detail)
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

      setError(
        getErrorMessage(
          err,
          '모임을 생성하지 못했습니다.',
        ),
      )

      return null

    } finally {
      setBusy(false)
    }
  }


  // =========================================================
  // 12. 모임 수정
  // =========================================================

  const updateMeetup = async (payload) => {

    if (!selectedMeetup) {
      return null
    }

    setBusy(true)

    setError('')
    setActionMessage('')

    try {
      const updated = await meetupApi.update(
        selectedMeetup.recruit_id,
        payload,
      )

      // 수정된 상세 정보 다시 조회
      await refreshDetail(
        selectedMeetup.recruit_id,
      )

      // 모임 목록도 갱신
      await loadMeetups()

      setView('detail')

      return updated

    } catch (err) {
      console.error(err)

      setError(
        getErrorMessage(
          err,
          '모임을 수정하지 못했습니다.',
        ),
      )

      return null

    } finally {
      setBusy(false)
    }
  }


  // =========================================================
  // 13. 모임 게시글 삭제
  // =========================================================

  const deleteMeetup = async () => {

    if (
      !selectedMeetup ||
      !window.confirm('이 모임 게시글을 삭제할까요?')
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

      setJoined(false)

      // 목록 새로고침
      await loadMeetups()

      setView('list')

      // 삭제 후 목록으로 이동
      const path = '/meetup'

      handledPath.current = path

      navigate(path, { replace: true })

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

    if (!selectedMeetup || busy) {
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
      setSelectedMeetup((prev) => ({
        ...prev,

        like_count: result.like_count,
        liked_by_me: result.liked_by_me,
      }))

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


  // =========================================================
  // 15. 모임 신청 / 신청 취소 / 중도이탈
  // =========================================================

  const changeParticipation = async (
    join,
    payload = null,
  ) => {

    if (!selectedMeetup || busy) {
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

      await loadMeetups()

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
  // 16. 프로젝트 연장
  // =========================================================

  const extendProject = async (payload) => {

    if (
      !selectedMeetup?.recruit_id ||
      busy
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
  // 17. 프로젝트 예외 시작
  // =========================================================

  const chooseExceptionStart = async () => {

    if (
      !selectedMeetup?.recruit_id ||
      busy
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
  // 18. 프로젝트 취소
  // =========================================================

  const cancelProject = async () => {

    if (
      !selectedMeetup?.recruit_id ||
      busy
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
  // 19. 프로젝트 중도 종료
  // =========================================================

  const endProjectEarly = async () => {

    if (
      !selectedMeetup?.recruit_id ||
      busy
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
  // 20. 외부 컴포넌트에 제공할 값
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

    // 좋아요
    toggleLike,

    // 프로젝트 관리
    extendProject,
    chooseExceptionStart,
    cancelProject,
    endProjectEarly,
  }
}