import '../../styles/CareerTalkDetailPage.css'

/** 커리어 톡톡 상세 화면: 예시 글은 읽기 전용, 작성한 임시 글만 수정/삭제 가능. */
export default function CareerTalkDetailPage({ talk, onBack, onEdit, onDelete }) {
    if (!talk) return null

    const isDraft = talk.isDraft === true

    return (
        <div className="career-talk-detail">
            <button type="button" className="career-talk-back" onClick={onBack}>
                ← 커리어 톡톡 목록으로
            </button>

            <article className="career-talk-detail-card">
                <div className="career-talk-detail-top">
                    <span className="career-post-tag">{talk.menu}</span>
                    <small>{isDraft ? '브라우저 임시 게시글' : '화면용 예시 게시글'}</small>
                </div>
                <h3>{talk.title}</h3>
                <div className="career-talk-detail-meta">
                    <span>{talk.author}</span>
                    <span>{talk.date}</span>
                </div>

                {isDraft && (talk.job_category || talk.current_status) && (
                    <div className="career-talk-detail-tags">
                        {talk.job_category && <span>{talk.job_category}</span>}
                        {talk.current_status && <span>{talk.current_status}</span>}
                    </div>
                )}

                <div className="career-talk-detail-body">
                    {talk.body || talk.summary}
                </div>

                {isDraft && talk.attachments?.length > 0 && (
                    <div className="career-talk-detail-files">
                        <strong>첨부 파일 (화면 확인용)</strong>
                        <ul>
                            {talk.attachments.map((file, index) => (
                                <li key={`${file.name}-${index}`}>{file.name}</li>
                            ))}
                        </ul>
                    </div>
                )}

                <p className="career-talk-detail-hint">
                    {isDraft
                        ? '프론트엔드 임시 데이터입니다. 새로고침하면 글과 파일 정보가 사라집니다.'
                        : '실제 등록된 게시글이 아닌 화면 확인용 예시입니다.'}
                </p>

                <div className="career-talk-detail-actions">
                    <button type="button" className="career-talk-cancel" onClick={onBack}>목록</button>
                    {isDraft && (
                        <>
                            <button type="button" className="career-talk-edit" onClick={onEdit}>수정</button>
                            <button type="button" className="career-talk-delete" onClick={onDelete}>삭제</button>
                        </>
                    )}
                </div>
            </article>
        </div>
    )
}
