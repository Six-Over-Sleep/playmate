import PostForm from '../../components/board/PostForm'

/** 작성·수정 화면은 동일한 폼을 사용한다. 기존 익명 관련 문구는 정책 확인 전 유지한다. */
export default function PostEditorPage({ board, post, busy, onBack, onSubmit }) {
  return (
    <main className="detail-shell editor-shell">
      <div className="editor-heading">
        <div>
          <h1>{post ? '게시글 수정' : '새 글 쓰기'}</h1>
          <p>{board.name} · 모든 글은 익명으로 표시돼요.</p>
        </div>
        <span className="anonymous-chip">익명 사용자</span>
      </div>
      <PostForm initial={post} busy={busy} onCancel={onBack} onSubmit={onSubmit} />
    </main>
  )
}
