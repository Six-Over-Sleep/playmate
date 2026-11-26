import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchInsight } from '../../services/careerInsightsApi'
import { boardApi } from '../../services/boardApi'
import { meetupApi } from '../../services/meetupApi'
import { getCategoryMeta, getMeetupStatus } from '../../utils/meetup'
import insightAlien from '../../assets/home-insight-alien.png'

// 아이콘은 별도 패키지 없이 시안의 입체감 있는 라인 스타일 SVG로 렌더링합니다.
function QuickNavIcon({ name }) {
  const paths = {
    board: <><path d="M5 5.5h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9l-5.5 4V7.5A2 2 0 0 1 5 5.5Z" /><path d="M8.5 10.5h8M8.5 14h5.5" /></>,
    meetup: <><circle cx="9" cy="8" r="3"/><path d="M2.75 21v-1.5A5.5 5.5 0 0 1 8.25 14h1.5a5.5 5.5 0 0 1 5.5 5.5V21"/><circle cx="18" cy="9" r="2.5"/><path d="M17 15h1a4.25 4.25 0 0 1 4.25 4.25V21"/></>,
    career: <><rect x="2.5" y="7.5" width="19" height="14" rx="2"/><path d="M8.5 7.5V5a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v2.5M2.5 13h19M10 13v2.5h4V13"/></>,
    growth: <><path d="M3 20.5h18M5.5 17V12M11.5 17V8.5M17.5 17V5"/><path d="m4 9 5-4 4 2.5 6-5M16.5 2.5H19v2.5"/></>,
  }
  return <svg className="home-quick-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

const NAV = [
  { id: 'board', label: '게시판' },
  { id: 'meetup', label: '모임' },
  { id: 'career', label: '취업' },
  { id: 'growth', label: '성장' },
]
const asList = (value) => Array.isArray(value) ? value : Array.isArray(value?.items) ? value.items : []
const number = (value) => Number(value || 0).toLocaleString('ko-KR')

function TopFive({ title, items, withMascot = false }) {
  const top = asList(items).slice(0, 5)
  const max = Math.max(1, ...top.map((item) => Number(item.count) || 0))
  // 실제 건수는 그대로 보여 주되, 막대 길이는 순위 차이를 읽기 쉽도록 비선형으로 강조합니다.
  const barWidth = (count) => {
    const value = Math.max(0, Number(count) || 0)
    return value === 0 ? '0%' : `${Math.max(8, Math.pow(value / max, 3) * 100)}%`
  }
  return <section className={`home-top-five${withMascot ? ' home-top-five--mascot' : ''}`}>
    {withMascot && <img className="home-insight-alien" src={insightAlien} alt="" aria-hidden="true" />}
    <h3>{title} <span className="home-top-five-label">TOP 5</span></h3>
    {top.length ? <ol>{top.map((item, index) => <li key={`${item.name}-${index}`}>
      <span className="home-rank-number">{String(index + 1).padStart(2, '0')}</span>
      <span className="home-rank-name" title={item.name}>{item.name}</span>
      <span className="home-rank-bar" title={`${number(item.count)}건 · 길이는 차이를 강조한 비선형 표시`}><i style={{ width: barWidth(item.count) }} /></span>
      <strong>{number(item.count)}건</strong>
    </li>)}</ol> : <p className="home-no-data">표시할 데이터가 없습니다.</p>}
  </section>
}

// 왼쪽 직무별 막대그래프와 다르게 기술 스택은 박스 없이 1위 강조 + 2열 순위 목록으로 표시합니다.
// 데이터의 실제 순위와 건수는 그대로 유지합니다.
function StackRanking({ items }) {
  const top = asList(items).slice(0, 5)
  return <section className="home-top-five home-top-five--mascot home-top-five--skills" aria-label="기술 스택 상위 순위">
    <img className="home-insight-alien" src={insightAlien} alt="" aria-hidden="true" />
    <h3>기술 스택 <span className="home-top-five-label">TOP 5</span></h3>
    {top.length ? <ol className="home-stack-list">
      {top.map((item, index) => <li key={`${item.name}-${index}`} className={index === 0 ? 'home-stack-first' : ''}>
        <span className="home-stack-index">{String(index + 1).padStart(2, '0')}</span>
        <span className="home-stack-info">
          <span className="home-stack-name" title={item.name}>{item.name}</span>
          {index === 0 && <small>가장 많이 등장한 기술</small>}
        </span>
        <span className="home-stack-count"><strong>{number(item.count)}</strong><small>건</small></span>
      </li>)}
    </ol> : <p className="home-no-data">표시할 기술 스택 데이터가 없습니다.</p>}
    <p className="home-stack-note">수집 공고에서 확인된 기술 스택 기준</p>
  </section>
}

// 데이터가 없을 때 카드 중앙에 표시하는 전용 안내 UI입니다.
function HomeEmptyState({ type, title, description, action, onAction }) {
  const isMeetup = type === 'meetup'
  return (
    <div className="home-empty-state" role="status">
      <svg className="home-empty-state-icon" width="46" height="46" viewBox="0 0 48 48" fill="none" stroke="currentColor" strokeWidth="2.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {isMeetup ? (
          <>
            <circle cx="18" cy="15" r="6" />
            <path d="M5.5 36v-3.3A12.5 12.5 0 0 1 18 20.2a12.5 12.5 0 0 1 12.5 12.5V36" />
            <circle cx="34.5" cy="17" r="5" />
            <path d="M33.5 24.5a10 10 0 0 1 9 10V36" />
          </>
        ) : (
          <>
            <path d="M8 9h19a4 4 0 0 1 4 4v13a4 4 0 0 1-4 4H17l-9 7V13a4 4 0 0 1 4-4Z" />
            <path d="M33 19h4a4 4 0 0 1 4 4v18l-8-7h-5" />
          </>
        )}
      </svg>
      <strong>{title}</strong>
      <p>{description}</p>
      <button className="home-empty-state-action" type="button" onClick={onAction}>{action}</button>
    </div>
  )
}

export default function HomePage({ onNavigate }) {
  const navigate = useNavigate()
  const [insights, setInsights] = useState(null)
  const [insightError, setInsightError] = useState('')
  const [posts, setPosts] = useState([])
  const [meetups, setMeetups] = useState([])
  const [postError, setPostError] = useState('')
  const [meetupError, setMeetupError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    fetchInsight('summary', {}, controller.signal)
      .then(setInsights)
      .catch((error) => { if (error.name !== 'AbortError') setInsightError('채용 통계를 불러올 수 없습니다.') })
    boardApi.featuredPosts('hot', '', { signal: controller.signal })
      .then((data) => setPosts(asList(data)))
      .catch((error) => { if (error.name !== 'AbortError') setPostError('HOT 게시글을 불러올 수 없습니다.') })
    // meetupApi.list()는 취소 신호를 받지 않으므로 마운트 상태를 별도로 확인합니다.
    let active = true
    meetupApi.list()
      .then((data) => { if (active) setMeetups(asList(data)) })
      .catch(() => { if (active) setMeetupError('모임 목록을 불러올 수 없습니다.') })
    return () => { active = false; controller.abort() }
  }, [])

  const openPost = (post) => {
    const boardId = Number(post.board_id)
    const postId = Number(post.id)
    if (boardId > 0 && postId > 0) navigate(`/board/${boardId}/posts/${postId}`)
    else navigate('/board/hot')
  }
  const suggested = [...meetups]
    .filter((meetup) => !['closed', 'deadline', 'completed'].includes(getMeetupStatus(meetup).className))
    .slice(0, 4)

  return <main className="playmate-home">
    <div className="home-night-surface">
      <section className="home-insights-shell">
        <div className="home-section-heading">
          <div className="home-section-copy">
            <div className="home-section-title-row">
              <h1>채용 인사이트</h1>
              <button type="button" onClick={() => onNavigate('career')}>전체보기 <span aria-hidden="true">›</span></button>
            </div>
            <p>채용 트렌드로 보는 지금, 가장 주목받는 직무와 기술 스택</p>
          </div>
        </div>
        {insightError && <p className="home-insights-message" role="status">{insightError} 취업 메뉴에서 다시 확인해 주세요.</p>}
        <div className="home-insights-grid">
          <TopFive title="직무별 공고" items={insights?.roles} />
          <StackRanking items={insights?.skills} />
        </div>
        <p className="home-insights-footnote">* 수집된 공고 표본의 실제 건수이며 시장 전체 통계가 아닙니다. 막대 길이는 차이를 강조한 비선형 표시입니다.</p>
      </section>
    </div>

    <div className="home-quick-wrap"><nav className="home-quick-links" aria-label="바로가기">
      {NAV.map((item) => <button key={item.id} type="button" onClick={() => onNavigate(item.id)}>
        <span className="home-quick-icon"><QuickNavIcon name={item.id} /></span><strong>{item.label}</strong><span className="home-quick-arrow">→</span>
      </button>)}
    </nav></div>

    <div className="home-community-layout">
      <section className="home-community-panel">
        <div className="home-panel-title"><h2><span>🔥</span> HOT 게시판</h2><button type="button" onClick={() => navigate('/board/hot')}>더보기 ›</button></div>
        {postError && <p className="home-panel-empty">{postError}</p>}
        {!postError && (posts.length ? <ol className="home-hot-list">{posts.slice(0, 5).map((post, i) => <li key={post.id}>
          <button type="button" onClick={() => openPost(post)}>
            <span className="home-hot-number">{i + 1}</span>
            <span className="home-hot-copy"><strong>{post.title}</strong><small>{post.author_name || '익명'} <span>♡ {number(post.like_count)}</span> <span>☏ {number(post.comment_count)}</span></small></span>
          </button>
        </li>)}</ol> : <HomeEmptyState type="board" title="아직 HOT 게시글이 없어요" description="커뮤니티의 첫 인기글을 만들어 보세요!" action="글 작성하기" onAction={() => onNavigate('board')} />)}
      </section>
      <section className="home-community-panel">
        <div className="home-panel-title"><h2><span className="home-heading-emoji" role="img" aria-label="함께하는 모임">🤝</span> 추천 스터디 · 프로젝트 모임</h2><button type="button" onClick={() => onNavigate('meetup')}>더보기 ›</button></div>
        {meetupError && <p className="home-panel-empty">{meetupError}</p>}
        {!meetupError && (suggested.length ? <div className="home-meetup-grid">{suggested.map((meetup) => <button type="button" key={meetup.recruit_id ?? meetup.id} onClick={() => navigate(`/meetup/${meetup.recruit_id ?? meetup.id}`)}>
          <span className="home-meetup-type">{getCategoryMeta(meetup.category).label}</span>
          <strong>{meetup.title}</strong><span className="home-meetup-meta">{getMeetupStatus(meetup).label} · {meetup.participant_count ?? meetup.member_count ?? 0}/{meetup.capacity ?? '-'}명</span>
        </button>)}</div> : <HomeEmptyState type="meetup" title="아직 추천 모임이 없어요" description="함께 성장할 팀원을 직접 모집해 보세요!" action="모임 만들기" onAction={() => onNavigate('meetup')} />)}
      </section>
    </div>
  </main>
}
