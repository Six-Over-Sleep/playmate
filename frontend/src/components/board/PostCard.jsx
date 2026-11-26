import { formatBoardDate } from '../../utils/board'

/** 취업 게시글 목록과 동일한 선형 아이콘을 사용합니다. */
function PostMetricIcon({ type }) {
  const shapes = {
    comment: <><path d="M20.5 11.5a8.5 8.5 0 0 1-8.5 8.5 9 9 0 0 1-3.6-.8L3 21l1.8-5.4a9 9 0 0 1-.8-3.6 8.5 8.5 0 1 1 16.5-.5Z" /><path d="M8 11.5h8M8 15h5" /></>,
    like: <path d="M20.4 5.6a4.6 4.6 0 0 0-6.5 0L12 7.5l-1.9-1.9a4.6 4.6 0 0 0-6.5 6.5L12 20.5l8.4-8.4a4.6 4.6 0 0 0 0-6.5Z" />,
    scrap: <path d="M6 3.5h12a1 1 0 0 1 1 1V21l-7-4.5L5 21V4.5a1 1 0 0 1 1-1Z" />,
  }

  return (
    <svg className="pm-board-post-metric-icon" width="13" height="13" viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true">
      {shapes[type]}
    </svg>
  )
}

/** 댓글 → 좋아요 → 스크랩 순서로 실제 서버 집계 값을 표시합니다. */
export default function PostCard({ post, disabled, onClick }) {
  const commentCount = post.comment_count ?? 0
  const likeCount = post.like_count ?? 0
  // 이전 버전 API에는 스크랩 수가 없으므로 없는 수치를 0으로 꾸며내지 않습니다.
  const scrapCount = post.scrap_count ?? '—'

  return (
    <button className="post-card" disabled={disabled} onClick={onClick}>
      <h3>{post.title}</h3>
      <p>{post.body}</p>
      <div className="post-meta">
        <strong>{post.author_name}</strong>
        <span className="pm-board-post-date">{formatBoardDate(post.created_at)}</span>
        <span className="pm-board-post-metric" title="댓글" aria-label={`댓글 ${commentCount}개`}>
          <PostMetricIcon type="comment" /><span>{commentCount}</span>
        </span>
        <span className="pm-board-post-metric" title="좋아요" aria-label={`좋아요 ${likeCount}개`}>
          <PostMetricIcon type="like" /><span>{likeCount}</span>
        </span>
        <span className="pm-board-post-metric" title={post.scrap_count == null ? '스크랩 수 정보 없음' : '스크랩'}
          aria-label={post.scrap_count == null ? '스크랩 수 정보 없음' : `스크랩 ${post.scrap_count}개`}>
          <PostMetricIcon type="scrap" /><span>{scrapCount}</span>
        </span>
      </div>
    </button>
  )
}
