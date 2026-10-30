// PLAYMATE_COMMENT_ANON_EDIT_V2
// PLAYMATE_BOARD_ANONYMOUS_V1
import { useState } from 'react'
import { useCommentEditor } from '../../hooks/board/useBoardForms'
import { formatBoardDate } from '../../utils/board'
import CommentForm from './CommentForm'

/**
 * 댓글 한 개의 표시와 편집 UI. 서버가 내려준 is_owner로 기존 버튼 표시를 유지한다.
 * 서버가 부모 → 대댓글 순서로 내려주므로 parent_comment_id가 있으면 들여쓰기만 한다.
 * 대댓글은 1단계까지만 허용되므로 최상위 댓글에만 답글 버튼을 둔다.
 */
function Comment({ comment, busy, onEdit, onDelete, onReply }) {
  const editor = useCommentEditor(comment, busy, onEdit)
  const [replying, setReplying] = useState(false)
  const isReply = Boolean(comment.parent_comment_id)

  /** 답글 성공 응답을 받았을 때만 입력창을 닫는다. 실패하면 초안이 남는다. */
  async function submitReply(body, _parentCommentId, isAnonymous = false) {
    const result = await onReply(body, comment.id, isAnonymous)
    if (result) setReplying(false)
    return result
  }

  // 삭제된 부모 댓글은 살아 있는 대댓글이 있을 때만 서버가 자리표시로 내려준다.
  if (comment.is_deleted) {
    return (
      <article className="comment deleted">
        <div className="comment-avatar">-</div>
        <div className="comment-content">
          <p>삭제된 댓글입니다.</p>
        </div>
      </article>
    )
  }

  return (
    <article className={isReply ? 'comment reply' : 'comment'}>
      <div className="comment-avatar">{comment.is_anonymous ? '익' : (comment.author_name?.charAt(0) || 'U')}</div>
      <div className="comment-content">
        <div>
          <strong>{comment.author_name}</strong>
          <time>{formatBoardDate(comment.created_at)}</time>
        </div>
        {editor.editing ? (
          <div className="inline-edit">
            <div className="board-comment-edit-fields">
              <textarea
                aria-label="댓글 수정 내용"
                value={editor.body}
                maxLength={2000}
                disabled={busy}
                onChange={(event) => editor.setBody(event.target.value)}
              />
              <label className="board-anonymous-option">
                <input
                  type="checkbox"
                  checked={editor.isAnonymous}
                  disabled={busy}
                  onChange={(event) => editor.setIsAnonymous(event.target.checked)}
                />
                익명으로 표시
              </label>
            </div>
            <button type="button" disabled={busy || !editor.body.trim()} onClick={editor.save}>저장</button>
            <button type="button" disabled={busy} onClick={editor.cancelEditing}>취소</button>
          </div>
        ) : (
          <p>{comment.body}</p>
        )}
        {!editor.editing && (
          <div className="comment-actions">
            {!isReply && (
              <button disabled={busy} onClick={() => setReplying((open) => !open)}>
                {replying ? '답글 취소' : '답글'}
              </button>
            )}
            {comment.is_owner && (
              <div className="owner-actions">
                <button disabled={busy} onClick={editor.startEditing}>수정</button>
                <button disabled={busy} onClick={() => onDelete(comment.id)}>삭제</button>
              </div>
            )}
          </div>
        )}
        {replying && (
          <CommentForm
            busy={busy}
            onSubmit={submitReply}
            placeholder="답글을 입력해주세요."
            submitLabel="답글 작성"
          />
        )}
      </div>
    </article>
  )
}

/** 서버의 댓글 순서와 id를 유지해 편집 중인 댓글의 상태가 다른 댓글로 이동하지 않게 한다. */
export default function CommentList({ comments, busy, onEdit, onDelete, onReply }) {
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
          onReply={onReply}
        />
      ))}
    </div>
  )
}
