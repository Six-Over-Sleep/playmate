/** 게시판 선택과 생성 이벤트를 부모로 전달한다. 저장 중에는 선택을 잠근다. */
export default function BoardSidebar({
  boards = [],
  busy,
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
          disabled={busy}
          onClick={() => onSelect(board)}
        >
          {board.name}
        </button>
      ))}

      <div className="sidebar-spacer" />

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
