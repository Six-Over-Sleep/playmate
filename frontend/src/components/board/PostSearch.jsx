import { useState } from 'react'

export default function PostSearch({ value, onSearch }) {
  const [draft, setDraft] = useState(value)
  const submit = (event) => { event.preventDefault(); onSearch(draft.trim()) }
  return (
    <form className="search-row" onSubmit={submit}>
      <div className="search-box"><span aria-hidden="true">⌕</span><input aria-label="게시글 검색" placeholder="제목 · 내용 검색" value={draft} onChange={(e) => setDraft(e.target.value)} />{draft && <button type="button" aria-label="검색어 초기화" onClick={() => { setDraft(''); onSearch('') }}>×</button>}<button>검색</button></div>
      <div className="sort-pill">최신순⌄</div>
    </form>
  )
}

