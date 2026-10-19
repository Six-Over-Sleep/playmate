import MeetupPage from '../../pages/meetup/MeetupPage'
import MeetupDetailPage from '../../pages/meetup/MeetupDetailPage'
import MeetupEditorPage from '../../pages/meetup/MeetupEditorPage'
import useMeetups from '../../hooks/meetup/useMeetups'

export default function MeetupSection() {
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
