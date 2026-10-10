export default function BoardSidebar({
  boards = [],
  selectedId,
  onSelect,
  onCreate,
}) {
  return (
    <aside className="board-sidebar" aria-label="게시판 목록">
      {(boards || []).map((board) => (
        <button
          type="button"
          key={board.id}
          className={board.id === selectedId ? 'active' : ''}
          aria-current={board.id === selectedId ? 'page' : undefined}
          onClick={() => onSelect(board)}
        >
          {board.name}
        </button>
      ))}

      <div className="sidebar-spacer" />

      <button
        type="button"
        className="create-board"
        onClick={onCreate}
      >
        ＋ 게시판 만들기
      </button>
    </aside>
  )
}