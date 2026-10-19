import { getMemberName } from '../../utils/meetup'

export default function MeetupMemberList({
  members = [],
  currentCount = 0,
  ownerId,
}) {
  const isHostMember = (member) => {
    if (member?.is_host || member?.is_owner) return true
    const id = member?.member_id ?? member?.id
    return ownerId != null && id != null && String(id) === String(ownerId)
  }

  return (
    <section className="meetup-member-section">
      <h2>참여 멤버 ({currentCount})</h2>
      {members.length > 0 ? (
        <ul className="meetup-member-list">
          {members.map((member, index) => (
            <li key={member.member_id ?? member.id ?? index}>
              <div className="meetup-member-info">
                <span
                  className="meetup-member-avatar"
                  aria-hidden="true"
                />
                <span>{getMemberName(member, index)}</span>
              </div>
              {isHostMember(member) && (
                <span className="meetup-host-badge">모임장</span>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <div className="meetup-member-empty">아직 참여 멤버 정보가 없어요.</div>
      )}
    </section>
  )
}
