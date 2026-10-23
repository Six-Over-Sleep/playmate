import '../../styles/CareerReviewDetailPage.css'

const STAGE_NAMES = {
    DOCUMENT: '서류',
    CODING_TEST: '코딩 테스트',
    ASSIGNMENT: '과제',
    INTERVIEW: '면접',
    FINAL: '최종',
}

const RESULT_NAMES = {
    PASS: '합격',
    FAIL: '불합격',
    PENDING: '대기',
}

const TYPE_NAMES = {
    NEW: '신입',
    EXPERIENCED: '경력',
}

/** 화면 테스트용 후기 상세: 서버에 없는 값은 추정하지 않는다. */
export default function CareerReviewDetailPage({ review, onBack, onEdit, onDelete }) {
    if (!review) return null

    const isDraft = review.isDraft === true

    return (
        <div className="career-review-detail">
            <button
                type="button"
                className="career-review-back"
                onClick={onBack}
            >
                ← 취준 도감 목록으로
            </button>

            <article className="career-review-detail-card">
                <div className="career-review-detail-top">
                    <span className="career-post-tag">{review.menu}</span>
                    <span className="career-review-demo-label">
                        {isDraft ? '브라우저 임시 후기' : '화면용 예시 후기'}
                    </span>
                </div>

                <h3>{review.title}</h3>

                <div className="career-review-detail-meta">
                    <span>{review.author}</span>
                    <span>{review.date}</span>
                </div>

                <dl className="career-review-facts">
                    <div>
                        <dt>기업명</dt>
                        <dd>{review.company_name || '비공개 / 미입력'}</dd>
                    </div>
                    <div>
                        <dt>지원 직무</dt>
                        <dd>{review.job_category || '미입력'}</dd>
                    </div>
                    <div>
                        <dt>지원 유형</dt>
                        <dd>{TYPE_NAMES[review.experience_level] || '미입력'}</dd>
                    </div>
                    <div>
                        <dt>전형 단계</dt>
                        <dd>{STAGE_NAMES[review.process_stage] || '미입력'}</dd>
                    </div>
                    <div>
                        <dt>전형 결과</dt>
                        <dd>{RESULT_NAMES[review.process_result] || '미입력'}</dd>
                    </div>
                </dl>

                <div className="career-review-detail-body">
                    {review.body || review.summary}
                </div>

                <p className="career-review-detail-hint">
                    {isDraft
                        ? '프론트엔드 임시 데이터입니다. 새로고침하거나 페이지를 벗어나면 사라집니다.'
                        : '예시 게시글은 실제 후기 데이터가 아니므로 상세 항목이 비어 있습니다.'}
                </p>

                <div className="career-review-detail-actions">
                    <button type="button" className="career-review-cancel" onClick={onBack}>
                        목록
                    </button>
                    {isDraft && (
                        <>
                            <button type="button" className="career-review-edit-btn" onClick={onEdit}>
                                수정
                            </button>
                            <button type="button" className="career-review-delete-btn" onClick={onDelete}>
                                삭제
                            </button>
                        </>
                    )}
                </div>
            </article>
        </div>
    )
}
