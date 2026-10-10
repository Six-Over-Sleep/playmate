import { useState } from 'react'

const formatDate = (value) => new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))

function Comment({ comment, onEdit, onDelete }) {
  const [editing, setEditing] = useState(false)
  const [body, setBody] = useState(comment.body)
  return <article className="comment"><div className="comment-avatar">익</div><div className="comment-content"><div><strong>{comment.author_name}</strong><time>{formatDate(comment.created_at)}</time></div>{editing ? <div className="inline-edit"><textarea value={body} maxLength="2000" onChange={(e) => setBody(e.target.value)}/><button onClick={async () => { await onEdit(comment.id, body.trim()); setEditing(false) }}>저장</button><button onClick={() => setEditing(false)}>취소</button></div> : <p>{comment.body}</p>}{comment.is_owner && !editing && <div className="owner-actions"><button onClick={() => setEditing(true)}>수정</button><button onClick={() => onDelete(comment.id)}>삭제</button></div>}</div></article>
}

export default function CommentList({ comments, onEdit, onDelete }) {
  if (!comments.length) return <p className="empty-state compact">첫 댓글을 남겨보세요.</p>
  return <div>{comments.map((comment) => <Comment key={comment.id} comment={comment} onEdit={onEdit} onDelete={onDelete}/>)}</div>
}

