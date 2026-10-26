import MeetupPage from '../../pages/meetup/MeetupPage'
import MeetupDetailPage from '../../pages/meetup/MeetupDetailPage'
import MeetupEditorPage from '../../pages/meetup/MeetupEditorPage'
import useMeetups from '../../hooks/meetup/useMeetups'

export default function MeetupSection({
  currentMemberId = null,
}) {
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

  return (
    <>
      {error && (
        <div className="error-banner" role="alert">
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
            actionMessage={actionMessage}
            onBack={goBack}
            onEdit={openEdit}
            onDelete={deleteMeetup}
            onJoin={(payload) =>
              changeParticipation(true, payload)
            }
            onCancelJoin={() =>
              changeParticipation(false)
            }
            onExtendProject={extendProject}
            onChooseExceptionStart={chooseExceptionStart}
            onCancelProject={cancelProject}
            onEndEarly={endProjectEarly}
          />
        )}

      {!detailLoading && view === 'editor' && (
        <MeetupEditorPage
          key={selectedMeetup?.recruit_id ?? 'new'}
          meetup={selectedMeetup}
          busy={busy}
          onBack={selectedMeetup ? backToDetail : goBack}
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
