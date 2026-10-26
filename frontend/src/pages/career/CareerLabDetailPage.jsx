import '../../styles/CareerLabDetailPage.css'

const TYPE_LABELS = {
    QUESTION: '질문',
    DISCUSSION: '토론',
}

/** PostgreSQL에 저장된 커리어 연구소 게시글 상세 화면 */
export default function CareerLabDetailPage({
    post,
    onBack,
    onEdit,
    onDelete,
    onVote,
    onToggleResolved,
    busy = false,
    children,
}) {
    if (!post) return null

    const options = post.poll_options || []
    const voted = post.my_vote_option_id !== null && post.my_vote_option_id !== undefined

    return (
        <div className="career-lab-detail">
            <button type="button" className="career-lab-back" disabled={busy} onClick={onBack}>
                ← 커리어 연구소 목록으로
            </button>
            <article className="career-lab-detail-card">
                <div className="career-lab-detail-top">
                    <span className="career-post-tag">{post.menu}</span>
                </div>

                <h3>{post.title}</h3>
                <div className="career-lab-detail-meta">
                    <span>{post.author}</span>
                    <span>{post.date}</span>
                    <span>{TYPE_LABELS[post.post_type] || post.post_type}</span>
                </div>

                <div className="career-lab-detail-body">{post.body}</div>

                {post.post_type === 'QUESTION' && (
                    <div className="career-lab-resolution">
                        <span>
                            질문 상태: <strong>{post.is_resolved ? '해결 완료' : '해결 대기'}</strong>
                        </span>
                        {post.is_owner && (
                            <button type="button" disabled={busy} onClick={onToggleResolved}>
                                {post.is_resolved ? '미해결로 변경' : '해결 완료 표시'}
                            </button>
                        )}
                    </div>
                )}

                {post.post_type === 'DISCUSSION' && options.length >= 2 && (
                    <section className="career-lab-detail-poll">
                        <h4>투표</h4>
                        <p>총 {post.total_votes ?? 0}표 · 회원당 1회 투표 가능</p>
                        {options.map((option) => (
                            <button
                                key={option.option_id}
                                type="button"
                                className={post.my_vote_option_id === option.option_id ? 'selected' : ''}
                                disabled={busy || voted}
                                onClick={() => onVote(option.option_id)}
                            >
                                <span>{option.option_text}</span>
                                <span>{option.vote_count ?? 0}표</span>
                            </button>
                        ))}
                        {voted && <p>투표가 완료되었습니다. 다른 선택지로 변경할 수 없습니다.</p>}
                    </section>
                )}

                <div className="career-lab-detail-actions">
                    <button type="button" className="career-lab-cancel" disabled={busy} onClick={onBack}>
                        목록
                    </button>
                    {post.is_owner && (
                        <>
                            <button type="button" className="career-lab-edit" disabled={busy} onClick={onEdit}>
                                수정
                            </button>
                            <button type="button" className="career-lab-delete" disabled={busy} onClick={onDelete}>
                                삭제
                            </button>
                        </>
                    )}
                </div>

                {/* 좋아요·스크랩·댓글 (취업 4종 공통 영역) */}
                {children}
            </article>
        </div>
    )
}
