import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'

import MeetupPage from '../../pages/meetup/MeetupPage'
import MeetupDetailPage from '../../pages/meetup/MeetupDetailPage'
import MeetupEditorPage from '../../pages/meetup/MeetupEditorPage'
import useMeetups from '../../hooks/meetup/useMeetups'

export default function MeetupSection({
  currentMemberId = null,
  targetMeetupId = null,
}) {
  const navigate = useNavigate()

  // =========================================================
  // 1. 모임 상태 및 함수
  // =========================================================

  const {
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
  } = useMeetups({
    currentMemberId,
  })

  // =========================================================
  // 2. 마이페이지 → 모임 상세 자동 이동
  // =========================================================

  const openedMeetupId = useRef(null)

  useEffect(() => {
    // 모임 ID가 없는 경우: 모임 목록
    if (targetMeetupId == null) {
      if (openedMeetupId.current !== null) {
        openedMeetupId.current = null
        goBack()
      }

      return
    }

    const recruitId = Number(targetMeetupId)

    // 잘못된 모임 ID 검사
    if (
      !Number.isSafeInteger(recruitId) ||
      recruitId <= 0
    ) {
      return
    }

    // 같은 모임 중복 조회 방지
    if (openedMeetupId.current === recruitId) {
      return
    }

    openedMeetupId.current = recruitId

    // 해당 모임의 상세 정보 조회
    void openMeetup({
      recruit_id: recruitId,
    })
  }, [targetMeetupId])

  // =========================================================
  // 3. 모임 목록 → 상세 페이지 이동
  // =========================================================

  const handleOpenMeetup = (meetup) => {
    const recruitId = Number(meetup?.recruit_id)

    if (
      !Number.isSafeInteger(recruitId) ||
      recruitId <= 0
    ) {
      console.error('잘못된 모임 ID:', meetup)
      return
    }

    // 모임 ID가 포함된 주소로 이동
    navigate(`/meetup/${recruitId}`)
  }

  // =========================================================
  // 4. 상세 페이지 → 모임 목록 이동
  // =========================================================

  const handleGoBack = () => {
    goBack()

    openedMeetupId.current = null

    navigate('/meetup')
  }

  // =========================================================
  // 5. 화면 렌더링
  // =========================================================

  return (
    <>
      {/* 오류 메시지 */}
      {error && (
        <div
          className="error-banner"
          role="alert"
        >
          {error}
        </div>
      )}

      {/* 상세 조회 로딩 */}
      {detailLoading && (
        <main className="meetup-page">
          <p>모임 정보를 불러오는 중...</p>
        </main>
      )}

      {/* =====================================
          모임 목록
      ===================================== */}

      {!detailLoading && view === 'list' && (
        <MeetupPage
          meetups={meetups}
          loading={loading}
          onMeetup={handleOpenMeetup}
          onWrite={openWrite}
        />
      )}

      {/* =====================================
          모임 상세 페이지
      ===================================== */}

      {!detailLoading &&
        view === 'detail' &&
        selectedMeetup && (
          <MeetupDetailPage
            meetup={selectedMeetup}
            members={members}
            memberCount={memberCount}
            joined={joined}
            busy={busy}
            actionMessage={actionMessage}

            // 목록으로 돌아가기
            onBack={handleGoBack}

            // 모임 수정 및 삭제
            onEdit={openEdit}
            onDelete={deleteMeetup}

            // 모임 참여
            onJoin={(payload) =>
              changeParticipation(true, payload)
            }

            // 참여 취소
            onCancelJoin={() =>
              changeParticipation(false)
            }

            // 프로젝트 기간 연장
            onExtendProject={extendProject}

            // 예외 시작 선택
            onChooseExceptionStart={chooseExceptionStart}

            // 프로젝트 취소
            onCancelProject={cancelProject}

            // 프로젝트 조기 종료
            onEndEarly={endProjectEarly}
          />
        )}

      {/* =====================================
          모임 작성 및 수정
      ===================================== */}

      {!detailLoading && view === 'editor' && (
        <MeetupEditorPage
          key={selectedMeetup?.recruit_id ?? 'new'}
          meetup={selectedMeetup}
          busy={busy}

          onBack={
            selectedMeetup
              ? backToDetail
              : handleGoBack
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