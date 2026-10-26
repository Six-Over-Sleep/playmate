// PLAYMATE - 내 활동 상세 기록
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getMyActivities, getMyLikes } from '../../services/mypageApi'

const PAGE_SIZE = 10

// 요청하신 네 가지 활동을 먼저 배치하고, 기존 '내 모임'은 유지합니다.
const TABS = [
  { id: 'comments', label: '댓글·대댓글' },
  { id: 'likes', label: '좋아요' },
  { id: 'posts', label: '작성 게시글' },
  { id: 'scraps', label: '스크랩' },
  { id: 'meetups', label: '내 모임' },
]

function formatDate(value) {
  return value ? String(value).replace('T', ' ').slice(0, 16) : '날짜 정보 없음'
}

function getPostUrl(item) {
  const postId = Number(item.post_id)
  const recruitId = Number(item.recruit_id)
  const postType = String(item.post_type || '').toUpperCase()

  if (Number.isSafeInteger(recruitId) && recruitId > 0) {
    return `/meetup/${recruitId}`
  }
  if (postType === 'RECRUIT') return null
  if (!Number.isSafeInteger(postId) || postId <= 0) return null

  if (postType === 'CAREER') {
    const names = {
      '취준도감': 'reviews',
      '취준 도감': 'reviews',
      '커리어 톡톡': 'talk',
      '현직자 라운지': 'lounge',
      '커리어 연구소': 'lab',
    }
    const category = String(item.career_category || item.category_code || names[item.board_name] || '').toLowerCase()
    if (['reviews', 'talk', 'lounge', 'lab'].includes(category)) {
      return `/career/${category}/${postId}`
    }
    return null
  }

  const boardId = Number(item.board_id)
  return Number.isSafeInteger(boardId) && boardId > 0
    ? `/board/${boardId}/posts/${postId}`
    : null
}

function getDisplay(type, item) {
  switch (type) {
    case 'comments':
      return {
        title: item.post_title || '댓글의 원본 게시글',
        description: item.body || '',
        meta: `${item.parent_comment_id ? '대댓글' : '댓글'} · ${formatDate(item.created_at)}`,
      }
    case 'likes':
      return {
        title: item.title || '제목 없음',
        description: '',
        meta: `${item.board_name || '기타 게시판'} · ${item.comment_id != null || String(item.target_type || '').toUpperCase() === 'COMMENT' ? '댓글' : '게시글'} · ${formatDate(item.liked_at)}`,
      }
    case 'posts':
      return {
        title: item.title || '제목 없음',
        description: '',
        meta: `${item.board_name || '작성 게시글'} · ${formatDate(item.created_at)}`,
      }
    case 'scraps':
      return {
        title: item.title || '제목 없음',
        description: '',
        meta: `스크랩 · ${formatDate(item.scrapped_at)}`,
      }
    default:
      return { title: '', description: '', meta: '' }
  }
}

function getMeetupStatus(state) {
  switch (String(state || '').toUpperCase()) {
    case 'OPEN': return '모집 중'
    case 'CLOSED':
    case 'CLOSE': return '모집 마감'
    default: return state || '상태 미정'
  }
}

function getMeetupCategory(category) {
  const names = { study: '스터디', game: '게임', sports: '운동', exercise: '운동', group_buy: '공동구매' }
  return names[String(category || '').toLowerCase()] || category || '모임'
}

function getMeetupMode(mode) {
  return String(mode || '').toLowerCase() === 'regular' ? '정기모임' : '단기모임'
}

// 백엔드 구버전(배열)과 서버 페이지네이션 버전({items,total})을 모두 지원합니다.
function normalizePage(data, page) {
  if (Array.isArray(data)) {
    return {
      items: data.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
      total: data.length,
    }
  }
  if (data && Array.isArray(data.items)) {
    return { items: data.items, total: Number(data.total) || 0 }
  }
  throw new Error('활동 조회 응답 형식이 올바르지 않습니다.')
}

export default function MyActivity({ onOpenMeetup, onOpenPost }) {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('comments')
  const [items, setItems] = useState([])
  const [totalCount, setTotalCount] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    setItems([])
    setLoading(true)
    setError('')

    const request = activeTab === 'likes'
      ? getMyLikes(page)
      : getMyActivities(activeTab, page)

    Promise.resolve(request)
      .then((data) => {
        if (!active) return
        const result = normalizePage(data, page)
        setItems(result.items)
        setTotalCount(result.total)
      })
      .catch((cause) => {
        if (active) setError(cause.message || '내 활동을 불러오지 못했습니다.')
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => { active = false }
  }, [activeTab, page])

  const changeTab = (tabId) => {
    if (tabId === activeTab) return
    setActiveTab(tabId)
    setPage(1)
    setItems([])
    setTotalCount(0)
  }

  const openMeetup = (value) => {
    const id = Number(value)
    if (!Number.isSafeInteger(id) || id <= 0) return
    if (typeof onOpenMeetup === 'function') onOpenMeetup(id)
    else navigate(`/meetup/${id}`)
  }

  const openOriginal = (item, url) => {
    if (!url) return
    if (url.startsWith('/meetup/')) {
      openMeetup(item.recruit_id)
    } else if (typeof onOpenPost === 'function') {
      onOpenPost(item)
    } else {
      navigate(url)
    }
  }

  const totalPages = Math.ceil(totalCount / PAGE_SIZE)

  return (
    <section className="mypage-activity" aria-labelledby="mypage-activity-heading">
      <div className="mypage-activity-heading">
        <h3 id="mypage-activity-heading">활동 상세 내역</h3>
        {!loading && !error && <span>총 {totalCount.toLocaleString('ko-KR')}건</span>}
      </div>

      <div className="mypage-activity-tabs" role="tablist" aria-label="활동 유형">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            className={activeTab === tab.id ? 'active' : ''}
            onClick={() => changeTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="mypage-activity-content" role="tabpanel">
        {loading ? (
          <p className="mypage-activity-empty">활동 내역을 불러오는 중...</p>
        ) : error ? (
          <p className="mypage-profile-error" role="alert">활동 조회 실패: {error}</p>
        ) : items.length === 0 ? (
          <p className="mypage-activity-empty">이 카테고리에는 아직 활동 내역이 없습니다.</p>
        ) : activeTab === 'meetups' ? (
          <div className="mypage-meetup-grid">
            {items.map((item) => {
              const isOpen = String(item.state || '').toUpperCase() === 'OPEN'
              const isHost = String(item.role || '').toUpperCase() === 'HOST'
              return (
                <article
                  key={item.recruit_id}
                  className="mypage-meetup-card"
                  role="link"
                  tabIndex={0}
                  title="모임 상세 보기"
                  onClick={() => openMeetup(item.recruit_id)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      openMeetup(item.recruit_id)
                    }
                  }}
                >
                  <div className="mypage-meetup-top">
                    <span className="mypage-meetup-category">{getMeetupCategory(item.category)}</span>
                    <span className={isOpen ? 'mypage-meetup-status open' : 'mypage-meetup-status'}>
                      {isOpen ? '● ' : ''}{getMeetupStatus(item.state)}
                    </span>
                  </div>
                  <h3>{item.title}</h3>
                  <div className="mypage-meetup-details">
                    <span>{isHost ? '👑 모임장' : '👤 참여자'}</span>
                    <span>{getMeetupMode(item.recruit_mode)}</span>
                  </div>
                  <div className="mypage-meetup-footer">
                    <span>모임 #{item.recruit_id}</span>
                    <span>{formatDate(item.created_at)}</span>
                  </div>
                </article>
              )
            })}
          </div>
        ) : (
          <ul className="mypage-activity-list">
            {items.map((item) => {
              const display = getDisplay(activeTab, item)
              const url = getPostUrl(item)
              const key = activeTab === 'comments' ? item.comment_id : item.post_id
              return (
                <li className="mypage-activity-item" key={key}>
                  {url ? (
                    <button
                      type="button"
                      className="mypage-activity-post-link"
                      onClick={() => openOriginal(item, url)}
                      title="원본 게시글 열기"
                    >
                      <strong>{display.title}</strong>
                      {display.description && <span className="mypage-activity-description">{display.description}</span>}
                      <span className="mypage-activity-meta">{display.meta}</span>
                    </button>
                  ) : (
                    <div className="mypage-activity-plain">
                      <strong>{display.title}</strong>
                      {display.description && <p className="mypage-activity-description">{display.description}</p>}
                      <span className="mypage-activity-meta">{display.meta}</span>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>

      {!loading && !error && totalPages > 1 && (
        <div className="mypage-pagination">
          <button type="button" disabled={page === 1} onClick={() => setPage((n) => Math.max(1, n - 1))}>
            이전
          </button>
          {Array.from({ length: totalPages }, (_, index) => index + 1).map((number) => (
            <button
              key={number}
              type="button"
              className={page === number ? 'active' : ''}
              aria-label={`${number}페이지`}
              aria-current={page === number ? 'page' : undefined}
              onClick={() => setPage(number)}
            >
              {number}
            </button>
          ))}
          <button
            type="button"
            disabled={page === totalPages}
            onClick={() => setPage((n) => Math.min(totalPages, n + 1))}
          >
            다음
          </button>
        </div>
      )}
    </section>
  )
}
