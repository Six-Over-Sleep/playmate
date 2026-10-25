import '../../styles/CareerTalkDetailPage.css'

/** 커리어 톡톡 상세 화면. 실제 서버의 게시글만 표시합니다. */
export default function CareerTalkDetailPage({
    talk,
    onBack,
    onEdit,
    onDelete,
    busy = false,
}) {
    if (!talk) return null

    return (
        <div className="career-talk-detail">
            <button
                type="button"
                className="career-talk-back"
                onClick={onBack}
                disabled={busy}
            >
                ← 커리어 톡톡 목록으로
            </button>

            <article className="career-talk-detail-card">
                <div className="career-talk-detail-top">
                    <span className="career-post-tag">{talk.menu}</span>
                </div>

                <h3>{talk.title}</h3>

                <div className="career-talk-detail-meta">
                    <span>{talk.author}</span>
                    <span>{talk.date}</span>
                </div>

                {(talk.job_category || talk.current_status) && (
                    <div className="career-talk-detail-tags">
                        {talk.job_category && (
                            <span>{talk.job_category}</span>
                        )}
                        {talk.current_status && (
                            <span>{talk.current_status}</span>
                        )}
                    </div>
                )}

                <div className="career-talk-detail-body">
                    {talk.body || talk.summary}
                </div>

                <div className="career-talk-detail-actions">
                    <button
                        type="button"
                        className="career-talk-cancel"
                        onClick={onBack}
                        disabled={busy}
                    >
                        목록
                    </button>

                    {talk.is_owner && (
                        <>
                            <button
                                type="button"
                                className="career-talk-edit"
                                onClick={onEdit}
                                disabled={busy}
                            >
                                수정
                            </button>
                            <button
                                type="button"
                                className="career-talk-delete"
                                onClick={onDelete}
                                disabled={busy}
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
