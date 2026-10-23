import '../../styles/CareerLoungeDetailPage.css'

/** 현직자 라운지 상세: 예시 글은 읽기 전용, 본인 브라우저에서 작성한 임시 글만 수정/삭제. */
export default function CareerLoungeDetailPage({ post, onBack, onEdit, onDelete }) {
    if (!post) return null

    const isDraft = post.isDraft === true

    return (
        <div className="career-lounge-detail">
            <button type="button" className="career-lounge-back" onClick={onBack}>
                ← 현직자 라운지 목록으로
            </button>

            <article className="career-lounge-detail-card">
                <div className="career-lounge-detail-top">
                    <span className="career-post-tag">{post.menu}</span>
                    <small>{isDraft ? '브라우저 임시 글' : '화면용 예시 글'}</small>
                </div>

                <h3>{post.title}</h3>
                <div className="career-lounge-detail-meta">
                    <span>{post.author}</span>
                    <span>{post.date}</span>
                </div>

                {isDraft && (
                    <div className="career-lounge-detail-tags">
                        <span>{post.post_type === 'QUESTION' ? '직무 질문' : '실무 경험'}</span>
                        <span>{post.job_category}</span>
                        {post.career_years !== null && <span>경력 {post.career_years}년</span>}
                        {post.company_size && <span>{post.company_size}</span>}
                        {post.tech_stack && <span>{post.tech_stack}</span>}
                    </div>
                )}

                <div className="career-lounge-detail-body">{post.body || post.summary}</div>

                {isDraft && [
                    ['실제 업무', post.work_details],
                    ['어려웠던 점', post.challenges],
                    ['조언', post.advice],
                ].filter(([, value]) => Boolean(value)).map(([heading, value]) => (
                    <section className="career-lounge-detail-extra" key={heading}>
                        <h4>{heading}</h4>
                        <p>{value}</p>
                    </section>
                ))}

                <p className="career-lounge-detail-hint">
                    {isDraft
                        ? '서버에 저장되지 않은 화면용 임시 글입니다. 새로고침하면 사라집니다. 공개 범위 설정도 실제로 적용되지 않습니다.'
                        : '화면용 예시 글이며, 작성자의 졸업·재직 인증이 확인된 게시글이 아닙니다.'}
                </p>

                <div className="career-lounge-detail-actions">
                    <button type="button" className="career-lounge-cancel" onClick={onBack}>목록</button>
                    {isDraft && (
                        <>
                            <button type="button" className="career-lounge-edit" onClick={onEdit}>수정</button>
                            <button type="button" className="career-lounge-delete" onClick={onDelete}>삭제</button>
                        </>
                    )}
                </div>
            </article>
        </div>
    )
}
