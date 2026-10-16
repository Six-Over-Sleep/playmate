import { useCommentForm } from '../../hooks/board/useBoardForms'

/** 제출 상태는 부모와 공유하고, 실패 시 초안을 유지하는 로직은 hook에 둔다. */
export default function CommentForm({ busy, onSubmit }) {
  const { body, setBody, submit } = useCommentForm(busy, onSubmit)

  return (
    <form className="comment-form" onSubmit={submit}>
      <textarea
        aria-label="댓글 내용"
        maxLength={2000}
        rows={3}
        value={body}
        disabled={busy}
        onChange={(event) => setBody(event.target.value)}
        placeholder="댓글을 입력해주세요."
      />
      <button className="button mint" disabled={busy || !body.trim()}>
        댓글 작성
      </button>
    </form>
  )
}
