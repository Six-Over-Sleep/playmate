import { formatBoardDate } from '../../utils/board'

/** 목록 항목을 표시한다. 정렬과 서버 데이터 변경은 상위 hook에서 처리한다. */
export default function PostCard({ post, disabled, onClick }) {
  return (
    <button className="post-card" disabled={disabled} onClick={onClick}>
      <h3>{post.title}</h3>
      <p>{post.body}</p>
      <div className="post-meta">
        <strong>{post.author_name}</strong>
        <span>{formatBoardDate(post.created_at)}</span>
        <span>💬 {post.comment_count}</span>
        <span>♡ {post.like_count}</span>
      </div>
    </button>
  )
}
