import '../../styles/CareerLoungeDetailPage.css'

/** 서버에 저장된 현직자 라운지 게시글 상세 화면 */
export default function CareerLoungeDetailPage({
    post,
    onBack,
    onEdit,
    onDelete,
    busy = false,
}) {
    if (!post) return null

    return (
        <div className="career-lounge-detail">
            <button
                type="button"
                className="career-lounge-back"
                disabled={busy}
                onClick={onBack}
            >
                ← 현직자 라운지 목록으로
            </button>

            <article className="career-lounge-detail-card">
                <div className="career-lounge-detail-top">
                    <span className="career-post-tag">{post.menu}</span>
                </div>

                <h3>{post.title}</h3>

                <div className="career-lounge-detail-meta">
                    <span>{post.author}</span>
                    <span>{post.date}</span>
                </div>

                <div className="career-lounge-detail-tags">
                    <span>{post.post_type === 'QUESTION' ? '직무 질문' : '실무 경험'}</span>
                    {post.job_category && <span>{post.job_category}</span>}
                    {post.career_years !== null && post.career_years !== undefined && (
                        <span>경력 {post.career_years}년</span>
                    )}
                    {post.company_name && <span>{post.company_name}</span>}
                </div>

                <div className="career-lounge-detail-body">
                    {post.body || post.summary}
                </div>

                <div className="career-lounge-detail-actions">
                    <button
                        type="button"
                        className="career-lounge-cancel"
                        disabled={busy}
                        onClick={onBack}
                    >
                        목록
                    </button>

                    {post.is_owner && (
                        <>
                            <button
                                type="button"
                                className="career-lounge-edit"
                                disabled={busy}
                                onClick={onEdit}
                            >
                                수정
                            </button>
                            <button
                                type="button"
                                className="career-lounge-delete"
                                disabled={busy}
                                onClick={onDelete}
                            >
                                삭제
                            </button>
                        </>
                    )}
                </div>
            </article>
        </div>
    )
}
