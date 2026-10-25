import { useCommentForm } from '../../hooks/board/useBoardForms'

/**
 * 제출 상태는 부모와 공유하고, 실패 시 초안을 유지하는 로직은 hook에 둔다.
 * 답글 입력에도 재사용하므로 안내 문구와 버튼 이름만 바꿀 수 있게 한다.
 */
export default function CommentForm({
  busy,
  onSubmit,
  placeholder = '댓글을 입력해주세요.',
  submitLabel = '댓글 작성',
}) {
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
        placeholder={placeholder}
      />
      <button className="button mint" disabled={busy || !body.trim()}>
        {submitLabel}
      </button>
    </form>
  )
}
