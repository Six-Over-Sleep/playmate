import BoardSidebar from '../../components/board/BoardSidebar'
import PostCard from '../../components/board/PostCard'
import PostSearch from '../../components/board/PostSearch'

export default function BoardPage({ boards, board, posts, query, loading, onSelectBoard, onCreateBoard, onSearch, onWrite, onPost }) {
  return <main className="board-shell"><section className="page-intro"><div><h1>게시판</h1><p>학생끼리 편하게 이야기해요.</p></div></section><div className="board-grid"><BoardSidebar boards={boards} selectedId={board?.id} onSelect={onSelectBoard} onCreate={onCreateBoard}/><section className="feed"><div className="feed-head"><div><h2>{board?.name || '게시판'}</h2><p>{board?.description || '함께 배우고, 편하게 이야기해요.'}</p></div><button className="button mint write" disabled={!board} onClick={onWrite}>＋ 글쓰기</button></div>{board && <PostSearch value={query} onSearch={onSearch}/>} {loading ? <p className="empty-state">불러오는 중…</p> : posts === null ? <p className="empty-state error-state">게시글을 불러오지 못했습니다. 상단 오류를 확인해주세요.</p> : posts.length ? posts.map((post) => <PostCard key={post.id} post={post} onClick={() => onPost(post)}/>) : <p className="empty-state">{query ? '검색 결과가 없습니다.' : '아직 작성된 글이 없습니다.'}</p>}</section></div></main>
}
