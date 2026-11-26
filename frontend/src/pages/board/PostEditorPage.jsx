import BoardSidebar from '../../components/board/BoardSidebar'
import PostForm from '../../components/board/PostForm'

/** 게시판 상세와 동일한 공통 레이아웃에서 작성·수정 폼을 표시합니다. */
export default function PostEditorPage({
  boards, memberCourse, memberCohort, board, post, busy,
  onSelectBoard, onCreateBoard, onBack, onSubmit,
}) {
  return (
    <main className="board-shell pm-board-dashboard pm-board-detail-page pm-board-editor-page">
      <div className="pm-board-title">
        <div><h1>게시판</h1></div>
        <p>배우고, 공유하고, 함께 성장하는 PlayMate 이야기</p>
      </div>
      <div className="board-grid">
        <BoardSidebar
          boards={boards}
          memberCourse={memberCourse}
          memberCohort={memberCohort}
          busy={busy}
          selectedId={board?.id}
          onSelect={onSelectBoard}
          onCreate={onCreateBoard}
        />
        <div className="pm-board-content">
          <section className="detail-content pm-board-detail-card pm-board-editor-card">
            <div className="editor-heading">
              <div>
                <h1>{post ? '게시글 수정' : '게시글 작성'}</h1>
                <p>{board.name} · 작성 시 익명 여부를 선택할 수 있어요.</p>
              </div>
              <span className="anonymous-chip">익명 선택 가능</span>
            </div>
            <PostForm initial={post} busy={busy} onCancel={onBack} onSubmit={onSubmit} />
          </section>
        </div>
      </div>
    </main>
  )
}
