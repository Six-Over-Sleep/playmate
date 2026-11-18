/* PLAYMATE_FRONTEND_POLISH_V1 */
// PLAYMATE_BOARD_REPORTS_V1
import BoardCreateModal from './BoardCreateModal'
import BoardSidebar from './BoardSidebar'
import BoardPage from '../../pages/board/BoardPage'
import PostDetailPage from '../../pages/board/PostDetailPage'
import PostEditorPage from '../../pages/board/PostEditorPage'
import { useBoard } from '../../hooks/board/useBoard'
import useBoardVisitTracker from '../../hooks/useBoardVisitTracker'

/** 게시판 전용 hook의 상태와 화면만 연결한다. 인증·모임 상태는 여기서 관리하지 않는다. */
export default function BoardSection({ resetVersion, memberCourse, memberCohort }) {
  const boardState = useBoard(resetVersion)
  useBoardVisitTracker(boardState.board?.id)
  const {
    boards, board, posts, post, comments, view, query, loading,
    detailLoading, busy, modal, error, success, initialized,
  } = boardState
  const unavailable = initialized && !board && error

  return (
    <>
      {error && <div className="error-banner" role="alert">{error}</div>}
      {success && <div className="success-toast" role="status">{success}</div>}

      {unavailable ? (
        <main className="service-error">
          <h1>게시판을 불러오지 못했어요</h1>
          <p>{error}</p>
          <button className="button purple" onClick={() => window.location.reload()}>
            다시 시도
          </button>
        </main>
      ) : (
        <>
          {detailLoading && (
            <main className="board-shell pm-board-dashboard pm-board-detail-page pm-board-loading-page" aria-busy="true">
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
                  onSelect={boardState.selectBoard}
                  onCreate={boardState.openModal}
                />
                <div className="pm-board-content">
                  <section className="detail-content pm-board-detail-card pm-board-loading-card" role="status" aria-live="polite">
                    <span className="pm-board-loading-spinner" aria-hidden="true" />
                    <span>게시글을 불러오는 중...</span>
                  </section>
                </div>
              </div>
            </main>
          )}

          {!detailLoading && view === 'list' && (
            <BoardPage
              boards={boards}
              memberCourse={memberCourse}
              memberCohort={memberCohort}
              board={board}
              posts={posts}
              query={query}
              loading={loading}
              busy={busy || !initialized}
              onSelectBoard={boardState.selectBoard}
              onCreateBoard={boardState.openModal}
              onSearch={boardState.searchPosts}
              onWrite={boardState.openEditor}
              onPost={boardState.openPost}
            />
          )}

          {!detailLoading && view === 'editor' && board && (
            <PostEditorPage
              key={post?.id ?? 'new'}
              boards={boards}
              memberCourse={memberCourse}
              memberCohort={memberCohort}
              board={board}
              post={post}
              busy={busy}
              onSelectBoard={boardState.selectBoard}
              onCreateBoard={boardState.openModal}
              onBack={boardState.cancelEditor}
              onSubmit={boardState.savePost}
            />
          )}

          {!detailLoading && view === 'detail' && post && (
            <PostDetailPage
              key={post.id}
              memberCourse={memberCourse}
              memberCohort={memberCohort}
              boards={boards}
              board={board}
              post={post}
              comments={comments}
              busy={busy}
              onSelectBoard={boardState.selectBoard}
              onCreateBoard={boardState.openModal}
              onBack={boardState.backToList}
              onEdit={boardState.editPost}
              onDelete={boardState.deletePost}
              onLike={boardState.toggleLike}
              onScrap={boardState.toggleScrap}
              onReport={boardState.reportPost}
              onComment={boardState.addComment}
              onEditComment={boardState.editComment}
              onDeleteComment={boardState.deleteComment}
            />
          )}
        </>
      )}

      <BoardCreateModal
        open={modal}
        busy={busy}
        onClose={boardState.closeModal}
        onCreate={boardState.createBoard}
      />
    </>
  )
}
