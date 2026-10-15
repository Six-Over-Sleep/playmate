import { useBoardSearch } from '../../hooks/board/useBoardSearch'

/** 목록의 검색 입력과 정렬 선택을 한 곳에서 표현한다. 정렬은 서버 재조회 없이 처리한다. */
export default function PostSearch({ value, sort, onSort, onSearch, busy }) {
  const { search, setSearch, submitSearch } = useBoardSearch(value, onSearch)

  return (
    <form className="search-row" onSubmit={submitSearch}>
      <div className="search-box">
        <span aria-hidden="true">⌕</span>
        <input
          aria-label="게시글 검색"
          value={search}
          disabled={busy}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="게시글 검색"
        />
        <button type="submit" aria-label="검색" disabled={busy}>검색</button>
      </div>
      <select
        className="sort-pill"
        aria-label="게시글 정렬"
        value={sort}
        disabled={busy}
        onChange={(event) => onSort(event.target.value)}
      >
        <option value="latest">최신순</option>
        <option value="oldest">오래된순</option>
      </select>
    </form>
  )
}
