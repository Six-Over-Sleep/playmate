import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getMyActivities } from '../../services/mypageApi'

const PAGE_SIZE = 10

const TABS = [
  { id: 'posts', label: '내 게시글' },
  { id: 'comments', label: '내 댓글' },
  { id: 'scraps', label: '내 스크랩' },
  { id: 'meetups', label: '내 모임' },
]


// 날짜 표시
function formatDate(value) {
  return value
    ? value.replace('T', ' ').slice(0, 16)
    : '날짜 정보 없음'
}


// 모임 모집 상태
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


// 모임 운영 방식
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


// 모임 카테고리
function getMeetupCategory(category) {
  const categories = {
    study: '스터디',
    game: '게임',
    exercise: '운동',
    group_buy: '공동구매',
  }

  return (
    categories[category?.toLowerCase()] ||
    category ||
    '모임'
  )
}


// =========================================================
// 게시글 상세 페이지 URL 생성
// =========================================================

function getPostUrl(item) {
  const postId = item.post_id

  if (!postId) {
    return null
  }

  // 자유게시판
  if (item.post_type === 'BOARD') {
    if (!item.board_id) {
      return null
    }

    return `/board/${item.board_id}/posts/${postId}`
  }

  // 취업 게시판
  if (item.post_type === 'CAREER') {
    const categoryMap = {
      '취준도감': 'reviews',
      '커리어 톡톡': 'talk',
      '현직자 라운지': 'lounge',
      '커리어 연구소': 'lab',
    }

    const category =
      item.career_category ||
      categoryMap[item.board_name]

    if (category) {
      return `/career/${category}/${postId}`
    }
  }

  return null
}


// =========================================================
// 마이페이지 내 활동
// =========================================================

export default function MyActivity({ onOpenMeetup }) {
  const navigate = useNavigate()

  const [activeTab, setActiveTab] = useState('posts')
  const [items, setItems] = useState([])

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [page, setPage] = useState(1)
  const [totalCount, setTotalCount] = useState(0)


  // =========================================================
  // 페이지네이션
  // =========================================================

  const isServerTab =
    activeTab === 'posts' ||
    activeTab === 'comments'

  const queryPage = isServerTab ? page : 1

  const totalPages = isServerTab
    ? Math.ceil(totalCount / PAGE_SIZE)
    : Math.ceil(items.length / PAGE_SIZE)

  const visibleItems = isServerTab
    ? items
    : items.slice(
        (page - 1) * PAGE_SIZE,
        page * PAGE_SIZE,
      )


  // =========================================================
  // 탭 변경
  // =========================================================

  const handleTabChange = (tabId) => {
    if (tabId === activeTab) {
      return
    }

    setActiveTab(tabId)
    setPage(1)
    setItems([])
    setTotalCount(0)
  }


  // =========================================================
  // 활동 내역 조회
  // =========================================================

  useEffect(() => {
    let active = true

    setLoading(true)
    setError('')
    setItems([])

    getMyActivities(activeTab, queryPage)
      .then((data) => {
        if (!active) {
          return
        }

        if (isServerTab) {
          if (!data || !Array.isArray(data.items)) {
            throw new Error(
              '활동 조회 응답 형식이 올바르지 않습니다.',
            )
          }

          setItems(data.items)
          setTotalCount(Number(data.total) || 0)

        } else {
          if (!Array.isArray(data)) {
            throw new Error(
              '활동 조회 응답 형식이 올바르지 않습니다.',
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

    return () => {
      active = false
    }

  }, [activeTab, queryPage, isServerTab])


  // =========================================================
  // 게시글 / 댓글 / 스크랩 표시 정보
  // =========================================================

  const getDisplay = (item) => {
    switch (activeTab) {
      case 'posts':
        return {
          title: item.title,
          description: '',
          meta:
            `${item.board_name || '기타 게시글'} · ` +
            formatDate(item.created_at),
        }

      case 'comments':
        return {
          title: item.post_title,
          description: item.body,
          meta:
            `${item.parent_comment_id ? '대댓글' : '댓글'} · ` +
            formatDate(item.created_at),
        }

      case 'scraps':
        return {
          title: item.title,
          description: '',
          meta: `스크랩 · ${formatDate(item.scrapped_at)}`,
        }

      default:
        return {
          title: '',
          description: '',
          meta: '',
        }
    }
  }


  // =========================================================
  // 모임 상세 이동
  // =========================================================

  const openMyMeetup = (recruitId) => {
    if (!recruitId) {
      return
    }

    navigate(`/meetup/${recruitId}`)
  }


  // =========================================================
  // 화면
  // =========================================================

  return (
    <div className="mypage-activity">

      <h2>내 활동</h2>

      {/* 활동 유형 탭 */}
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
            className={
              activeTab === tab.id ? 'active' : ''
            }
            onClick={() => handleTabChange(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>


      {/* 활동 목록 */}
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

          // =========================================
          // 내 모임 목록
          // =========================================

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

                  // 모임 카드 클릭 시 상세 페이지 이동
                  onClick={() =>
                    openMyMeetup(item.recruit_id)
                  }

                  // 키보드 접근 지원
                  role="link"
                  tabIndex={0}

                  onKeyDown={(event) => {
                    if (
                      event.key === 'Enter' ||
                      event.key === ' '
                    ) {
                      event.preventDefault()
                      openMyMeetup(item.recruit_id)
                    }
                  }}

                  title="모임 상세 보기"
                >

                  {/* 모임 카테고리 및 상태 */}
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


                  {/* 참여 정보 */}
                  <div className="mypage-meetup-details">

                    <span>
                      {isHost
                        ? '👑 모임장'
                        : '👤 참여자'}
                    </span>

                    <span>
                      {getMeetupMode(item.recruit_mode)}
                    </span>

                  </div>


                  {/* 모임 ID 및 생성일 */}
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

          // =========================================
          // 내 게시글 / 댓글 / 스크랩
          // =========================================

          <ul className="mypage-activity-list">

            {visibleItems.map((item) => {
              const data = getDisplay(item)

              const id =
                item.comment_id ??
                item.post_id

              const url = getPostUrl(item)

              return (
              <li
                key={id}
                className="mypage-activity-item"
                onClickCapture={(e) => {
                  if (
                    ['comments', 'scraps'].includes(activeTab) &&
                    item.recruit_id != null
                  ) {
                    e.stopPropagation()
                    onOpenMeetup(Number(item.recruit_id))
                  }
                }}
              >

                  {url ? (

                    <button
                      type="button"
                      className="mypage-activity-post-link"
                      onClick={() => navigate(url)}
                      title="게시글 상세 보기"
                    >

                      <strong>{data.title}</strong>

                      {data.description && (
                        <span className="mypage-activity-description">
                          {data.description}
                        </span>
                      )}

                      <span className="mypage-activity-meta">
                        {data.meta}
                      </span>

                    </button>

                  ) : (

                    <>
                      <strong>{data.title}</strong>

                      {data.description && (
                        <p className="mypage-activity-description">
                          {data.description}
                        </p>
                      )}

                      <span className="mypage-activity-meta">
                        {data.meta}
                      </span>
                    </>

                  )}

                </li>
              )
            })}

          </ul>
        )}

      </div>


      {/* =========================================
          페이지네이션
          ========================================= */}

      {!loading && !error && totalPages > 1 && (

        <div className="mypage-pagination">

          <button
            type="button"
            disabled={page === 1}
            onClick={() =>
              setPage((prev) =>
                Math.max(1, prev - 1),
              )
            }
          >
            이전
          </button>


          {Array.from(
            { length: totalPages },
            (_, index) => index + 1,
          ).map((number) => (

            <button
              key={number}
              type="button"
              className={
                page === number ? 'active' : ''
              }
              aria-label={`${number}페이지`}
              aria-current={
                page === number
                  ? 'page'
                  : undefined
              }
              onClick={() => setPage(number)}
            >
              {number}
            </button>

          ))}


          <button
            type="button"
            disabled={page === totalPages}
            onClick={() =>
              setPage((prev) =>
                Math.min(
                  totalPages,
                  prev + 1,
                ),
              )
            }
          >
            다음
          </button>

        </div>

      )}

    </div>
  )
}