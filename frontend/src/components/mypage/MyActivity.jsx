import { useEffect, useState } from 'react'
import { getMyActivities } from '../../services/mypageApi'

// 페이지당 표시 개수
const PAGE_SIZE = 10

// 내 활동 탭
const TABS = [
  { id: 'posts', label: '내 게시글' },
  { id: 'comments', label: '내 댓글' },
  { id: 'scraps', label: '내 스크랩' },
  { id: 'likes', label: '내 좋아요' },
  { id: 'meetups', label: '내 모임' },
]

// 날짜 표시
function formatDate(value) {
  return value
    ? value.replace('T', ' ').slice(0, 16)
    : '날짜 정보 없음'
}

// 모집 상태 표시
function getMeetupStatus(state) {
  switch (state?.toUpperCase()) {
    case 'OPEN':
      return '모집 중'
    case 'CLOSE':
    case 'CLOSED':
      return '모집 마감'
    default:
      return state || '상태 미정'
  }
}

// 모임 유형 표시
function getMeetupMode(mode) {
  switch (mode?.toLowerCase()) {
    case 'regular':
      return '상시모임'
    case 'temporary':
    case 'one_time':
      return '일회성 모임'
    default:
      return mode || '모임'
  }
}

// 모임 카테고리 표시
function getMeetupCategory(category) {
  const categories = {
    study: '스터디',
    game: '게임',
    exercise: '운동',
    group_buy: '공동구매',
  }

  return categories[category?.toLowerCase()] || category || '모임'
}

export default function MyActivity({ onOpenPost, onOpenMeetup }) {
  // 현재 탭
  const [activeTab, setActiveTab] = useState('posts')

  // 활동 데이터
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // 페이지네이션
  const [page, setPage] = useState(1)
  const [totalCount, setTotalCount] = useState(0)

  // 게시글·댓글은 Backend 페이지네이션
  const isServerTab =
    activeTab === 'posts' || activeTab === 'comments'

  // Backend에 요청할 페이지
  const queryPage = isServerTab ? page : 1

  // 전체 페이지 수
  const totalPages = isServerTab
    ? Math.ceil(totalCount / PAGE_SIZE)
    : Math.ceil(items.length / PAGE_SIZE)

  // 현재 페이지에 표시할 데이터
  const visibleItems = isServerTab
    ? items
    : items.slice(
        (page - 1) * PAGE_SIZE,
        page * PAGE_SIZE
      )

  // 탭 변경
  const handleTabChange = (tabId) => {
    if (tabId === activeTab) return

    setActiveTab(tabId)
    setPage(1)
    setItems([])
    setTotalCount(0)
  }

  // 활동 데이터 조회
  useEffect(() => {
    let active = true

    setLoading(true)
    setError('')
    setItems([])

    getMyActivities(activeTab, queryPage)
      .then((data) => {
        if (!active) return

        if (isServerTab) {
          // 게시글·댓글 응답:
          // { items: [], total: 0, page: 1, page_size: 10 }

          if (!data || !Array.isArray(data.items)) {
            throw new Error(
              '활동 조회 응답 형식이 올바르지 않습니다.'
            )
          }

          setItems(data.items)
          setTotalCount(Number(data.total) || 0)
        } else {
          // 스크랩·모임은 기존 배열 응답
          if (!Array.isArray(data)) {
            throw new Error(
              '활동 조회 응답 형식이 올바르지 않습니다.'
            )
          }

          setItems(data)
          setTotalCount(data.length)
        }
      })
      .catch((err) => {
        if (active) {
          setError(err.message)
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false)
        }
      })

    // 이전 요청의 응답이 새 탭에 표시되지 않도록 방지
    return () => {
      active = false
    }
  }, [activeTab, queryPage, isServerTab])

  // 게시글·댓글·스크랩 표시 정보
  const getDisplay = (item) => {
    switch (activeTab) {
      case 'posts':
        return {
          title: item.title,
          description: '',
          meta: `${
            item.board_name || '기타 게시글'
          } · ${formatDate(item.created_at)}`,
        }

      case 'comments':
        return {
          title: item.post_title,
          description: item.body,
          meta: `${
            item.parent_comment_id ? '대댓글' : '댓글'
          } · ${formatDate(item.created_at)}`,
        }

      case 'scraps':
        return {
          title: item.title,
          description: '',
          meta: `스크랩 · ${formatDate(item.scrapped_at)}`,
        }

      case 'likes':
        return {
          title: item.title,
          description: '',
          meta: `좋아요 · ${formatDate(item.liked_at)}`,
        }

      default:
        return {
          title: '',
          description: '',
          meta: '',
        }
    }
  }

  return (
    <div className="mypage-activity">

      <h2>내 활동</h2>

      {/* 활동 탭 */}
      <div
        className="mypage-activity-tabs"
        role="tablist"
        aria-label="내 활동 유형"
      >
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            className={activeTab === tab.id ? 'active' : ''}
            onClick={() => handleTabChange(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* 활동 조회 결과 */}
      <div
        className="mypage-activity-content"
        role="tabpanel"
      >
        {loading ? (

          <p className="mypage-activity-empty">
            활동 내역을 불러오는 중...
          </p>

        ) : error ? (

          <p className="mypage-profile-error">
            활동 조회 실패: {error}
          </p>

        ) : items.length === 0 ? (

          <p className="mypage-activity-empty">
            아직 활동 내역이 없습니다.
          </p>

        ) : activeTab === 'meetups' ? (

          // 내 모임: 카드형
          <div className="mypage-meetup-grid">
            {visibleItems.map((item) => {
              const isOpen =
                item.state?.toUpperCase() === 'OPEN'

              const isHost =
                item.role?.toUpperCase() === 'HOST'

              return (
                  <article
                    key={item.recruit_id}
                    className="mypage-meetup-card"
                    role="button"
                    tabIndex={0}
                    onClick={() => onOpenMeetup?.(item)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        onOpenMeetup?.(item)
                      }
                    }}
                  >

                  {/* 카테고리 + 모집 상태 */}
                  <div className="mypage-meetup-top">
                    <span className="mypage-meetup-category">
                      {getMeetupCategory(item.category)}
                    </span>

                    <span
                      className={
                        isOpen
                          ? 'mypage-meetup-status open'
                          : 'mypage-meetup-status'
                      }
                    >
                      {isOpen ? '● ' : ''}
                      {getMeetupStatus(item.state)}
                    </span>
                  </div>

                  {/* 모임 제목 */}
                  <h3>{item.title}</h3>

                  {/* 모임장 여부 및 유형 */}
                  <div className="mypage-meetup-details">
                    <span>
                      {isHost ? '👑 모임장' : '👤 참여자'}
                    </span>

                    <span>
                      {getMeetupMode(item.recruit_mode)}
                    </span>
                  </div>

                  {/* 모임 정보 */}
                  <div className="mypage-meetup-footer">
                    <span>
                      모임 #{item.recruit_id}
                    </span>

                    <span>
                      {formatDate(item.created_at)}
                    </span>
                  </div>

                </article>
              )
            })}
          </div>

        ) : (

          // 게시글·댓글·스크랩: 리스트형
          <ul className="mypage-activity-list">
            {visibleItems.map((item) => {
              const data = getDisplay(item)

              const id =
                item.comment_id ?? item.post_id

              return (
                <li
                  key={id}
                  className="mypage-activity-item"
                >
                  <button
                    type="button"
                    className="mypage-activity-link"
                    onClick={() => onOpenPost(item)}
                  >
                    <strong>{data.title}</strong>

                    {data.description && (
                      <p className="mypage-activity-description">
                        {data.description}
                      </p>
                    )}

                    <span className="mypage-activity-meta">
                      {data.meta}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>

        )}
      </div>

      {/* 페이지네이션 */}
      {!loading && !error && totalPages > 1 && (
        <div className="mypage-pagination">

          {/* 이전 페이지 */}
          <button
            type="button"
            disabled={page === 1}
            onClick={() => {
              setPage((prev) => Math.max(1, prev - 1))
            }}
          >
            이전
          </button>

          {/* 페이지 번호 */}
          {Array.from(
            { length: totalPages },
            (_, index) => index + 1
          ).map((number) => (
            <button
              key={number}
              type="button"
              className={page === number ? 'active' : ''}
              aria-label={`${number}페이지`}
              aria-current={
                page === number ? 'page' : undefined
              }
              onClick={() => setPage(number)}
            >
              {number}
            </button>
          ))}

          {/* 다음 페이지 */}
          <button
            type="button"
            disabled={page === totalPages}
            onClick={() => {
              setPage((prev) =>
                Math.min(totalPages, prev + 1)
              )
            }}
          >
            다음
          </button>

        </div>
      )}
    </div>
  )
}
