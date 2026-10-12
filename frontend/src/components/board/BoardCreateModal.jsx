import { useState } from 'react'

export default function BoardCreateModal({ open, busy, onClose, onCreate }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [reason, setReason] = useState('')

  if (!open) return null

  const submit = async (event) => {
    event.preventDefault()
    if (busy || !name.trim()) return

    const created = await onCreate({
      name: name.trim(),
      category: '자유',
      description: description.trim() || null,
      creation_reason: reason.trim() || null,
    })

    if (created) {
      setName('')
      setDescription('')
      setReason('')
    }
  }

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={onClose}
    >
      <section
        className="modal board-create-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="board-modal-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <button
          type="button"
          className="modal-close"
          onClick={onClose}
          aria-label="닫기"
        >
          ×
        </button>

        <h2 id="board-modal-title">새 게시판 만들기</h2>
        <p>관심 있는 주제로, 자유롭게 모여요.</p>

        <form onSubmit={submit}>
          <label>
            게시판 이름 *
            <input
              autoFocus
              required
              maxLength={40}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="예: 알고리즘 질문"
            />
          </label>

          <label>
            게시판 소개 (선택)
            <textarea
              maxLength={200}
              rows={3}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="어떤 이야기를 나눌 공간인가요?"
            />
            <small>게시판 목록에 공개돼요.</small>
          </label>

          <label>
            만드는 이유 (선택 · 설계 제안)
            <textarea
              maxLength={500}
              rows={3}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="새 공간이 필요한 이유를 알려주세요."
            />
            <small>
              게시판 설명과 별도로 기록해요. 다른 회원에게 공개하지 않아요.
            </small>
          </label>

          <div className="modal-actions">
            <button
              type="button"
              className="button ghost"
              onClick={onClose}
            >
              취소
            </button>
            <button
              type="submit"
              className="button mint"
              disabled={busy || !name.trim()}
            >
              {busy ? '생성 중…' : '생성'}
            </button>
          </div>
        </form>
      </section>
    </div>
  )
}