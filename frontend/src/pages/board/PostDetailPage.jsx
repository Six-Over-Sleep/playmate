import CommentForm from '../../components/board/CommentForm'
import CommentList from '../../components/board/CommentList'
import { mediaUrl } from '../../services/boardApi'

const formatDate = (value) => new Intl.DateTimeFormat('ko-KR', { dateStyle: 'long', timeStyle: 'short' }).format(new Date(value))

export default function PostDetailPage({ boards, board, post, comments, busy, onSelectBoard, onCreateBoard, onBack, onEdit, onDelete, onComment, onEditComment, onDeleteComment }) {
  return <main className="detail-layout"><aside className="detail-side">{boards.map((item) => <button key={item.id} className={item.id === board.id ? 'active' : ''} onClick={() => onSelectBoard(item)}>{item.name}</button>)}<button className="create-board" onClick={onCreateBoard}>＋ 게시판 만들기</button></aside><article className="detail-content"><button className="back-link" onClick={onBack}>‹ {board.name} 목록으로</button><header className="detail-head"><div className="detail-title-row"><h1>{post.title}</h1>{post.is_owner && <div className="owner-actions"><button onClick={onEdit}>수정</button><button onClick={onDelete}>삭제</button></div>}</div><p><strong>{post.author_name}</strong><span>{formatDate(post.created_at)}</span></p></header><div className="post-body">{post.body}</div>{!!post.images?.length && <div className="post-images">{post.images.map((image) => <img key={image.id} src={mediaUrl(image.url)} alt={image.original_name}/>)}</div>}<section className="comments"><h2>댓글 {comments.length}</h2><CommentList comments={comments} onEdit={onEditComment} onDelete={onDeleteComment}/><CommentForm busy={busy} onSubmit={onComment}/></section></article></main>
}
