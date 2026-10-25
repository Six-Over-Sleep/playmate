import '../../styles/CareerLabDetailPage.css'

const TYPE_LABELS = {
    QUESTION: '질문',
    DISCUSSION: '토론',
    FEEDBACK: '피드백',
}

/** 질문·토론·피드백 상세. 프론트엔드 임시 글에만 수정·삭제·투표·해결 표시를 제공합니다. */
export default function CareerLabDetailPage({ post, onBack, onEdit, onDelete, onVote, onToggleResolved }) {
    if (!post) return null

    const isDraft = post.isDraft === true
    const options = post.poll_options || []
    const votes = post.poll_votes || []
    const voteCount = votes.reduce((sum, number) => sum + number, 0)

    return (
        <div className="career-lab-detail">
            <button type="button" className="career-lab-back" onClick={onBack}>
                ← 커리어 연구소 목록으로
            </button>

            <article className="career-lab-detail-card">
                <div className="career-lab-detail-top">
                    <span className="career-post-tag">{post.menu}</span>
                    <small>{isDraft ? '브라우저 임시 글' : '화면용 예시 글'}</small>
                </div>

                <h3>{post.title}</h3>
                <div className="career-lab-detail-meta">
                    <span>{post.author}</span>
                    <span>{post.date}</span>
                    {isDraft && <span>{TYPE_LABELS[post.post_type]}</span>}
                </div>

                <div className="career-lab-detail-body">{post.body || post.summary}</div>

                {isDraft && post.post_type === 'QUESTION' && (
                    <>
                        {post.desired_job && (
                            <p className="career-lab-detail-field">희망 직무: <strong>{post.desired_job}</strong></p>
                        )}
                        {post.question_detail && (
                            <section className="career-lab-detail-extra">
                                <h4>답변받고 싶은 내용</h4>
                                <p>{post.question_detail}</p>
                            </section>
                        )}
                        <div className="career-lab-resolution">
                            <span>질문 상태: <strong>{post.resolved ? '해결됨' : '답변 대기'}</strong></span>
                            <button type="button" onClick={onToggleResolved}>
                                {post.resolved ? '미해결로 변경' : '해결 표시'}
                            </button>
                        </div>
                    </>
                )}

                {isDraft && post.post_type === 'DISCUSSION' && (
                    <>
                        <section className="career-lab-detail-extra">
                            <h4>나의 주장·의견</h4>
                            <p>{post.discussion_stance}</p>
                        </section>
                        {options.length >= 2 && (
                            <section className="career-lab-detail-poll">
                                <h4>선택지 투표 (화면 테스트용)</h4>
                                <p>총 {voteCount}표 · 현재 브라우저에서 1회만 선택 가능</p>
                                {options.map((option, index) => (
                                    <button
                                        key={`${index}-${option}`}
                                        type="button"
                                        className={post.my_vote === index ? 'selected' : ''}
                                        disabled={post.my_vote !== null && post.my_vote !== undefined}
                                        onClick={() => onVote(index)}
                                    >
                                        <span>{option}</span>
                                        <span>{votes[index] || 0}표</span>
                                    </button>
                                ))}
                            </section>
                        )}
                    </>
                )}

                {isDraft && post.post_type === 'FEEDBACK' && (
                    <>
                        <section className="career-lab-detail-extra">
                            <h4>피드백 요청 사항</h4>
                            <p>{post.feedback_focus}</p>
                        </section>
                        {post.reference_url && (
                            <p className="career-lab-detail-field">
                                참고 링크: <a href={post.reference_url} target="_blank" rel="noopener noreferrer">외부 자료 열기</a>
                            </p>
                        )}
                        {!!post.file_names?.length && (
                            <p className="career-lab-detail-field">
                                첨부 예정 파일명: {post.file_names.join(', ')} (업로드되지 않음)
                            </p>
                        )}
                    </>
                )}

                <p className="career-lab-detail-hint">
                    {isDraft
                        ? '임시 데이터입니다. 새로고침하면 사라지고, 해결 표시·투표·첨부 파일은 서버에 반영되지 않습니다.'
                        : '예시 글입니다. 실제 게시글이 아니므로 수정 및 투표할 수 없습니다.'}
                </p>

                <div className="career-lab-detail-actions">
                    <button type="button" className="career-lab-cancel" onClick={onBack}>목록</button>
                    {isDraft && (
                        <>
                            <button type="button" className="career-lab-edit" onClick={onEdit}>수정</button>
                            <button type="button" className="career-lab-delete" onClick={onDelete}>삭제</button>
                        </>
                    )}
                </div>
            </article>
        </div>
    )
}
