import { getMemberName } from '../../utils/meetup'

// 서버가 참여자를 임의 순서로 반환하더라도 모임장을 먼저 표시한다.
// 일반 참여자는 참여일시가 빠른 순서로 정렬하고, 시간이 없거나 같으면 원래 순서를 유지한다.
const getMemberId = member => member?.member_id ?? member?.id

const isHostMember = (member, ownerId) => {
  if (member?.is_host === true || member?.is_owner === true) return true
  if (['HOST', 'OWNER'].includes(String(member?.role ?? member?.member_role ?? '').toUpperCase())) return true

  const memberId = getMemberId(member)
  return ownerId != null && memberId != null && String(memberId) === String(ownerId)
}

const getJoinedAt = member => {
  const value = member?.joined_at ?? member?.joinedAt
  if (!value) return null

  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? timestamp : null
}

const orderMembers = (members, ownerId) => [...members]
  .map((member, index) => ({ member, index }))
  .sort((a, b) => {
    const aIsHost = isHostMember(a.member, ownerId)
    const bIsHost = isHostMember(b.member, ownerId)
    if (aIsHost !== bIsHost) return aIsHost ? -1 : 1

    const aJoined = getJoinedAt(a.member)
    const bJoined = getJoinedAt(b.member)
    if (aJoined !== null && bJoined !== null && aJoined !== bJoined) return aJoined - bJoined
    if (aJoined !== null && bJoined === null) return -1
    if (aJoined === null && bJoined !== null) return 1
    return a.index - b.index
  })
  .map(({ member }) => member)

// 참여 인원수와 멤버 목록을 표시하고, 확인 가능한 모임장에게 배지를 붙임.
export default function MeetupMemberList({
  members = [],
  currentCount = 0,
  ownerId,
}) {
  const orderedMembers = orderMembers(Array.isArray(members) ? members : [], ownerId)

  return (
    <section className="meetup-member-section">
      <h2>참여 멤버 ({currentCount})</h2>
      {orderedMembers.length > 0 ? (
        <ul className="meetup-member-list">
          {orderedMembers.map((member, index) => {
            // 표시 이름이 같아도 같은 회원으로 간주하지 않는다.
            // API의 실제 회원 ID를 행 식별 기준으로 유지한다.
            const rowMemberId = getMemberId(member)

            const rowKey =
              rowMemberId != null
                ? `member-${String(rowMemberId)}`
                : `member-row-${index}`

            return (
            <li key={rowKey}>
              <div className="meetup-member-info">
                {member.profile_image_url && <img className="meetup-member-avatar" src={member.profile_image_url}
                  alt="" loading="lazy" referrerPolicy="no-referrer"
                  onError={(event) => { event.currentTarget.hidden = true }} />}

                <span
                  className="meetup-member-avatar meetup-member-fallback"
                  aria-hidden="true"
                />
                <span>{getMemberName(member, index)}</span>
              </div>
              {isHostMember(member, ownerId) && (
                <span className="meetup-host-badge">모임장</span>
              )}
            </li>
            )
          })}
        </ul>
      ) : (
        <div className="meetup-member-empty">아직 참여 멤버 정보가 없어요.</div>
      )}
    </section>
  )
}
