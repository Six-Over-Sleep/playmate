import { useState } from 'react'

export default function CommentForm({ busy, onSubmit }) {
  const [body, setBody] = useState('')
  const submit = async (event) => { event.preventDefault(); if (!body.trim()) return; await onSubmit(body.trim()); setBody('') }
  return <form className="comment-form" onSubmit={submit}><textarea aria-label="댓글 내용" maxLength="2000" rows="3" value={body} onChange={(e) => setBody(e.target.value)} placeholder="댓글을 입력해주세요."/><button className="button mint" disabled={busy || !body.trim()}>댓글 작성</button></form>
}

