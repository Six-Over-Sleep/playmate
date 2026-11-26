import { useState, useRef } from 'react'
import { MeetupNotice, MeetupConfirm } from './MeetupFeedback'
import { useNavigate, useLocation } from 'react-router-dom'

import MeetupPage from '../../pages/meetup/MeetupPage'
import MeetupDetailPage from '../../pages/meetup/MeetupDetailPage'
import MeetupEditorPage from '../../pages/meetup/MeetupEditorPage'
import useMeetups from '../../hooks/meetup/useMeetups'

export default function MeetupSection({
  currentMemberId = null,
  isAdmin = false,
} = {}) {
  const navigate = useNavigate()
  const location = useLocation()
  const listUrl = useRef('/meetup')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [creationCategory, setCreationCategory] = useState('study')

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
    comments, toggleLike, toggleScrap, addComment, editComment, deleteComment, dismissNotice,
    commentsLoading,

    goBack,
    backToDetail,
    openWrite,
    openEdit,
    createMeetup,
    updateMeetup,
    deleteMeetup,
    changeParticipation,
    createActivity,

    extendProject,
    chooseExceptionStart,
    cancelProject,
    endProjectEarly,
  } = useMeetups({
    currentMemberId,
  })

  // =========================================================
  // 2. 모임 목록 → 상세 페이지 이동
  // =========================================================

  // 상세 조회는 useMeetups의 URL Effect 한 곳에서만 처리한다.
  // 여기서는 URL만 변경해서 동일 상세가 두 번 호출되지 않게 한다.
  const handleOpenMeetup = (meetup) => {
    const recruitId = Number(meetup?.recruit_id)

    if (
      !Number.isSafeInteger(recruitId) ||
      recruitId <= 0
    ) {
      console.error('잘못된 모임 ID:', meetup)
      return
    }

    listUrl.current = `/meetup${location.search}`
    navigate(`/meetup/${recruitId}`)
  }

  // =========================================================
  // 3. 상세 페이지 → 모임 목록 이동
  // =========================================================

  const handleGoBack = () => {
    goBack(false)
    navigate(listUrl.current)
  }

  // =========================================================
  // 4. 화면 렌더링
  // =========================================================

  return (
    <>
      <MeetupNotice message={error || actionMessage} error={Boolean(error)} onClose={dismissNotice} />
      {!detailLoading && view === 'error' && (
        <main className="meetup-page meetup-detail-error">
          <h1>모임을 열 수 없어요.</h1>
          <p>{error || '모임 주소를 확인하고 다시 이용해주세요.'}</p>
          <button type="button" onClick={handleGoBack}>모임 목록으로 돌아가기</button>
        </main>
      )}
      {confirmDelete && <MeetupConfirm busy={busy} onCancel={() => setConfirmDelete(false)} onConfirm={async () => { await deleteMeetup(); setConfirmDelete(false) }} />}

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
          onWrite={(category) => {
            // 목록에서 고른 종류를 새 모임에도 유지한다. 전체 탭은 스터디가 기본이다.
            setCreationCategory(category === 'all' ? 'study' : category)
            openWrite()
          }}
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
            currentMemberId={currentMemberId}
            onDelete={() => setConfirmDelete(true)}
            onLike={toggleLike}
            onScrap={toggleScrap}
            comments={comments}
            commentsLoading={commentsLoading}
            onAddComment={addComment}
            onEditComment={editComment}
            onDeleteComment={deleteComment}

            // 모임 참여
            onJoin={(payload) =>
              changeParticipation(true, payload)
            }

            // 참여 취소
            onCancelJoin={() =>
              changeParticipation(false)
            }

            // 활동 인증 / 후기
            onAddActivity={createActivity}

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
          isAdmin={isAdmin}
          initialCategory={creationCategory}
          key={selectedMeetup?.recruit_id ?? 'new'}
          meetup={selectedMeetup}
          busy={busy}

          onBackToList={handleGoBack}

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
