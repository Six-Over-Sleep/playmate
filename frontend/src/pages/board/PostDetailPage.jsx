import CommentForm from '../../components/board/CommentForm'
import CommentList from '../../components/board/CommentList'
import { mediaUrl } from '../../services/boardApi'
import { formatBoardDate } from '../../utils/board'

/** 상세 화면을 구성한다. 소유자 표시는 서버 응답을 따르고 실제 인가는 백엔드가 수행한다. */
export default function PostDetailPage({
  boards, board, post, comments, busy, onSelectBoard, onCreateBoard,
  onBack, onEdit, onDelete, onLike, onScrap, onComment, onEditComment, onDeleteComment,
}) {
  return (
    <main className="detail-layout">
      <aside className="detail-side">
        {boards.map((item) => (
          <button
            key={item.id}
            className={item.id === board.id ? 'active' : ''}
            disabled={busy}
            onClick={() => onSelectBoard(item)}
          >
            {item.name}
          </button>
        ))}
        <button className="create-board" disabled={busy} onClick={onCreateBoard}>
          ＋ 게시판 만들기
        </button>
      </aside>
      <article className="detail-content">
        <button className="back-link" disabled={busy} onClick={onBack}>
          ‹ {board.name} 목록으로
        </button>
        <header className="detail-head">
          <div className="detail-title-row">
            <h1>{post.title}</h1>
            {post.is_owner && (
              <div className="owner-actions">
                <button disabled={busy} onClick={onEdit}>수정</button>
                <button disabled={busy} onClick={onDelete}>삭제</button>
              </div>
            )}
          </div>
          <p>
            <strong>{post.author_name}</strong>
            <span>{formatBoardDate(post.created_at, 'long')}</span>
          </p>
        </header>
        <div className="post-body">{post.body}</div>
        {!!post.images?.length && (
          <div className="post-images">
            {post.images.map((image) => (
              <img key={image.id} src={mediaUrl(image.url)} alt={image.original_name} />
            ))}
          </div>
        )}
        {/* 표시 값은 서버 응답(like_count·liked_by_me·scrapped_by_me)을 그대로 사용한다. */}
        <div className="post-reactions">
          <button
            className={`button ${post.liked_by_me ? 'purple' : 'ghost'}`}
            aria-pressed={post.liked_by_me}
            disabled={busy}
            onClick={onLike}
          >
            {post.liked_by_me ? '♥' : '♡'} 좋아요 {post.like_count}
          </button>
          <button
            className={`button ${post.scrapped_by_me ? 'purple' : 'ghost'}`}
            aria-pressed={Boolean(post.scrapped_by_me)}
            disabled={busy}
            onClick={onScrap}
          >
            {post.scrapped_by_me ? '스크랩됨' : '스크랩'}
          </button>
        </div>
        <section className="comments">
          <h2>댓글 {post.comment_count}</h2>
          <CommentList
            comments={comments}
            busy={busy}
            onEdit={onEditComment}
            onDelete={onDeleteComment}
            onReply={onComment}
          />
          <CommentForm busy={busy} onSubmit={onComment} />
        </section>
      </article>
    </main>
  )
}
