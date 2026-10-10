const formatDate = (value) => new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))

export default function PostCard({ post, onClick }) {
  return (
    <button className="post-card" onClick={onClick}>
      <h3>{post.title}</h3>
      <p>{post.body}</p>
      <div className="post-meta"><strong>{post.author_name}</strong><span>{formatDate(post.created_at)}</span><span>💬 {post.comment_count}</span></div>
    </button>
  )
}

