import { useEffect, useMemo, useState } from 'react'
import BoardSidebar from '../../components/board/BoardSidebar'
import PostCard from '../../components/board/PostCard'

export default function BoardPage({
  boards,
  board,
  posts,
  query,
  loading,
  onSelectBoard,
  onCreateBoard,
  onSearch,
  onWrite,
  onPost,
}) {
  const [search, setSearch] = useState(query || '')
  const [sort, setSort] = useState('latest')

  useEffect(() => {
    setSearch(query || '')
  }, [query, board?.id])

  const sortedPosts = useMemo(() => {
    if (!Array.isArray(posts)) return []

    const indexed = posts.map((post, index) => {
      const parsed = Date.parse(post.created_at ?? post.createdAt ?? '')

      return {
        post,
        index,
        time: Number.isFinite(parsed) ? parsed : null,
      }
    })

    const hasDates = indexed.every(({ time }) => time !== null)

    indexed.sort((a, b) => {
      // 날짜가 없으면 API의 최신순 응답 순서를 사용합니다.
      const difference = hasDates
        ? b.time - a.time
        : a.index - b.index

      return (
        (sort === 'latest' ? difference : -difference) ||
        a.index - b.index
      )
    })

    return indexed.map(({ post }) => post)
  }, [posts, sort])

  const submitSearch = (event) => {
    event.preventDefault()
    onSearch(search.trim())
  }

  return (
    <main className="board-shell">
      <section className="page-intro">
        <div>
          <h1>게시판</h1>
          <p>학생끼리 편하게 이야기해요.</p>
        </div>
      </section>

      <div className="board-grid">
        <BoardSidebar
          boards={boards}
          selectedId={board?.id}
          onSelect={onSelectBoard}
          onCreate={onCreateBoard}
        />

        <section className="feed">
          <div className="feed-head">
            <div>
              <h2>{board?.name || '게시판'}</h2>
              <p>
                {board?.description ||
                  '함께 배우고, 편하게 이야기해요.'}
              </p>
            </div>

            <button
              type="button"
              className="button mint write"
              disabled={!board}
              onClick={onWrite}
            >
              ＋ 글쓰기
            </button>
          </div>

          {board && (
            <form className="search-row" onSubmit={submitSearch}>
              <div className="search-box">
                <span aria-hidden="true">⌕</span>

                <input
                  aria-label="게시글 검색"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="게시글 검색"
                />

                <button type="submit" aria-label="검색">
                  검색
                </button>
              </div>

              <select
                className="sort-pill"
                aria-label="게시글 정렬"
                value={sort}
                onChange={(event) => setSort(event.target.value)}
              >
                <option value="latest">최신순</option>
                <option value="oldest">오래된순</option>
              </select>
            </form>
          )}

          {loading ? (
            <p className="empty-state">불러오는 중…</p>
          ) : posts === null ? (
            <p className="empty-state error-state">
              게시글을 불러오지 못했습니다. 상단 오류를 확인해주세요.
            </p>
          ) : sortedPosts.length ? (
            sortedPosts.map((post) => (
              <PostCard
                key={post.id}
                post={post}
                onClick={() => onPost(post)}
              />
            ))
          ) : (
            <p className="empty-state">
              {query
                ? '검색 결과가 없습니다.'
                : '아직 작성된 글이 없습니다.'}
            </p>
          )}
        </section>
      </div>
    </main>
  )
}