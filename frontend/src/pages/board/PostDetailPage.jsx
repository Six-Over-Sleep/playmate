// PLAYMATE_BOARD_REPORTS_V1
// PLAYMATE_COURSE_BOARD_PERMISSIONS_V1
import { useState } from 'react'
import BoardSidebar from '../../components/board/BoardSidebar'
import CommentForm from '../../components/board/CommentForm'
import CommentList from '../../components/board/CommentList'
import { mediaUrl } from '../../services/boardApi'
import { formatBoardDate } from '../../utils/board'

/** 상세 화면을 구성한다. 소유자 표시는 서버 응답을 따르고 실제 인가는 백엔드가 수행한다. */
export default function PostDetailPage({
  boards, board, post, comments, busy, memberCourse, memberCohort, onSelectBoard, onCreateBoard,
  onBack, onEdit, onDelete, onLike, onScrap, onReport, onComment, onEditComment, onDeleteComment,
}) {
  const canWrite = board.can_write !== false
  const [reportOpen, setReportOpen] = useState(false)
  const [reportReason, setReportReason] = useState('SPAM')
  const [reportDetails, setReportDetails] = useState('')
  const canReport = !post.is_owner && board.name !== '공지사항'

  async function submitReport(event) {
    event.preventDefault()
    const result = await onReport(reportReason, reportDetails)
    if (result) setReportOpen(false)
  }

  return (
    <main className="detail-layout">
      <aside className="detail-side">
        <BoardSidebar
          boards={boards}
          memberCourse={memberCourse}
          memberCohort={memberCohort}
          busy={busy}
          selectedId={board?.id}
          onSelect={onSelectBoard}
          onCreate={onCreateBoard}
        />
      </aside>
      <article className="detail-content">
        <button className="back-link" disabled={busy} onClick={onBack}>
          ‹ {board.name} 목록으로
        </button>
        <header className="detail-head">
          <div className="detail-title-row">
            <h1>{post.title}</h1>
            {post.is_owner && canWrite && (
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
        {canReport && (
          <section className="board-report-area" aria-label="게시글 신고">
            <button type="button" disabled={busy} onClick={() => setReportOpen((open) => !open)}>
              {reportOpen ? '신고 취소' : '게시글 신고'}
            </button>
            {reportOpen && (
              <form className="board-report-form" onSubmit={submitReport}>
                <label htmlFor="report-reason">신고 사유</label>
                <select id="report-reason" value={reportReason} disabled={busy}
                  onChange={(event) => setReportReason(event.target.value)}>
                  <option value="SPAM">광고·도배</option>
                  <option value="ABUSE">욕설·괴롭힘</option>
                  <option value="HATE">혐오 표현</option>
                  <option value="PRIVACY">개인정보 노출</option>
                  <option value="OTHER">기타</option>
                </select>
                <textarea aria-label="신고 상세 내용" maxLength={500}
                  placeholder="상세 내용 (선택)" value={reportDetails} disabled={busy}
                  onChange={(event) => setReportDetails(event.target.value)} />
                <button type="submit" disabled={busy}>신고 접수</button>
              </form>
            )}
          </section>
        )}
        <section className="comments">
          <h2>댓글 {post.comment_count}</h2>
          {!canWrite && (
            <p className="board-course-readonly">다른 과정·기수 게시판은 댓글·답글을 작성할 수 없습니다.</p>
          )}
          <CommentList
            canReply={canWrite}
            comments={comments}
            busy={busy}
            onEdit={onEditComment}
            onDelete={onDeleteComment}
            onReply={onComment}
          />
          {canWrite && <CommentForm busy={busy} onSubmit={onComment} />}
        </section>
      </article>
    </main>
  )
}
