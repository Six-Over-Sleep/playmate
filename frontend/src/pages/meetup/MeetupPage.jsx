import { useMemo, useState } from 'react'
import MeetupCard from '../../components/meetup/MeetupCard'
import MeetupCategoryTabs from '../../components/meetup/MeetupCategoryTabs'
import { CATEGORY_OPTIONS, isClosedMeetup, normalizeCategory } from '../../utils/meetup'

// 선택한 카테고리에 맞춰 목록 제목을 표시합니다.
const CATEGORY_HEADINGS = {
  all: '모임 둘러보기',
  study: '스터디 모임',
  project: '프로젝트 모임',
  sports: '운동 모임',
  game: '게임 모임',
  group_buy: '공동구매 모임',
}

export default function MeetupPage({ meetups = [], loading = false, onMeetup, onWrite }) {
  const [category, setCategory] = useState('all')
  const [search, setSearch] = useState('')
  const visibleMeetups = useMemo(() => {
    const word = search.trim().toLocaleLowerCase()
    return (category === 'all' ? [...meetups] : meetups.filter((meetup) => normalizeCategory(meetup.category) === category))
      .filter((meetup) => !word || `${meetup.title ?? ''} ${meetup.body ?? ''}`.toLocaleLowerCase().includes(word))
      .sort((a, b) => {
        const aClosed = isClosedMeetup(a)
        const bClosed = isClosedMeetup(b)
        if (aClosed !== bClosed) return aClosed ? 1 : -1
        return Number(b.recruit_id ?? b.id ?? 0) - Number(a.recruit_id ?? a.id ?? 0)
      })
  }, [meetups, category, search])

  return <main className="meetup-page pm-meetup-page">
    <div className="pm-meetup-title"><h1>모임</h1><p>스터디, 프로젝트, 운동, 게임까지 함께할 동료를 찾아보세요.</p></div>
    <div className="pm-meetup-layout">
      <aside className="pm-meetup-sidebar">
        <div className="pm-meetup-sidebar-heading"><strong>카테고리</strong></div>
        <MeetupCategoryTabs categories={CATEGORY_OPTIONS} value={category} onChange={setCategory} />
      </aside>
      <div className="pm-meetup-main">
        <div className="pm-meetup-search-row"><label className="pm-meetup-search"><span aria-hidden="true">⌕</span><input type="search" value={search} placeholder="모임 이름 또는 내용을 검색하세요" onChange={(event) => setSearch(event.target.value)} /></label><button type="button" className="meetup-write-button" onClick={() => onWrite?.(category)}>＋ 모임 만들기</button></div>
        <div className="pm-meetup-section-head"><h2>{CATEGORY_HEADINGS[category] ?? '모임 둘러보기'}</h2><span>총 {visibleMeetups.length.toLocaleString('ko-KR')}개 모임</span></div>
        {loading ? <div className="meetup-empty">모임을 불러오는 중이에요.</div>
          : visibleMeetups.length === 0 ? <div className="meetup-empty">{search ? '검색 결과가 없습니다.' : '이 카테고리에 등록된 모임이 아직 없어요.'}</div>
            : <section className={`meetup-grid${category === 'all' && !search.trim() ? ' meetup-grid--featured' : ''}`} aria-label="모임 목록">{visibleMeetups.map((meetup) => <MeetupCard key={meetup.recruit_id ?? meetup.id} meetup={meetup} onClick={() => onMeetup?.(meetup)} />)}</section>}
      </div>
    </div>
  </main>
}
