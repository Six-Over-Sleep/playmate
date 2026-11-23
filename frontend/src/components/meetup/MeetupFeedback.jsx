import { useEffect, useRef, useId } from 'react'

export function MeetupNotice({ message, error, onClose }) {
  useEffect(() => {
    if (!message || error) return
    const timer = setTimeout(onClose, 5000)
    return () => clearTimeout(timer)
  }, [message, error, onClose])
  if (!message) return null
  return <div className={`meetup-notice meetup-toast ${error ? 'error' : 'success'}`} role={error ? 'alert' : 'status'}>
    <span aria-hidden="true">{error ? '!' : '✓'}</span><span>{message}</span>
    <button type="button" aria-label="알림 닫기" onClick={onClose}>×</button>
  </div>
}

export function MeetupConfirm({ busy, onCancel, onConfirm, title = '모임을 삭제할까요?', description = '삭제하면 목록에서 사라져요. 진행 중인 모임은 운영 취소 절차를 확인해주세요.' }) {
  const dialog = useRef(null)
  const titleId = useId()
  useEffect(() => {
    const previous = document.activeElement
    dialog.current.showModal()
    return () => { previous?.focus() }
  }, [])
  return <dialog ref={dialog} className="meetup-confirm" aria-labelledby={titleId}
    onCancel={(event) => { event.preventDefault(); if (!busy) onCancel() }}>
    <h2 id={titleId}>{title}</h2>
    <p>{description}</p>
    <div className="meetup-action-buttons">
      <button autoFocus type="button" disabled={busy} onClick={onCancel}>돌아가기</button>
      <button className="delete" type="button" disabled={busy} onClick={onConfirm}>{busy ? '삭제 중...' : '삭제하기'}</button>
    </div>
  </dialog>
}
