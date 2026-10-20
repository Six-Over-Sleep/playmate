import { getMemberName } from '../../utils/meetup'

// 참여 인원수와 멤버 목록을 표시하고, 확인 가능한 모임장에게 배지를 붙임.
export default function MeetupMemberList({
  members = [],
  currentCount = 0,
  ownerId,
}) {
  // 명시적인 모임장 플래그를 먼저 확인하고, 없으면 전달받은 ownerId와 비교함.
  const isHostMember = (member) => {
    if (member?.is_host || member?.is_owner) return true
    const id = member?.member_id ?? member?.id
    // API에서 ID를 숫자 또는 문자열로 받을 수 있어 문자열로 통일해 비교함.
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
