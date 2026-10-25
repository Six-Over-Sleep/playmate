import { useState } from 'react'
import { formatDateTime } from '../../utils/meetup'

// 모임 댓글 목록과 작성·답글·수정·삭제 입력을 표시함.
// 서버가 부모 → 대댓글 순서로 내려주므로 parent_comment_id가 있으면 들여쓰기만 함.
export default function MeetupCommentList({
  comments = [],
  busy = false,
  onAdd,
  onEdit,
  onDelete,
}) {
  const [body, setBody] = useState('')
  const [replyTargetId, setReplyTargetId] = useState(null)
  const [replyBody, setReplyBody] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [editBody, setEditBody] = useState('')

  // 삭제 자리표시는 실제 댓글이 아니므로 개수에서 제외함.
  const commentCount = comments.filter((comment) => !comment.is_deleted).length

  // 성공했을 때만 입력값을 비워 실패 시 작성 중인 내용을 유지함.
  const submitComment = async (event) => {
    event.preventDefault()
    if (!body.trim()) return

    if (await onAdd(body.trim())) setBody('')
  }

  const submitReply = async (event) => {
    event.preventDefault()
    if (!replyBody.trim()) return

    if (await onAdd(replyBody.trim(), replyTargetId)) {
      setReplyTargetId(null)
      setReplyBody('')
    }
  }

  const saveEdit = async (commentId) => {
    if (!editBody.trim()) return

    if (await onEdit(commentId, editBody.trim())) setEditingId(null)
  }

  // 답글 입력창은 최상위 댓글 하나에만 열림. 같은 댓글을 다시 누르면 닫힘.
  const toggleReply = (commentId) => {
    setReplyTargetId((prev) => (prev === commentId ? null : commentId))
    setReplyBody('')
  }

  const startEdit = (comment) => {
    setEditingId(comment.comment_id)
    setEditBody(comment.body)
  }

  // 일반 댓글과 답글이 같은 입력 모양을 사용함.
  const renderForm = (value, setValue, onSubmit, placeholder, label) => (
    <form
      className="meetup-comment-form"
      onSubmit={onSubmit}
    >
      <textarea
        aria-label={placeholder}
        rows={3}
        maxLength={2000}
        value={value}
        disabled={busy}
        placeholder={placeholder}
        onChange={(event) => setValue(event.target.value)}
      />
      <div className="meetup-action-buttons">
        <button
          type="submit"
          className="meetup-join-button"
          disabled={busy || !value.trim()}
        >
          {label}
        </button>
      </div>
    </form>
  )

  return (
    <section className="meetup-comment-section">
      <h2>댓글 ({commentCount})</h2>

      {comments.length > 0 ? (
        <ul className="meetup-comment-list">
          {comments.map((comment) => {
            const isReply = comment.parent_comment_id != null

            // 삭제된 부모 댓글은 살아 있는 대댓글이 있을 때만 서버가 자리표시로 내려줌.
            if (comment.is_deleted) {
              return (
                <li
                  key={comment.comment_id}
                  className="meetup-comment deleted"
                >
                  <p className="meetup-comment-body">삭제된 댓글입니다.</p>
                </li>
              )
            }

            return (
              <li
                key={comment.comment_id}
                className={isReply ? 'meetup-comment reply' : 'meetup-comment'}
              >
                <div className="meetup-comment-head">
                  <strong>{comment.author_name}</strong>
                  <span>{formatDateTime(comment.created_at)}</span>
                </div>

                {editingId === comment.comment_id ? (
                  <div className="meetup-comment-edit">
                    <textarea
                      aria-label="댓글 수정 내용"
                      rows={3}
                      maxLength={2000}
                      value={editBody}
                      disabled={busy}
                      onChange={(event) => setEditBody(event.target.value)}
                    />
                    <div className="meetup-owner-actions">
                      <button
                        type="button"
                        disabled={busy || !editBody.trim()}
                        onClick={() => saveEdit(comment.comment_id)}
                      >
                        저장
                      </button>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => setEditingId(null)}
                      >
                        취소
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <p className="meetup-comment-body">{comment.body}</p>

                    {/* 대댓글은 1단계까지만 허용되므로 최상위 댓글에만 답글 버튼을 둠. */}
                    <div className="meetup-owner-actions">
                      {!isReply && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => toggleReply(comment.comment_id)}
                        >
                          {replyTargetId === comment.comment_id
                            ? '답글 취소'
                            : '답글'}
                        </button>
                      )}

                      {comment.is_owner && (
                        <>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => startEdit(comment)}
                          >
                            수정
                          </button>
                          <button
                            type="button"
                            className="delete"
                            disabled={busy}
                            onClick={() => onDelete(comment.comment_id)}
                          >
                            삭제
                          </button>
                        </>
                      )}
                    </div>
                  </>
                )}

                {replyTargetId === comment.comment_id &&
                  renderForm(
                    replyBody,
                    setReplyBody,
                    submitReply,
                    '답글을 입력해주세요.',
                    '답글 작성',
                  )}
              </li>
            )
          })}
        </ul>
      ) : (
        <div className="meetup-member-empty">첫 댓글을 남겨보세요.</div>
      )}

      {renderForm(
        body,
        setBody,
        submitComment,
        '댓글을 입력해주세요.',
        '댓글 작성',
      )}
    </section>
  )
}
