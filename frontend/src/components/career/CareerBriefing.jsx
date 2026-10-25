import { useMemo, useState } from 'react'
import CareerNewsDetailPage from '../../pages/career/CareerNewsDetailPage'
import { CAREER_NEWS_DEMO } from '../../data/careerNewsDemo'
import '../../styles/CareerBriefing.css'

const NEWS_TYPES = ['전체 유형', '채용 동향', '기술 동향', '직무 분석']

function formatDate(value) {
    return value ? value.replaceAll('-', '.') : '발행일 정보 없음'
}

/** 뉴스 목록·필터·상세 UI만 담당합니다. 실제 수집 API는 다음 단계에서 연결합니다. */
export default function CareerBriefing({ menus }) {
    const [activeMenu, setActiveMenu] = useState('전체')
    const [input, setInput] = useState('')
    const [keyword, setKeyword] = useState('')
    const [newsType, setNewsType] = useState('전체 유형')
    const [sort, setSort] = useState('latest')
    const [selectedNews, setSelectedNews] = useState(null)
    const [savedIds, setSavedIds] = useState([])

    const articles = useMemo(() => {
        const key = keyword.trim().toLocaleLowerCase('ko-KR')
        const filtered = CAREER_NEWS_DEMO.filter((article) => {
            const matchesMenu = activeMenu === '전체' || article.category === activeMenu
            const matchesType = newsType === '전체 유형' || article.news_type === newsType
            const searchText = [
                article.title,
                article.summary,
                article.publisher,
                article.category,
                ...(article.keywords || []),
            ].join(' ').toLocaleLowerCase('ko-KR')
            return matchesMenu && matchesType && searchText.includes(key)
        })

        return filtered.sort((a, b) => {
            if (sort === 'oldest') {
                return (a.published_at || '').localeCompare(b.published_at || '')
            }
            if (sort === 'title') return a.title.localeCompare(b.title, 'ko')
            return (b.published_at || '').localeCompare(a.published_at || '')
        })
    }, [activeMenu, keyword, newsType, sort])

    function changeMenu(menu) {
        setActiveMenu(menu)
        setInput('')
        setKeyword('')
        setSelectedNews(null)
    }

    function toggleSaved(id) {
        setSavedIds((ids) => ids.includes(id)
            ? ids.filter((item) => item !== id)
            : [...ids, id]
        )
    }

    if (selectedNews) {
        return (
            <CareerNewsDetailPage
                news={selectedNews}
                onBack={() => setSelectedNews(null)}
                saved={savedIds.includes(selectedNews.id)}
                onToggleSave={() => toggleSaved(selectedNews.id)}
            />
        )
    }

    return (
        <div className="career-briefing">
            <p className="career-briefing-intro">
                IT 분야 채용·직무 뉴스를 한곳에서 살펴보는 공간입니다.
                기사 원문은 수집 API 연동 이후 연결됩니다.
            </p>

            <p className="career-briefing-demo" role="note">
                현재는 <strong>화면 테스트용 가상 뉴스 6건</strong>입니다.
                실제 기사·언론사·발행일 데이터가 아니에요.
            </p>

            <nav className="career-subnav" aria-label="커리어 브리핑 직무별 필터">
                {menus.map((menu) => (
                    <button
                        key={menu}
                        type="button"
                        className={activeMenu === menu ? 'active' : ''}
                        aria-pressed={activeMenu === menu}
                        onClick={() => changeMenu(menu)}
                    >
                        {menu}
                    </button>
                ))}
            </nav>

            <div className="career-briefing-toolbar">
                <form
                    className="career-search"
                    onSubmit={(event) => {
                        event.preventDefault()
                        setKeyword(input)
                    }}
                >
                    <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                        <circle cx="11" cy="11" r="7" />
                        <path d="m16 16 4 4" />
                    </svg>
                    <input
                        value={input}
                        onChange={(event) => setInput(event.target.value)}
                        placeholder="제목·키워드·내용 검색"
                        aria-label="뉴스 검색"
                    />
                    <button type="submit">검색</button>
                </form>

                <select
                    value={newsType}
                    onChange={(event) => setNewsType(event.target.value)}
                    aria-label="뉴스 유형"
                >
                    {NEWS_TYPES.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>

                <select
                    value={sort}
                    onChange={(event) => setSort(event.target.value)}
                    aria-label="뉴스 정렬"
                >
                    <option value="latest">최신순</option>
                    <option value="oldest">오래된순</option>
                    <option value="title">제목순</option>
                </select>
            </div>

            <p className="career-briefing-count" aria-live="polite">
                표시 결과 <strong>{articles.length}</strong>건 (가상 데이터)
            </p>

            <div className="career-news-list">
                {articles.length > 0 ? articles.map((article) => (
                    <article key={article.id} className="career-news-item">
                        <div className="career-news-meta">
                            <span className="career-news-category-pill">{article.category}</span>
                            <span>{article.news_type}</span>
                            <span>{formatDate(article.published_at)} (예시)</span>
                        </div>

                        <button
                            type="button"
                            className="career-news-title"
                            onClick={() => setSelectedNews(article)}
                            aria-label={`${article.title} 상세 보기`}
                        >
                            {article.title}
                        </button>

                        <p className="career-news-summary">{article.summary}</p>
                        <div className="career-news-bottom">
                            <span>{article.publisher}</span>
                            <div className="career-news-tags">
                                {article.keywords.slice(0, 3).map((tag) => (
                                    <span key={tag}>#{tag}</span>
                                ))}
                            </div>
                            <button
                                type="button"
                                className={`career-news-save ${savedIds.includes(article.id) ? 'saved' : ''}`}
                                onClick={() => toggleSaved(article.id)}
                                aria-label={`${article.title} ${savedIds.includes(article.id) ? '임시 스크랩 취소' : '임시 스크랩'}`}
                                aria-pressed={savedIds.includes(article.id)}
                            >
                                {savedIds.includes(article.id) ? '♥' : '♡'}
                            </button>
                        </div>
                    </article>
                )) : (
                    <div className="career-news-empty">
                        <strong>조건에 맞는 뉴스가 없어요.</strong>
                        <p>직무·뉴스 유형·검색어를 변경해 주세요.</p>
                        <button
                            type="button"
                            onClick={() => {
                                setActiveMenu('전체')
                                setInput('')
                                setKeyword('')
                                setNewsType('전체 유형')
                                setSort('latest')
                            }}
                        >
                            필터 초기화
                        </button>
                    </div>
                )}
            </div>
            <p className="career-news-disclaimer">스크랩은 화면 테스트 전용이며 서버에 저장되지 않습니다.</p>
        </div>
    )
}
