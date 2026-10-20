import MeetupPage from '../../pages/meetup/MeetupPage'
import MeetupDetailPage from '../../pages/meetup/MeetupDetailPage'
import MeetupEditorPage from '../../pages/meetup/MeetupEditorPage'
import useMeetups from '../../hooks/meetup/useMeetups'

// 모임 훅의 상태와 동작을 목록·상세·편집 화면에 연결하는 상위 컴포넌트.
export default function MeetupSection() {
  // 데이터 조회와 변경, 화면 전환 상태는 useMeetups에서 관리함.
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
    openMeetup,
    goBack,
    backToDetail,
    openWrite,
    openEdit,
    createMeetup,
    updateMeetup,
    deleteMeetup,
    changeParticipation,
  } = useMeetups()

  return (
    <>
      {error && (
        <div
          className="error-banner"
          role="alert"
        >
          {error}
        </div>
      )}

      {/* 상세 데이터를 불러오는 동안 목록·상세·편집 화면 대신 로딩 문구를 표시함. */}
      {detailLoading && (
        <main className="meetup-page">
          <p>모임 정보를 불러오는 중...</p>
        </main>
      )}

      {/* 목록에서 카드 선택과 모임 작성 동작을 연결함. */}
      {!detailLoading && view === 'list' && (
        <MeetupPage
          meetups={meetups}
          loading={loading}
          onMeetup={openMeetup}
          onWrite={openWrite}
        />
      )}

      {/* 선택한 모임이 있을 때 상세 정보와 참여·취소 등의 동작을 전달함. */}
      {!detailLoading && view === 'detail' && selectedMeetup && (
        <MeetupDetailPage
          meetup={selectedMeetup}
          members={members}
          memberCount={memberCount}
          joined={joined}
          busy={busy}
          onBack={goBack}
          onEdit={openEdit}
          onDelete={deleteMeetup}
          onJoin={() => changeParticipation(true)}
          onCancelJoin={() => changeParticipation(false)}
        />
      )}

      {/* 신규/기존 모임에 따라 등록·수정 및 돌아가기 동작을 구분함.
          key가 바뀌면 편집 컴포넌트를 새로 생성해 이전 폼 상태가 남지 않게 함. */}
      {!detailLoading && view === 'editor' && (
        <MeetupEditorPage
          key={selectedMeetup?.recruit_id ?? 'new'}
          meetup={selectedMeetup}
          busy={busy}
          onBack={selectedMeetup ? backToDetail : goBack}
          onSubmit={selectedMeetup ? updateMeetup : createMeetup}
        />
      )}
    </>
  )
}
