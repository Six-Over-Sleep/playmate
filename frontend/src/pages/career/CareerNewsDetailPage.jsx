import '../../styles/CareerBriefing.css'

const SUMMARY_PENDING = 'AI 뉴스 요약 준비 중입니다.'

/** 외부 링크는 서버에서 전달받은 정상적인 HTTP(S) 주소만 엽니다. */
function validArticleUrl(value) {
    if (!value) return null

    try {
        const url = new URL(value)
        return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null
    } catch {
        return null
    }
}

/**
 * 기사 링크와 목적지 표시.
 * - original_url: 언론사 원문으로 확인된 주소 (현재 수집 데이터에는 없음)
 * - link_url + GOOGLE_NEWS_RSS: Google 뉴스 기사 페이지 (언론사 원문 주소 아님)
 * - link_url + UNVERIFIED: 목적지를 확인하지 않은 링크
 */
function articleLink(news) {
    const original = validArticleUrl(news.original_url)
    if (original) {
        return { href: original, label: '언론사 원문 보기 ↗', note: null }
    }
    const link = validArticleUrl(news.link_url)
    if (link && news.link_type === 'GOOGLE_NEWS_RSS') {
        return {
            href: link,
            label: 'Google 뉴스에서 기사 보기 ↗',
            note: 'Google 뉴스를 거쳐 언론사 기사로 이동합니다.',
        }
    }
    if (link) {
        return {
            href: link,
            label: '기사 링크 열기 ↗',
            note: '목적지를 확인하지 않은 링크입니다.',
        }
    }
    return null
}

function formatDate(value) {
    if (!value) return '발행일 정보 없음'
    return value.replaceAll('-', '.')
}

/** 커리어 브리핑은 기사 본문을 복제하지 않고 메타데이터·요약·기사 링크만 제공합니다. */
export default function CareerNewsDetailPage({ news, onBack, saved, saving = false, saveError = '', onToggleSave }) {
    if (!news) return null

    // 운영자가 숨긴 뉴스: 내 스크랩에서만 열리며 기사 링크 없이 스크랩 해제만 할 수 있다.
    const hidden = Boolean(news.is_hidden)
    const link = hidden ? null : articleLink(news)
    const categories = news.categories?.length ? news.categories : [news.category].filter(Boolean)

    return (
        <div className="career-news-detail">
            <button type="button" className="career-news-back" onClick={onBack}>
                ← 뉴스 목록으로
            </button>

            <article className="career-news-detail-card">
                <div className="career-news-detail-meta">
                    {categories.map((category) => (
                        <span key={category} className="career-news-category-pill">{category}</span>
                    ))}
                    {news.news_type && <span>{news.news_type}</span>}
                    <span>{formatDate(news.published_at)}</span>
                </div>

                <h3>{news.title}</h3>
                <p className="career-news-source">출처: {news.publisher || '출처 정보 없음'}</p>
                {hidden && (
                    <p className="career-news-link-note" role="status">
                        현재 커리어 브리핑에 표시되지 않는 뉴스입니다. 스크랩 해제만 할 수 있어요.
                    </p>
                )}

                <section className="career-news-detail-section">
                    <h4>뉴스 요약</h4>
                    <p className={news.summary ? '' : 'career-news-pending'}>{news.summary || SUMMARY_PENDING}</p>
                </section>

                <section className="career-news-detail-section">
                    <h4>취업 준비에 중요한 이유</h4>
                    {news.why_it_matters ? (
                        <>
                            <p>{news.why_it_matters}</p>
                            <small>해석 콘텐츠는 원문 기사와 별도로 표시됩니다.</small>
                        </>
                    ) : (
                        <p className="career-news-pending">{SUMMARY_PENDING}</p>
                    )}
                </section>

                <section className="career-news-detail-section">
                    <h4>연결해서 공부할 키워드</h4>
                    {news.study_keywords?.length ? (
                        <div className="career-news-tags">
                            {news.study_keywords.map((keyword) => (
                                <span key={keyword}>#{keyword}</span>
                            ))}
                        </div>
                    ) : (
                        <p className="career-news-pending">{SUMMARY_PENDING}</p>
                    )}
                </section>

                <div className="career-news-detail-actions">
                    <button
                        type="button"
                        className={`career-news-save ${saved ? 'saved' : ''}`}
                        onClick={onToggleSave}
                        disabled={saving || (hidden && !saved)}
                        aria-pressed={Boolean(saved)}
                    >
                        {saved ? '♥ 스크랩됨' : '♡ 스크랩'}
                    </button>
                    {link ? (
                        <a
                            className="career-news-source-link"
                            href={link.href}
                            target="_blank"
                            rel="noopener noreferrer"
                        >
                            {link.label}
                        </a>
                    ) : (
                        <span className="career-news-no-link" title="기사 링크가 없습니다">
                            {hidden ? '기사 링크 숨김' : '기사 링크 없음'}
                        </span>
                    )}
                </div>
                {link?.note && <p className="career-news-link-note">{link.note}</p>}
                {saveError && <p className="career-news-error" role="alert">{saveError}</p>}
            </article>

            <p className="career-news-disclaimer">
                기사 본문은 저장하지 않으며 제목·출처·발행일·기사 링크만 제공합니다.
            </p>
        </div>
    )
}
