import { useEffect, useState } from 'react'
import { meetupApi } from '../../services/meetupApi'
import { normalizeMemberCount } from '../../utils/meetup'

function getApplicationStatus(meetup) {
  return String(
    meetup?.my_application?.application_status ?? '',
  ).toUpperCase()
}

function hasActiveApplication(meetup) {
  return ['ACCEPTED', 'WAITING'].includes(
    getApplicationStatus(meetup),
  )
}

// 신규 프로젝트·스터디는 DB의 확장 프로그램 행이 있는 경우에만
// permissions / my_application / lifecycle_status 같은 확장 계약을 내려준다.
// 기존 스터디를 category 문자열만으로 신규 프로그램으로 판단하면 안 된다.
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

// 기존 운동·게임·공동구매·옛 스터디의 참여 여부는
// 로그인 회원 ID와 /members 응답의 실제 member_id를 비교한다.
// 숫자/문자열 차이 때문에 명시적으로 문자열로 통일한다.
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

function getScheduleVersion(meetup) {
  const version = Number(meetup?.schedule_version)

  return Number.isInteger(version) && version >= 1
    ? version
    : null
}

function getErrorMessage(error, fallback) {
  return (
    error?.message ||
    error?.detail ||
    fallback
  )
}

export default function useMeetups({
  currentMemberId = null,
} = {}) {
  const [meetups, setMeetups] = useState([])
  const [selectedMeetup, setSelectedMeetup] = useState(null)
  const [view, setView] = useState('list')
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [members, setMembers] = useState([])
  const [memberCount, setMemberCount] = useState(0)

  // 신규 프로그램은 my_application이 최종 기준이고,
  // 기존 모임은 로그인 회원 ID와 members의 실제 member_id 비교가 최종 기준이다.
  // joined는 기존 상세 컴포넌트와의 호환을 위해 유지한다.
  const [joined, setJoined] = useState(false)

  const [error, setError] = useState('')
  const [actionMessage, setActionMessage] = useState('')

  const loadMeetups = async () => {
    setLoading(true)

    try {
      const data = await meetupApi.list()

      setMeetups(Array.isArray(data) ? data : [])
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

  useEffect(() => {
    // 로그아웃/재로그인/계정 전환 때 이전 사용자의 참여 상태가
    // 다음 사용자에게 남지 않도록 화면 상태를 초기화한다.
    setSelectedMeetup(null)
    setMembers([])
    setMemberCount(0)
    setJoined(false)
    setView('list')
    setError('')
    setActionMessage('')

    loadMeetups()
  }, [currentMemberId])

  const loadParticipation = async (
    recruitId,
    detail = null,
  ) => {
    const [memberData, countData] = await Promise.all([
      meetupApi.members(recruitId),
      meetupApi.count(recruitId),
    ])

    const memberList = Array.isArray(memberData)
      ? memberData
      : memberData?.members || []

    setMembers(memberList)

    const detailCount = detail?.participant_count

    setMemberCount(
      detailCount != null
        ? Number(detailCount)
        : normalizeMemberCount(countData),
    )

    if (detail) {
      setJoined(
        resolveJoinedState(
          detail,
          memberList,
          currentMemberId,
        ),
      )
    } else {
      // 상세 계약이 없는 상태에서는 이전 사용자의 joined 값을 유지하지 않는다.
      setJoined(false)
    }
  }

  const refreshDetail = async (recruitId) => {
    const detail = await meetupApi.detail(recruitId)

    setSelectedMeetup(detail)

    await loadParticipation(recruitId, detail)

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

  const openMeetup = async (meetup) => {
    setDetailLoading(true)
    setError('')
    setActionMessage('')

    try {
      const detail = await meetupApi.detail(
        meetup.recruit_id,
      )

      setSelectedMeetup(detail)

      await loadParticipation(
        meetup.recruit_id,
        detail,
      )

      setView('detail')
    } catch (err) {
      console.error(err)
      setError(
        getErrorMessage(
          err,
          '모임 정보를 불러오지 못했습니다.',
        ),
      )
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
    setActionMessage('')
  }

  const backToDetail = () => {
    setView('detail')
  }

  const openWrite = () => {
    setSelectedMeetup(null)
    setError('')
    setActionMessage('')
    setView('editor')
  }

  const openEdit = async () => {
    if (!selectedMeetup?.recruit_id) return

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

  const createMeetup = async (payload) => {
    setBusy(true)
    setError('')
    setActionMessage('')

    try {
      const created = await meetupApi.create(payload)

      await loadMeetups()

      if (created?.recruit_id) {
        const detail = await meetupApi.detail(
          created.recruit_id,
        )

        setSelectedMeetup(detail)

        await loadParticipation(
          created.recruit_id,
          detail,
        )

        setView('detail')
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

  const updateMeetup = async (payload) => {
    if (!selectedMeetup) return null

    setBusy(true)
    setError('')
    setActionMessage('')

    try {
      const updated = await meetupApi.update(
        selectedMeetup.recruit_id,
        payload,
      )

      await refreshDetail(
        selectedMeetup.recruit_id,
      )

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
      // 게시글 논리 삭제이며 프로젝트 운영 취소와 다르다.
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

  // payload가 있으면 프로젝트 신청,
  // payload가 없으면 스터디 신청이다.
  const changeParticipation = async (
    join,
    payload = null,
  ) => {
    if (!selectedMeetup || busy) {
      return null
    }

    const isWithdrawal =
      !join &&
      selectedMeetup?.permissions?.can_withdraw === true

    if (isWithdrawal) {
      const confirmed = window.confirm(
        '모임 시작 후 중도이탈로 처리됩니다.\n\n중도이탈이 누적 3회 이상이면 이후 모든 종류의 모임에 새로 신청할 수 없습니다. 시작 전 신청 취소는 집계하지 않으며, 제한 전에 접수된 유효 신청은 유지됩니다.\n\n정말 중도이탈할까요?',
      )

      if (!confirmed) {
        return null
      }
    }

    setBusy(true)
    setError('')
    setActionMessage('')

    try {
      const result = join
        ? await meetupApi.join(
            selectedMeetup.recruit_id,
            payload,
          )
        : await meetupApi.cancelJoin(
            selectedMeetup.recruit_id,
          )

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

      // 프로젝트 신청 모달은 오류를 자체 표시해야 하므로
      // 신청서가 있는 요청에서는 호출자에게 다시 전달한다.
      if (join && payload != null) {
        throw err
      }

      return null
    } finally {
      setBusy(false)
    }
  }

  const extendProject = async (payload) => {
    if (!selectedMeetup?.recruit_id || busy) {
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

      throw err
    } finally {
      setBusy(false)
    }
  }

  const chooseExceptionStart = async () => {
    if (!selectedMeetup?.recruit_id || busy) {
      return null
    }

    const scheduleVersion =
      getScheduleVersion(selectedMeetup)

    if (!scheduleVersion) {
      setError(
        '최신 일정 버전을 확인할 수 없습니다. 상세 정보를 다시 불러와주세요.',
      )
      return null
    }

    const confirmed = window.confirm(
      '필수 기술이 부족한 현재 확정 구성으로 시작하도록 결정할까요?\n\n이 결정은 기술 조건만 예외로 처리하며, 프로젝트는 예정 시작 시각에 실제 시작됩니다.',
    )

    if (!confirmed) {
      return null
    }

    setBusy(true)
    setError('')
    setActionMessage('')

    try {
      const result =
        await meetupApi.chooseExceptionStart(
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

  const cancelProject = async () => {
    if (!selectedMeetup?.recruit_id || busy) {
      return null
    }

    const reason = window.prompt(
      '프로젝트 취소 사유를 입력해주세요.',
      '',
    )

    if (reason == null) {
      return null
    }

    const trimmedReason = reason.trim()

    if (!trimmedReason) {
      setError('프로젝트 취소 사유를 입력해주세요.')
      return null
    }

    const confirmed = window.confirm(
      '프로젝트를 취소할까요?\n기존 참여·신청 이력은 서버에 유지됩니다.',
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

  const endProjectEarly = async () => {
    if (!selectedMeetup?.recruit_id || busy) {
      return null
    }

    const reason = window.prompt(
      '프로젝트 중도 종료 사유를 입력해주세요.',
      '',
    )

    if (reason == null) {
      return null
    }

    const trimmedReason = reason.trim()

    if (!trimmedReason) {
      setError('중도 종료 사유를 입력해주세요.')
      return null
    }

    const confirmed = window.confirm(
      '프로젝트를 중도 종료할까요?\n중도 종료는 정상 완료와 구분되어 기록됩니다.',
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
    actionMessage,

    openMeetup,
    goBack,
    backToDetail,
    openWrite,
    openEdit,
    createMeetup,
    updateMeetup,
    deleteMeetup,
    changeParticipation,

    extendProject,
    chooseExceptionStart,
    cancelProject,
    endProjectEarly,
  }
}
