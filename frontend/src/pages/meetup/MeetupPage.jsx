import { useMemo, useState } from 'react'
import MeetupCard from '../../components/meetup/MeetupCard'

const CATEGORIES = [
  { value: 'all', label: '전체' },
  { value: 'sports', label: '🏃 운동' },
  { value: 'game', label: '🎮 게임' },
  { value: 'study', label: '📖 스터디' },
  { value: 'group_buy', label: '🛒 공동구매' },
]

function normalizeCategory(value) {
  if (!value) return ''
  const category = String(value).toLowerCase()

  if (['sports', 'sport', 'exercise', '운동'].includes(category)) return 'sports'
  if (['game', 'gaming', '게임'].includes(category)) return 'game'
  if (['study', '스터디'].includes(category)) return 'study'
  if (['group_buy', 'groupbuy', 'purchase', '공동구매'].includes(category)) return 'group_buy'

  return category
}

function isClosedMeetup(meetup) {
  const state = String(meetup?.state ?? meetup?.status ?? '').toUpperCase()
  return ['CLOSED', 'CANCELLED', 'CANCELED', 'EXPIRED', 'FULL'].includes(state)
}

export default function MeetupPage({
  meetups = [],
  loading = false,
  onMeetup,
  onWrite,
}) {
  const [category, setCategory] = useState('all')

  const visibleMeetups = useMemo(() => {
    const filtered =
      category === 'all'
        ? [...meetups]
        : meetups.filter(
            (meetup) => normalizeCategory(meetup.category) === category,
          )

    // 모집 가능한 모임을 먼저 보여주고, 마감된 모임은 아래쪽으로 보낸다.
    return filtered.sort((a, b) => {
      const aClosed = isClosedMeetup(a)
      const bClosed = isClosedMeetup(b)

      if (aClosed !== bClosed) return aClosed ? 1 : -1

      const aId = Number(a.recruit_id ?? a.id ?? 0)
      const bId = Number(b.recruit_id ?? b.id ?? 0)
      return bId - aId
    })
  }, [meetups, category])

  return (
    <main className="meetup-page">
      <div className="meetup-title-row">
        <div>
          <h1>모임</h1>
          <p>같이할 사람을 찾아보세요.</p>
        </div>

        <button
          type="button"
          className="meetup-write-button"
          onClick={onWrite}
        >
          + 모임 만들기
        </button>
      </div>

      <div className="meetup-tabs" role="tablist" aria-label="모임 카테고리">
        {CATEGORIES.map((item) => (
          <button
            key={item.value}
            type="button"
            className={category === item.value ? 'active' : ''}
            onClick={() => setCategory(item.value)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="meetup-empty">모임을 불러오는 중이에요.</div>
      ) : visibleMeetups.length === 0 ? (
        <div className="meetup-empty">
          이 카테고리에 등록된 모임이 아직 없어요.
        </div>
      ) : (
        <section className="meetup-grid" aria-label="모임 목록">
          {visibleMeetups.map((meetup, index) => (
            <MeetupCard
              key={meetup.recruit_id ?? meetup.id}
              meetup={meetup}
              featured={index === 0}
              onClick={() => onMeetup?.(meetup)}
            />
          ))}
        </section>
      )}
    </main>
  )
}
