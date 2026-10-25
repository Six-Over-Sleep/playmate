import '../../styles/CareerBriefing.css'

/** 외부 원문 링크는 서버에서 전달받은 정상적인 HTTP(S) 주소만 엽니다. */
function validArticleUrl(value) {
    if (!value) return null

    try {
        const url = new URL(value)
        return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null
    } catch {
        return null
    }
}

function formatDate(value) {
    if (!value) return '발행일 정보 없음'
    return value.replaceAll('-', '.')
}

/** 커리어 브리핑은 기사 본문을 복제하지 않고 메타데이터·요약·원문 링크만 제공합니다. */
export default function CareerNewsDetailPage({ news, onBack, saved, onToggleSave }) {
    if (!news) return null

    const originalUrl = validArticleUrl(news.original_url)

    return (
        <div className="career-news-detail">
            <button type="button" className="career-news-back" onClick={onBack}>
                ← 뉴스 목록으로
            </button>

            <article className="career-news-detail-card">
                <div className="career-news-detail-meta">
                    <span className="career-news-category-pill">{news.category}</span>
                    <span>{news.news_type}</span>
                    <span>{formatDate(news.published_at)}</span>
                </div>

                <h3>{news.title}</h3>
                <p className="career-news-source">출처: {news.publisher}</p>

                <section className="career-news-detail-section">
                    <h4>뉴스 요약</h4>
                    <p>{news.summary || '등록된 요약이 없습니다.'}</p>
                </section>

                {news.why_it_matters && (
                    <section className="career-news-detail-section">
                        <h4>취업 준비에 중요한 이유</h4>
                        <p>{news.why_it_matters}</p>
                        <small>해석 콘텐츠는 원문 기사와 별도로 표시됩니다.</small>
                    </section>
                )}

                {!!news.study_keywords?.length && (
                    <section className="career-news-detail-section">
                        <h4>연결해서 공부할 키워드</h4>
                        <div className="career-news-tags">
                            {news.study_keywords.map((keyword) => (
                                <span key={keyword}>#{keyword}</span>
                            ))}
                        </div>
                    </section>
                )}

                <div className="career-news-detail-actions">
                    <button
                        type="button"
                        className={`career-news-save ${saved ? 'saved' : ''}`}
                        onClick={onToggleSave}
                        aria-pressed={saved}
                    >
                        {saved ? '♥ 임시 스크랩됨' : '♡ 임시 스크랩'}
                    </button>
                    {originalUrl ? (
                        <a
                            className="career-news-source-link"
                            href={originalUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                        >
                            원문 기사 보기 ↗
                        </a>
                    ) : (
                        <span className="career-news-no-link" title="뉴스 수집 API 연동 후 활성화됩니다">
                            원문 기사 미연결
                        </span>
                    )}
                </div>
            </article>

            <p className="career-news-disclaimer">
                현재 콘텐츠는 화면 테스트용 가상 데이터입니다. 임시 스크랩은 새로고침하면 초기화됩니다.
            </p>
        </div>
    )
}
