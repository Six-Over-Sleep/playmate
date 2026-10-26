import { useMemo, useState } from 'react'
import MeetupCard from '../../components/meetup/MeetupCard'
import MeetupCategoryTabs from '../../components/meetup/MeetupCategoryTabs'
import {
  CATEGORY_OPTIONS,
  isClosedMeetup,
  normalizeCategory,
} from '../../utils/meetup'

// 카테고리별 모임 목록과 작성 버튼 표시
export default function MeetupPage({
  meetups = [],
  loading = false,
  onMeetup,
  onWrite,
}) {
  const [category, setCategory] = useState('all')

  // 선택한 카테고리 기준 목록 필터링
  const visibleMeetups = useMemo(() => {
    const filtered =
      category === 'all'
        ? [...meetups]
        : meetups.filter(
            (meetup) => normalizeCategory(meetup.category) === category,
          )

    // 모집 가능한 모임 우선,
    // 동일한 상태에서는 최근 생성된 모임(recruit_id가 큰 값)을 먼저 표시
    return filtered.sort((a, b) => {
      const aClosed = isClosedMeetup(a)
      const bClosed = isClosedMeetup(b)

      if (aClosed !== bClosed) {
        return aClosed ? 1 : -1
      }

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

      <MeetupCategoryTabs
        categories={CATEGORY_OPTIONS}
        value={category}
        onChange={setCategory}
      />

      {/* 로딩·빈 목록·카드 목록 분기 */}
      {loading ? (
        <div className="meetup-empty">
          모임을 불러오는 중이에요.
        </div>
      ) : visibleMeetups.length === 0 ? (
        <div className="meetup-empty">
          이 카테고리에 등록된 모임이 아직 없어요.
        </div>
      ) : (
        <section
          className="meetup-grid"
          aria-label="모임 목록"
        >
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