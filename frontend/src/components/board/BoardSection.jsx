import BoardCreateModal from './BoardCreateModal'
import BoardPage from '../../pages/board/BoardPage'
import PostDetailPage from '../../pages/board/PostDetailPage'
import PostEditorPage from '../../pages/board/PostEditorPage'
import { useBoard } from '../../hooks/board/useBoard'

/** 게시판 전용 hook의 상태와 화면만 연결한다. 인증·모임 상태는 여기서 관리하지 않는다. */
export default function BoardSection({ resetVersion }) {
  const boardState = useBoard(resetVersion)
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
          {detailLoading && <p className="empty-state" role="status">글을 불러오는 중…</p>}

          {view === 'list' && (
            <BoardPage
              boards={boards}
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

          {view === 'editor' && board && (
            <PostEditorPage
              key={post?.id ?? 'new'}
              board={board}
              post={post}
              busy={busy}
              onBack={boardState.cancelEditor}
              onSubmit={boardState.savePost}
            />
          )}

          {view === 'detail' && post && (
            <PostDetailPage
              key={post.id}
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
