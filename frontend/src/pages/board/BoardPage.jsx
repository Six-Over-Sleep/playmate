import { useState } from 'react'
import PostSearch from '../../components/board/PostSearch'
import { useSortedPosts } from '../../hooks/board/useBoardSearch'
import BoardSidebar from '../../components/board/BoardSidebar'
import PostCard from '../../components/board/PostCard'

/** 목록 레이아웃과 화면 상태만 표현하고 검색·정렬은 전용 모듈에 맡긴다. */
export default function BoardPage({
  boards,
  board,
  posts,
  query,
  loading,
  busy,
  onSelectBoard,
  onCreateBoard,
  onSearch,
  onWrite,
  onPost,
}) {
  const [sort, setSort] = useState('latest')
  const sortedPosts = useSortedPosts(posts, sort)

  return (
    <main className="board-shell">
      <section className="page-intro">
        <div>
          <h1>게시판</h1>
        </div>
      </section>

      <div className="board-grid">
        <BoardSidebar
          boards={boards}
          busy={busy}
          selectedId={board?.id}
          onSelect={onSelectBoard}
          onCreate={onCreateBoard}
        />

        <section className="feed">
          <div className="feed-head">
            <div>
              <h2>{board?.name || '게시판'}</h2>
            </div>

            <button
              type="button"
              className="button mint write"
              disabled={!board || busy}
              onClick={onWrite}
            >
              ＋ 글쓰기
            </button>
          </div>

          {board && (
            <PostSearch
              key={board.id}
              value={query}
              sort={sort}
              onSort={setSort}
              onSearch={onSearch}
              busy={busy}
            />
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
                disabled={busy}
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
