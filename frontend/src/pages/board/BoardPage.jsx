import { NOTICE_BOARD_NAME, FREE_BOARD_NAME } from '../../utils/boardPolicy'
// 기존 게시판 API와 검색·게시글 기능을 유지하며 메인 큐레이션 순서를 정리합니다.
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PostSearch from '../../components/board/PostSearch'
import BoardSidebar from '../../components/board/BoardSidebar'
import PostCard from '../../components/board/PostCard'


function PreviewList({ posts, emptyMessage, onOpen, variant = 'ranked' }) {
  if (!posts.length) return <p className="pm-board-highlight-empty">{emptyMessage}</p>

  return <ol className={`pm-board-preview-list pm-board-preview-list--${variant}`}>
    {posts.map((post, index) => (
      <li key={`${post.board_id ?? 'board'}-${post.id}`}>
        <button type="button" onClick={() => onOpen(post)} title={post.title}>
          <span className="pm-board-preview-rank" aria-hidden="true">{index + 1}</span>
          <strong>{post.title}</strong>
          <small>♡ {post.like_count ?? 0}</small>
        </button>
      </li>
    ))}
  </ol>
}

export default function BoardPage({
  boards, memberCourse, memberCohort, board, posts, query, loading, busy,
  onSelectBoard, onCreateBoard, onSearch, onWrite, onPost,
  page, sort, hasNext, onPage, onSort, loadPreview, previewVersion,
}) {
  const navigate = useNavigate()
  const [hotPosts, setHotPosts] = useState([])
  const [hallPosts, setHallPosts] = useState([])
  const [noticePosts, setNoticePosts] = useState([])

  const visiblePosts = Array.isArray(posts) ? posts : []
  const canWrite = board && board.name !== NOTICE_BOARD_NAME && !board.featured && board.can_write !== false
  const hotBoard = boards.find((candidate) => String(candidate.id) === 'hot')
  const hallBoard = boards.find((candidate) => String(candidate.id) === 'hall-of-fame')
  const noticeBoard = boards.find((candidate) => String(candidate.name || '').replace(/^📢\s*/u, '') === NOTICE_BOARD_NAME)
  const noticeBoardId = noticeBoard?.id
  const selectedBoardName = String(board?.name || '').replace(/^[📢🏆🔥]\s*/u, '').trim()
  const showHighlights = selectedBoardName === FREE_BOARD_NAME
  // 공지사항을 선택한 경우 동일한 글을 미리보기와 목록에 중복 표시하지 않습니다.
  const showNoticePreview = Boolean(noticeBoard) && selectedBoardName !== NOTICE_BOARD_NAME

  useEffect(() => {
    let active = true
    setHotPosts([])
    setHallPosts([])
    if (showHighlights) {
      loadPreview('hot').then((items) => { if (active) setHotPosts(items) }).catch(() => {})
      loadPreview('hall-of-fame').then((items) => { if (active) setHallPosts(items) }).catch(() => {})
    }
    return () => { active = false }
  }, [showHighlights, loadPreview, previewVersion])

  useEffect(() => {
    let active = true
    setNoticePosts([])
    if (noticeBoardId != null && showNoticePreview) {
      loadPreview('notice', noticeBoardId).then((items) => { if (active) setNoticePosts(items) }).catch(() => {})
    }
    return () => { active = false }
  }, [noticeBoardId, showNoticePreview, loadPreview, previewVersion])

  const openPreviewPost = (post, fallbackBoard) => {
    const targetBoardId = post?.board_id ?? fallbackBoard?.id
    if (targetBoardId != null && post?.id != null) {
      navigate(`/board/${targetBoardId}/posts/${post.id}`)
    } else if (fallbackBoard) {
      onSelectBoard(fallbackBoard)
    }
  }

  return <main className="board-shell pm-board-dashboard">
    <div className="pm-board-title">
      <div><h1>게시판</h1></div>
      <p>배우고, 공유하고, 함께 성장하는 PlayMate 이야기</p>
    </div>
    <div className="board-grid">
      <BoardSidebar
        boards={boards} memberCourse={memberCourse} memberCohort={memberCohort}
        busy={busy} selectedId={board?.id} onSelect={onSelectBoard} onCreate={onCreateBoard}
      />
      <div className="pm-board-content">
        {showNoticePreview && <section className="pm-board-highlight-card pm-board-notice" aria-label="공지사항 미리보기">
          <div className="pm-board-highlight-heading">
            <h3>📢 공지사항</h3>
            <button type="button" onClick={() => noticeBoard && onSelectBoard(noticeBoard)} disabled={!noticeBoard}>더보기 ›</button>
          </div>
          {noticePosts.length ? (
            <ul className="pm-board-notice-list">
              {noticePosts.map((post) => (
                <li key={`${post.board_id ?? noticeBoardId}-${post.id}`}>
                  <button type="button" onClick={() => openPreviewPost(post, noticeBoard)} title={post.title}>
                    <span className="pm-board-notice-dot" aria-hidden="true" />
                    <strong>{post.title}</strong>
                    <span className="pm-board-notice-date">{post.created_at ? new Date(post.created_at).toLocaleDateString('ko-KR', { month: '2-digit', day: '2-digit' }) : ''}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : <p className="pm-board-highlight-empty">등록된 공지사항이 없습니다.</p>}
        </section>}

        {showHighlights && <div className="pm-board-highlights">
          <section className="pm-board-highlight-card" aria-label="HOT 게시글 미리보기">
            <div className="pm-board-highlight-heading">
              <h3>🔥 HOT 게시글</h3>
              <button type="button" onClick={() => hotBoard && onSelectBoard(hotBoard)} disabled={!hotBoard}>더보기 ›</button>
            </div>
            <PreviewList posts={hotPosts} emptyMessage="선정된 HOT 게시글이 없습니다." onOpen={(post) => openPreviewPost(post, hotBoard)} />
          </section>

          <section className="pm-board-highlight-card pm-board-hall" aria-label="명예의 전당 미리보기">
            <div className="pm-board-highlight-heading">
              <h3>🏆 명예의 전당</h3>
              <button type="button" onClick={() => hallBoard && onSelectBoard(hallBoard)} disabled={!hallBoard}>더보기 ›</button>
            </div>
            <PreviewList posts={hallPosts} emptyMessage="아직 명예의 전당에 선정된 글이 없습니다." onOpen={(post) => openPreviewPost(post, hallBoard)} variant="hall" />
          </section>
        </div>}

        <section className="feed pm-board-feed">
          <div className="feed-head">
            <div>
              <span className="pm-section-kicker">COMMUNITY BOARD</span>
              <h2>{board?.name || '전체 게시글'}</h2>
              {typeof board?.description === 'string' && board.description.trim() && <p className="board-intro-description">{board.description}</p>}
              {board?.course_code && board.can_write === false && <p className="board-course-readonly">다른 과정·기수 게시판입니다. 열람만 가능합니다.</p>}
            </div>
            {canWrite && <button type="button" className="button mint write" disabled={busy} onClick={onWrite}>＋ 글쓰기</button>}
          </div>
          {board && <PostSearch key={board.id} value={query} sort={sort} onSort={onSort} onSearch={onSearch} busy={busy || loading} hideSort={Boolean(board.featured)} />}
          {loading ? <p className="empty-state">불러오는 중…</p>
            : posts === null ? <p className="empty-state error-state">게시글을 불러오지 못했습니다. 상단 오류를 확인해주세요.</p>
              : visiblePosts.length > 0 ? visiblePosts.map((post) => <PostCard key={post.id} post={post} disabled={busy} onClick={() => onPost(post)} />)
                : <p className="empty-state">{query ? '검색 결과가 없습니다.' : board?.featured ? '아직 선정 기준을 충족한 인기 게시글이 없습니다.' : '아직 작성된 글이 없습니다.'}</p>}
          {!board?.featured && posts !== null && <nav aria-label="게시글 페이지" className="board-pagination">
            <button type="button" disabled={busy || loading || page === 0} onClick={() => onPage(page - 1)}>이전</button>
            <span aria-live="polite"> {page + 1} 페이지 </span>
            <button type="button" disabled={busy || loading || !hasNext} onClick={() => onPage(page + 1)}>다음</button>
          </nav>}
        </section>
      </div>
    </div>
  </main>
}
