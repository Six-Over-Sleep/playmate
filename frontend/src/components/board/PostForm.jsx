import { useEffect, useMemo, useState } from 'react'

export default function PostForm({ initial, busy, onCancel, onSubmit }) {
  const [title, setTitle] = useState(initial?.title || '')
  const [body, setBody] = useState(initial?.body || '')
  const [images, setImages] = useState([])
  const previews = useMemo(() => images.map((file) => ({ file, url: URL.createObjectURL(file) })), [images])
  useEffect(() => () => previews.forEach((item) => URL.revokeObjectURL(item.url)), [previews])
  const chooseImages = (event) => {
    const next = [...event.target.files]
    if (next.some((file) => file.size > 5 * 1024 * 1024)) return alert('이미지 한 장은 5MB를 넘을 수 없습니다.')
    if (images.length + next.length > 3) return alert('이미지는 최대 3장까지 첨부할 수 있습니다.')
    setImages((current) => [...current, ...next]); event.target.value = ''
  }
  const submit = (event) => { event.preventDefault(); onSubmit({ title: title.trim(), body: body.trim(), images }) }
  return <form className="editor-card" onSubmit={submit}>
    <label>제목 *<input maxLength="100" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="이야기의 제목을 입력하세요" /></label>
    <label>내용 *<textarea maxLength="20000" rows="9" value={body} onChange={(e) => setBody(e.target.value)} placeholder="실명이나 개인 연락처를 포함하지 않고 작성해 주세요." /></label>
    {!initial && <label>사진 (선택)<span className="upload-box">▧<strong>사진 추가 · 최대 3장, 각 5MB</strong><input type="file" accept="image/jpeg,image/png,image/gif,image/webp" multiple onChange={chooseImages}/></span></label>}
    {!!previews.length && <div className="image-previews">{previews.map((item, index) => <figure key={`${item.file.name}-${index}`}><img src={item.url} alt="업로드 미리보기"/><button type="button" onClick={() => setImages((current) => current.filter((_, i) => i !== index))}>×</button></figure>)}</div>}
    <p className="privacy-note">다른 회원에게는 공개용 익명 ID만 보여요. 작성자 기수·반이나 로그인 계정 정보는 공개하지 않아요.</p>
    <div className="form-actions"><button type="button" className="button ghost" onClick={onCancel}>취소</button><button className="button purple" disabled={busy || !title.trim() || !body.trim()}>{busy ? '등록 중…' : '글 등록'}</button></div>
  </form>
}
