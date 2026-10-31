// PLAYMATE_COMMENT_ANON_EDIT_V2
// PLAYMATE_BOARD_ANONYMOUS_V1
import { useEffect, useRef, useState } from 'react'

/** 입력을 성공 후에만 비우며 같은 렌더 사이의 연속 제출도 ref 잠금으로 막는다. */
export function useCommentForm(busy, onSubmit) {
  const [body, setBody] = useState('')
  const [isAnonymous, setIsAnonymous] = useState(false)
  const submitting = useRef(false)

  /** 공백·중복 제출을 거르고 댓글을 전송한다. 부모가 성공을 반환한 경우에만 초안을 지운다. */
  async function submit(event) {
    event.preventDefault()
    if (busy || submitting.current || !body.trim()) return
    submitting.current = true
    try {
      const result = await onSubmit(body.trim(), null, isAnonymous)
      if (result) {
        setBody('')
        setIsAnonymous(false)
      }
    } finally {
      submitting.current = false
    }
  }

  return { body, setBody, isAnonymous, setIsAnonymous, submit }
}

/** 취소 시 원문으로 복구하고 서버 변경 성공 때만 편집 모드를 닫는다. */
export function useCommentEditor(comment, busy, onEdit) {
  const [editing, setEditing] = useState(false)
  const [body, setBody] = useState(comment.body)
  const [isAnonymous, setIsAnonymous] = useState(Boolean(comment.is_anonymous))
  const submitting = useRef(false)

  /** 마지막 서버 본문을 복사해 편집을 시작한다. 이전에 취소한 초안을 다시 사용하지 않는다. */
  function startEditing() {
    setBody(comment.body)
    setIsAnonymous(Boolean(comment.is_anonymous))
    setEditing(true)
  }

  /** 편집 초안을 원문으로 되돌리고 편집 모드를 닫는다. 서버 요청은 발생하지 않는다. */
  function cancelEditing() {
    setBody(comment.body)
    setIsAnonymous(Boolean(comment.is_anonymous))
    setEditing(false)
  }

  /** 공백·중복 저장을 막고 수정한다. 성공 응답을 받았을 때만 편집을 종료한다. */
  async function save() {
    if (busy || submitting.current || !body.trim()) return
    submitting.current = true
    try {
      const result = await onEdit(comment.id, body.trim(), isAnonymous)
      if (result) setEditing(false)
    } finally {
      submitting.current = false
    }
  }

  return {
    editing, body, setBody, isAnonymous, setIsAnonymous,
    startEditing, cancelEditing, save,
  }
}

/** 게시판 생성이 실패하면 모든 입력을 남기고, 성공 응답을 받은 뒤 초기화한다. */
export function useBoardCreateForm(busy, onCreate) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [reason, setReason] = useState('')
  const submitting = useRef(false)

  /** 입력을 API 계약에 맞게 다듬어 전송한다. 실패 시 이름·소개·사유를 모두 보존한다. */
  async function submit(event) {
    event.preventDefault()
    if (busy || submitting.current || !name.trim()) return
    submitting.current = true
    try {
      const created = await onCreate({
        name: name.trim(),
        description: description.trim() || null,
        creation_reason: reason.trim() || null,
      })
      if (created) {
        setName('')
        setDescription('')
        setReason('')
      }
    } finally {
      submitting.current = false
    }
  }

  return { name, setName, description, setDescription, reason, setReason, submit }
}

/**
 * 게시글 입력과 파일 검증을 담당한다. object URL은 effect에서 생성하고
 * 해당 effect가 만든 URL만 정리하므로 StrictMode와 파일 변경에도 수명이 맞는다.
 */
export function usePostForm(initial, busy, onSubmit) {
  const [title, setTitle] = useState(initial?.title || '')
  const [body, setBody] = useState(initial?.body || '')
  const [isAnonymous, setIsAnonymous] = useState(Boolean(initial?.is_anonymous))
  const [images, setImages] = useState([])
  const [previews, setPreviews] = useState([])
  const submitting = useRef(false)

  useEffect(() => {
    const next = images.map((file) => ({ file, url: URL.createObjectURL(file) }))
    setPreviews(next)
    return () => next.forEach(({ url }) => URL.revokeObjectURL(url))
  }, [images])

  /** 선택 파일의 형식·5MB·총 3장 제한을 확인하고 통과한 선택 묶음만 추가한다. */
  function chooseImages(event) {
    const files = Array.from(event.target.files || [])
    // 잘못된 파일도 같은 파일로 재선택할 수 있도록 매번 input 값을 초기화한다.
    event.target.value = ''
    if (busy) return
    const allowedTypes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
    if (files.some((file) => !allowedTypes.includes(file.type))) {
      window.alert('JPG, PNG, GIF, WEBP 이미지만 첨부할 수 있습니다.')
      return
    }
    if (files.some((file) => file.size > 5 * 1024 * 1024)) {
      window.alert('이미지 한 장은 5MB를 넘을 수 없습니다.')
      return
    }
    if (images.length + files.length > 3) {
      window.alert('이미지는 최대 3장까지 첨부할 수 있습니다.')
      return
    }
    setImages((current) => [...current, ...files])
  }

  /** 선택 순번의 파일을 제거한다. 이후 effect 정리가 이전 미리보기 URL을 해제한다. */
  function removeImage(index) {
    if (!busy) setImages((current) => current.filter((_, itemIndex) => itemIndex !== index))
  }

  /** 공백 입력과 연속 제출을 막고 제목·본문·파일을 전달한다. 실패한 입력은 초기화하지 않는다. */
  async function submit(event) {
    event.preventDefault()
    if (busy || submitting.current || !title.trim() || !body.trim()) return
    submitting.current = true
    try {
      await onSubmit({ title: title.trim(), body: body.trim(), images, is_anonymous: isAnonymous })
    } finally {
      submitting.current = false
    }
  }

  return { title, setTitle, body, setBody, isAnonymous, setIsAnonymous, previews, chooseImages, removeImage, submit }
}
