import { useState } from 'react'
import PostSearch from '../../components/board/PostSearch'
import { useSortedPosts } from '../../hooks/board/useBoardSearch'
import BoardSidebar from '../../components/board/BoardSidebar'
import PostCard from '../../components/board/PostCard'

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

  // 일반 게시판은 기존 정렬 적용
  const sortedPosts = useSortedPosts(posts, sort)

  // 명예의 전당과 HOT은 서버에서 정렬한 순서 유지
  const visiblePosts = board?.featured
    ? (Array.isArray(posts) ? posts : [])
    : sortedPosts

  // 공지사항과 인기 게시판은 글쓰기 금지
  const canWrite =
    board &&
    board.name !== '공지사항' &&
    !board.featured

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
              <h2>
                {board?.name === '공지사항'
                  ? '📢 공지사항'
                  : board?.name || '게시판'}
              </h2>             
            </div>

            {/* 일반 게시판에서만 글쓰기 표시 */}
            {canWrite && (
              <button
                type="button"
                className="button mint write"
                disabled={busy}
                onClick={onWrite}
              >
                ＋ 글쓰기
              </button>
            )}
          </div>

          {/* 게시글 검색 */}
          {board && (
            <PostSearch
              key={board.id}
              value={query}
              sort={sort}
              onSort={setSort}
              onSearch={onSearch}
              busy={busy}
              hideSort={Boolean(board.featured)}
            />
          )}

          {/* 게시글 목록 */}
          {loading ? (
            <p className="empty-state">
              불러오는 중…
            </p>

          ) : posts === null ? (
            <p className="empty-state error-state">
              게시글을 불러오지 못했습니다.
              상단 오류를 확인해주세요.
            </p>

          ) : visiblePosts.length > 0 ? (
            visiblePosts.map((post) => (
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
                : board?.featured
                  ? '아직 선정 기준을 충족한 인기 게시글이 없습니다.'
                  : '아직 작성된 글이 없습니다.'}
            </p>
          )}

        </section>
      </div>
    </main>
  )
}