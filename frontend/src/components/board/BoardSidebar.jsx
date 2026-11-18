import { useState } from 'react'

// 일반 게시판을 처음에 보여줄 개수
const DEFAULT_VISIBLE_COUNT = 5

// 공지사항, 인기 게시판, 자유게시판은 항상 상단에 표시한다.
const SPECIAL_BOARD_ORDER = {
  '공지사항': 0,
  '명예의 전당': 1,
  'HOT 게시판': 2,
  '자유게시판': 3,
}

// 화면에만 사용하는 이모지를 제외한 게시판 이름
function getOriginalName(board) {
  return String(board?.name || '')
    .replace(/^[📢🏆🔥💬🎓]\s*/u, '')
    .trim()
}

// DB의 게시판 이름은 변경하지 않고 화면에만 이모지를 추가한다.
function getDisplayName(board) {
  const name = getOriginalName(board)

  if (name === '공지사항') return '📢 공지사항'
  if (name === '명예의 전당') return '🏆 명예의 전당'
  if (name === 'HOT 게시판') return '🔥 HOT 게시판'
  if (name === '자유게시판') return '💬 자유게시판'

  return board.name
}

// 일반 게시판과 상단 고정 게시판을 구분한다.
function isSpecialBoard(board) {
  const name = getOriginalName(board)

  return (
    Object.hasOwn(SPECIAL_BOARD_ORDER, name) ||
    board.featured === true
  )
}

/** 게시판 검색·접기·펼치기를 관리하고, 선택 및 생성은 부모에게 전달한다. */
export default function BoardSidebar({
  boards = [],
  memberCourse = null,
  memberCohort = null,
  busy,
  selectedId,
  onSelect,
  onCreate,
}) {
  const [search, setSearch] = useState('')
  const [expanded, setExpanded] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  // 작은 화면에서는 일반 게시판을 접어 두고, 사용자가 원할 때만 펼칩니다.
  const [compactGeneralOpen, setCompactGeneralOpen] = useState(false)

  const allBoards = Array.isArray(boards) ? boards : []

  // 로그인 회원의 실제 과정·기수와 비교합니다. 관리자의 can_write는
  // 모든 게시판에서 true일 수 있으므로 소속 판별에 사용하지 않습니다.
  const hasMemberProfile = Boolean(memberCourse) && memberCohort != null
  const writableCourseBoards = allBoards.filter(
    (item) => item.course_code && item.can_write === true
  )
  const fallbackBoardId = !hasMemberProfile && writableCourseBoards.length === 1
    ? writableCourseBoards[0].id
    : null

  const isMyCourseBoard = (item) => {
    if (!item.course_code) return false
    if (hasMemberProfile) {
      return String(item.course_code) === String(memberCourse)
        && Number(item.cohort) === Number(memberCohort)
    }
    // 개발용 헤더 로그인처럼 프로필이 없을 때만 안전한 대체 기준을 사용합니다.
    return fallbackBoardId != null && String(item.id) === String(fallbackBoardId)
  }

  // 주요 게시판과 내 과정은 각각 분리하되, 기존 게시판 ID/선택 기능은 유지한다.
  const specialBoards = allBoards
    .filter((item) => isSpecialBoard(item) && !isMyCourseBoard(item))
    .sort((first, second) => {
      const firstOrder = SPECIAL_BOARD_ORDER[getOriginalName(first)] ?? 99
      const secondOrder = SPECIAL_BOARD_ORDER[getOriginalName(second)] ?? 99
      return firstOrder - secondOrder
    })

  const myCourseBoards = allBoards.filter((item) => isMyCourseBoard(item))

  // 다른 과정·기수 게시판은 읽기 가능하되 '일반 게시판'으로 분류합니다.
  const normalBoards = allBoards.filter(
    (item) => !isSpecialBoard(item) && !isMyCourseBoard(item)
  )
  const searchWord = search.trim().toLocaleLowerCase()

  // 게시판 이름만 검색한다. 게시글 검색과는 별개다.
  const searchedBoards = searchWord
    ? normalBoards.filter((board) =>
        String(board.name).toLocaleLowerCase().includes(searchWord)
      )
    : normalBoards

  // 접은 상태에서는 5개까지만 표시한다.
  // 현재 선택된 게시판이 5개 밖에 있어도 선택 상태를 볼 수 있도록 유지한다.
  const visibleBoards = searchWord || expanded
    ? searchedBoards
    : searchedBoards.filter((board, index) =>
        index < DEFAULT_VISIBLE_COUNT ||
        String(board.id) === String(selectedId)
      )

  const hiddenCount = Math.max(0, normalBoards.length - visibleBoards.length)
  const hasMoreBoards = normalBoards.length > DEFAULT_VISIBLE_COUNT

  // 표시는 아이콘 + 텍스트로 나누어 주요 게시판의 글자 시작점을 통일한다.
  function boardButton(board) {
    const selected = String(board.id) === String(selectedId)
    const isMine = isMyCourseBoard(board)
    const boardName = getOriginalName(board)
    const boardClass = ({
      '자유게시판': 'free',
      '공지사항': 'notice',
      'HOT 게시판': 'hot',
      '명예의 전당': 'hall',
    })[boardName]
    const icon = isMine ? '🎓' : ({
      '공지사항': '📢',
      '명예의 전당': '🏆',
      'HOT 게시판': '🔥',
      '자유게시판': '💬',
    })[boardName]

    return (
      <button
        type="button"
        key={board.id}
        className={`board-directory-item${selected ? ' active' : ''}${isMine ? ' board-my-course' : ''}${boardClass ? ` board-directory-item--${boardClass}` : ''}`}
        aria-current={selected ? 'page' : undefined}
        disabled={busy}
        onClick={() => onSelect(board)}
        title={isMine ? `내 과정 · ${boardName}` : getDisplayName(board)}
      >
        {icon && <span className="board-directory-item-icon" aria-hidden="true">{icon}</span>}
        <span className="board-directory-item-text">{isMine && <span className="board-mobile-course-prefix">내 과정 · </span>}{boardName}</span>
      </button>
    )
  }

  return (
    <aside className="board-sidebar board-directory" aria-label="게시판 목록">
      {/* 공지사항, 명예의 전당, HOT, 자유게시판은 항상 표시 */}
      {specialBoards.length > 0 && (
        <div className="board-directory-group board-directory-pinned">
          <p className="board-directory-label">주요 게시판</p>

          <div className="board-directory-list">
            {specialBoards.map(boardButton)}
          </div>
        </div>
      )}

      {/* 소속 과정 게시판은 주요 게시판과 분리해서 표시 */}
      {myCourseBoards.length > 0 && (
        <div className="board-directory-group board-directory-own-course">
          <p className="board-directory-label">내 과정</p>
          <div className="board-directory-list">
            {myCourseBoards.map(boardButton)}
          </div>
        </div>
      )}

      {/* 일반 게시판: 이름 검색, 접기, 펼치기 */}
      <div className="board-directory-group board-directory-general">
        <div className="board-directory-heading">
          <span className="board-directory-label">
            일반 게시판 <small>{normalBoards.length}</small>
          </span>

          <button
            type="button"
            className="board-directory-mobile-toggle"
            aria-expanded={compactGeneralOpen}
            aria-controls="board-general-compact-content"
            onClick={() => {
              setCollapsed(false)
              setCompactGeneralOpen((value) => !value)
            }}
          >
            {compactGeneralOpen ? '접기 ▴' : '펼치기 ▾'}
          </button>

          <button
            type="button"
            className="board-directory-collapse"
            aria-expanded={!collapsed}
            aria-label={collapsed ? '일반 게시판 펼치기' : '일반 게시판 접기'}
            onClick={() => setCollapsed((value) => !value)}
          >
            {collapsed ? '펼치기 ▾' : '접기 ▴'}
          </button>
        </div>

        {/* PC에서는 항상 검색창을 노출합니다. 모바일·태블릿에서는 처음에 접습니다. */}
        <div
          id="board-general-compact-content"
          className={`board-directory-general-body${compactGeneralOpen ? ' is-mobile-open' : ''}`}
        >
        <div className="board-directory-search">
          <span aria-hidden="true">⌕</span>
          <input
            type="search"
            value={search}
            placeholder="게시판 이름 검색"
            aria-label="게시판 이름 검색"
            onChange={(event) => {
              setSearch(event.target.value)
              if (event.target.value.trim()) setCollapsed(false)
            }}
          />
        </div>

        {!collapsed && (
          <>
            <div
              className={
                `board-directory-list${expanded || searchWord ? ' expanded' : ''}`
              }
            >
              {visibleBoards.map(boardButton)}
            </div>

            {searchWord && visibleBoards.length === 0 && (
              <p className="board-directory-empty">검색 결과가 없습니다.</p>
            )}

            {/* 검색 중에는 전체 검색 결과를 표시하고, 일반 상태에서만 더보기 제공 */}
            {!searchWord && hasMoreBoards && (
              <button
                type="button"
                className="board-directory-more"
                aria-expanded={expanded}
                onClick={() => setExpanded((value) => !value)}
              >
                {expanded ? '간략히 보기 ▴' : `전체 보기 (${hiddenCount}개 더) ▾`}
              </button>
            )}
          </>
        )}
        </div>
      </div>

      {/* 기존 게시판 생성 기능 유지 */}
      <button
        type="button"
        className="create-board"
        disabled={busy}
        onClick={onCreate}
      >
        ＋ 게시판 만들기
      </button>
    </aside>
  )
}
