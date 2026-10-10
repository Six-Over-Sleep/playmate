import { useCallback, useEffect, useState } from 'react'
import Header from './components/layout/Header'
import BoardCreateModal from './components/board/BoardCreateModal'
import BoardPage from './pages/board/BoardPage'
import PostDetailPage from './pages/board/PostDetailPage'
import PostEditorPage from './pages/board/PostEditorPage'
import { boardApi } from './services/boardApi'

export default function App() {
  const [boards, setBoards] = useState([]), [board, setBoard] = useState(null), [posts, setPosts] = useState([])
  const [post, setPost] = useState(null), [comments, setComments] = useState([]), [view, setView] = useState('list')
  const [query, setQuery] = useState(''), [loading, setLoading] = useState(true), [busy, setBusy] = useState(false)
  const [modal, setModal] = useState(false), [error, setError] = useState('')
  const [success, setSuccess] = useState(''), [initialized, setInitialized] = useState(false)

  const run = useCallback(async (task) => { try { setError(''); return await task() } catch (e) { setError(e.message); throw e } }, [])
  const loadPosts = useCallback(async (target, q = '') => { setLoading(true); try { setPosts(await run(() => boardApi.posts(target.id, q))) } catch { setPosts(null) } finally { setLoading(false) } }, [run])

  useEffect(() => { run(boardApi.boards).then((items) => { setBoards(items); if (items[0]) { setBoard(items[0]); loadPosts(items[0]) } }).catch(() => setLoading(false)).finally(() => setInitialized(true)) }, [loadPosts, run])

  const selectBoard = (target) => { setBoard(target); setQuery(''); setView('list'); loadPosts(target) }
  const openPost = async (item) => { try { const [detail, replies] = await Promise.all([run(() => boardApi.post(board.id, item.id)), run(() => boardApi.comments(board.id, item.id))]); setPost(detail); setComments(replies); setView('detail') } catch {} }
  const refreshDetail = async () => { setPost(await run(() => boardApi.post(board.id, post.id))); setComments(await run(() => boardApi.comments(board.id, post.id))) }
  const notify = (message) => { setSuccess(message); setTimeout(() => setSuccess(''), 2500) }
  const mutate = async (task, after) => { setBusy(true); try { const result = await run(task); await after(result); return result } catch { return null } finally { setBusy(false) } }
  const createBoard = (payload) => mutate(() => boardApi.createBoard(payload), async (created) => { const items = await boardApi.boards(); setBoards(items); setModal(false); selectBoard(created); notify('게시판을 만들었습니다.') })
  const savePost = (payload) => mutate(() => post ? boardApi.updatePost(board.id, post.id, payload) : boardApi.createPost(board.id, payload), async (saved) => { setPost(saved); setComments(post ? comments : []); setView('detail'); notify(post ? '게시글을 수정했습니다.' : '게시글을 등록했습니다.') })
  const deletePost = () => { if (confirm('이 글을 삭제할까요?')) mutate(() => boardApi.deletePost(board.id, post.id), async () => { setView('list'); setPost(null); await loadPosts(board, query) }) }
  const addComment = (body) => mutate(() => boardApi.createComment(board.id, post.id, body), refreshDetail)
  const editComment = (id, body) => mutate(() => boardApi.updateComment(id, body), refreshDetail)
  const deleteComment = (id) => { if (confirm('이 댓글을 삭제할까요?')) return mutate(() => boardApi.deleteComment(id), refreshDetail) }

  const unavailable = initialized && !board && error
  return <><Header/>{error && <div className="error-banner" role="alert">{error}</div>}{success && <div className="success-toast" role="status">{success}</div>}{unavailable ? <main className="service-error"><h1>게시판을 불러오지 못했어요</h1><p>{error}</p><button className="button purple" onClick={() => location.reload()}>다시 시도</button></main> : <>{view === 'list' && <BoardPage boards={boards} board={board} posts={posts} query={query} loading={loading} onSelectBoard={selectBoard} onCreateBoard={() => setModal(true)} onSearch={(q) => { setQuery(q); loadPosts(board, q) }} onWrite={() => { setPost(null); setView('editor') }} onPost={openPost}/>} {view === 'editor' && board && <PostEditorPage board={board} post={post} busy={busy} onBack={() => setView(post ? 'detail' : 'list')} onSubmit={savePost}/>} {view === 'detail' && post && <PostDetailPage boards={boards} board={board} post={post} comments={comments} busy={busy} onSelectBoard={selectBoard} onCreateBoard={() => setModal(true)} onBack={() => { setView('list'); loadPosts(board, query) }} onEdit={() => setView('editor')} onDelete={deletePost} onComment={addComment} onEditComment={editComment} onDeleteComment={deleteComment}/>}</>}<BoardCreateModal open={modal} busy={busy} onClose={() => setModal(false)} onCreate={createBoard}/></>
}
