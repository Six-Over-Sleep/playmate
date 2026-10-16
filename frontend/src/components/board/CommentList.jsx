import { useCommentEditor } from '../../hooks/board/useBoardForms'
import { formatBoardDate } from '../../utils/board'

/** 댓글 한 개의 표시와 편집 UI. 서버가 내려준 is_owner로 기존 버튼 표시를 유지한다. */
function Comment({ comment, busy, onEdit, onDelete }) {
  const editor = useCommentEditor(comment, busy, onEdit)

  return (
    <article className="comment">
      <div className="comment-avatar">익</div>
      <div className="comment-content">
        <div>
          <strong>{comment.author_name}</strong>
          <time>{formatBoardDate(comment.created_at)}</time>
        </div>
        {editor.editing ? (
          <div className="inline-edit">
            <textarea
              aria-label="댓글 수정 내용"
              value={editor.body}
              maxLength={2000}
              disabled={busy}
              onChange={(event) => editor.setBody(event.target.value)}
            />
            <button disabled={busy || !editor.body.trim()} onClick={editor.save}>저장</button>
            <button disabled={busy} onClick={editor.cancelEditing}>취소</button>
          </div>
        ) : (
          <p>{comment.body}</p>
        )}
        {comment.is_owner && !editor.editing && (
          <div className="owner-actions">
            <button disabled={busy} onClick={editor.startEditing}>수정</button>
            <button disabled={busy} onClick={() => onDelete(comment.id)}>삭제</button>
          </div>
        )}
      </div>
    </article>
  )
}

/** 서버의 댓글 순서와 id를 유지해 편집 중인 댓글의 상태가 다른 댓글로 이동하지 않게 한다. */
export default function CommentList({ comments, busy, onEdit, onDelete }) {
  if (!comments.length) return <p className="empty-state compact">첫 댓글을 남겨보세요.</p>

  return (
    <div>
      {comments.map((comment) => (
        <Comment
          key={comment.id}
          comment={comment}
          busy={busy}
          onEdit={onEdit}
          onDelete={onDelete}
        />
      ))}
    </div>
  )
}
