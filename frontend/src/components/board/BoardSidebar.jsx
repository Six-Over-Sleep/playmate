import { useState } from 'react'
import '../../styles/boardSidebar.css'

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
    .replace(/^[📢🏆🔥]\s*/u, '')
    .trim()
}

// DB의 게시판 이름은 변경하지 않고 화면에만 이모지를 추가한다.
function getDisplayName(board) {
  const name = getOriginalName(board)

  if (name === '공지사항') return '📢 공지사항'
  if (name === '명예의 전당') return '🏆 명예의 전당'
  if (name === 'HOT 게시판') return '🔥 HOT 게시판'

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
  busy,
  selectedId,
  onSelect,
  onCreate,
}) {
  const [search, setSearch] = useState('')
  const [expanded, setExpanded] = useState(false)
  const [collapsed, setCollapsed] = useState(false)

  const allBoards = Array.isArray(boards) ? boards : []

  // 주요 게시판은 검색·접기 여부에 상관없이 상단에 고정한다.
  const specialBoards = allBoards
    .filter(isSpecialBoard)
    .sort((first, second) => {
      const firstOrder = SPECIAL_BOARD_ORDER[getOriginalName(first)] ?? 99
      const secondOrder = SPECIAL_BOARD_ORDER[getOriginalName(second)] ?? 99

      return firstOrder - secondOrder
    })

  const normalBoards = allBoards.filter((board) => !isSpecialBoard(board))
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

  // 현재 선택된 게시판에 강조 스타일을 적용한다.
  function boardButton(board) {
    const selected = String(board.id) === String(selectedId)

    return (
      <button
        type="button"
        key={board.id}
        className={`board-directory-item${selected ? ' active' : ''}`}
        aria-current={selected ? 'page' : undefined}
        disabled={busy}
        onClick={() => onSelect(board)}
        title={getDisplayName(board)}
      >
        {getDisplayName(board)}
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

      {/* 일반 게시판: 이름 검색, 접기, 펼치기 */}
      <div className="board-directory-group">
        <div className="board-directory-heading">
          <span className="board-directory-label">
            일반 게시판 <small>{normalBoards.length}</small>
          </span>

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

        {/* 접혀 있어도 검색창은 보여서 게시판을 바로 찾을 수 있다. */}
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
