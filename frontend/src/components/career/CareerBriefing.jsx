import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import CareerNewsDetailPage from '../../pages/career/CareerNewsDetailPage'
import {
    getCareerNews,
    getCareerNewsItem,
    scrapCareerNews,
    unscrapCareerNews,
} from '../../services/careerApi'
import '../../styles/CareerBriefing.css'

const NEWS_TYPES = ['전체 유형', '채용 동향', '기술 동향', '직무 분석']

// 커리어 브리핑 메뉴 이름 → 뉴스 API 직무 분야 코드 (크롤러·채용 트렌드 8개 분야)
const FIELD_CODES = {
    '데이터·AI': 'data_ai',
    '백엔드·서버': 'backend',
    '프론트엔드·웹': 'frontend',
    '모바일 개발': 'mobile',
    '클라우드·인프라': 'cloud_infra',
    '정보보안': 'security',
    'QA·테스트': 'qa_test',
    'IT기획·디자인': 'it_product',
}

function formatDate(value) {
    return value ? value.replaceAll('-', '.') : '발행일 정보 없음'
}

function publishedKey(article) {
    return article.published_datetime || article.published_at || ''
}

// 뉴스 상세 URL: /career/briefing/news/:newsId (직접 접속·새로고침·뒤로 가기 지원)
const LIST_PATH = '/career/briefing'
const DETAIL_PATH = /^\/career\/briefing\/news\/(\d+)\/?$/

function newsIdFromPath(pathname) {
    const match = pathname.match(DETAIL_PATH)
    const newsId = match ? Number(match[1]) : null
    return Number.isSafeInteger(newsId) && newsId > 0 ? newsId : null
}

/** 수집된 IT 뉴스 목록·필터·상세와 회원별 스크랩을 담당합니다. */
export default function CareerBriefing({ menus }) {
    const location = useLocation()
    const navigate = useNavigate()
    const routeNewsId = newsIdFromPath(location.pathname)

    const [activeMenu, setActiveMenu] = useState('전체')
    const [input, setInput] = useState('')
    const [keyword, setKeyword] = useState('')
    const [newsType, setNewsType] = useState('전체 유형')
    const [sort, setSort] = useState('latest')

    const [news, setNews] = useState([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState('')
    const [reloadKey, setReloadKey] = useState(0)
    const [pendingIds, setPendingIds] = useState([])
    const [scrapError, setScrapError] = useState('')

    // 상세는 목록에 없는 뉴스(30일 지난 뉴스, 마이페이지에서 연 숨긴 뉴스)도 열 수 있도록 한 건씩 조회한다.
    const [detail, setDetail] = useState(null)
    const [detailError, setDetailError] = useState('')
    const [detailReloadKey, setDetailReloadKey] = useState(0)

    // 직무 분야가 바뀌면 서버에서 해당 분야 뉴스를 다시 받는다. 늦게 온 이전 응답은 무시한다.
    useEffect(() => {
        const controller = new AbortController()
        setLoading(true)
        setError('')

        getCareerNews({ fieldCode: FIELD_CODES[activeMenu] }, { signal: controller.signal })
            .then((data) => setNews(data.items || []))
            .catch((err) => {
                if (err.name === 'AbortError') return
                setNews([])
                setError(err.message || '뉴스를 불러오지 못했습니다.')
            })
            .finally(() => {
                if (!controller.signal.aborted) setLoading(false)
            })

        return () => controller.abort()
    }, [activeMenu, reloadKey])

    // URL의 뉴스 ID가 바뀌면 상세를 다시 조회한다. 늦게 온 이전 응답은 무시한다.
    useEffect(() => {
        setDetail(null)
        setDetailError('')
        setScrapError('')
        if (routeNewsId === null) return undefined

        const controller = new AbortController()
        getCareerNewsItem(routeNewsId, { signal: controller.signal })
            .then((data) => setDetail(data))
            .catch((err) => {
                if (err.name === 'AbortError') return
                setDetailError(err.message || '뉴스를 불러오지 못했습니다.')
            })

        return () => controller.abort()
    }, [routeNewsId, detailReloadKey])

    // 수집 데이터에 뉴스 유형이 생기면 유형 필터를 다시 표시한다.
    const hasNewsTypes = news.some((article) => article.news_type)

    const articles = useMemo(() => {
        const key = keyword.trim().toLocaleLowerCase('ko-KR')
        const filtered = news.filter((article) => {
            const fieldCode = FIELD_CODES[activeMenu]
            const matchesMenu = !fieldCode || (article.field_codes || []).includes(fieldCode)
            const matchesType = !hasNewsTypes || newsType === '전체 유형' || article.news_type === newsType
            const searchText = [
                article.title,
                article.summary,
                article.publisher,
                ...(article.categories || []),
                ...(article.keywords || []),
            ].join(' ').toLocaleLowerCase('ko-KR')
            return matchesMenu && matchesType && searchText.includes(key)
        })

        return [...filtered].sort((a, b) => {
            if (sort === 'oldest') return publishedKey(a).localeCompare(publishedKey(b))
            if (sort === 'title') return a.title.localeCompare(b.title, 'ko')
            return publishedKey(b).localeCompare(publishedKey(a))
        })
    }, [news, activeMenu, keyword, newsType, sort, hasNewsTypes])

    function changeMenu(menu) {
        setActiveMenu(menu)
        setInput('')
        setKeyword('')
    }

    function openDetail(article) {
        navigate(`${LIST_PATH}/news/${article.id}`, { state: { fromBriefing: true } })
    }

    // 목록에서 열었으면 브라우저 기록을 되돌리고, 직접 접속·마이페이지에서 왔으면 목록으로 이동한다.
    function backToList() {
        if (location.state?.fromBriefing) navigate(-1)
        else navigate(LIST_PATH)
    }

    // 스크랩 결과를 목록과 상세에 함께 반영한다.
    const toggleScrap = useCallback(async (article) => {
        if (pendingIds.includes(article.id)) return
        setPendingIds((ids) => [...ids, article.id])
        setScrapError('')
        try {
            const result = article.scrapped_by_me
                ? await unscrapCareerNews(article.id)
                : await scrapCareerNews(article.id)
            const apply = (item) => (
                item.id === result.news_id
                    ? { ...item, scrapped_by_me: result.scrapped_by_me }
                    : item
            )
            setNews((items) => items.map(apply))
            setDetail((item) => (item ? apply(item) : item))
        } catch (err) {
            setScrapError(err.message || '스크랩 처리에 실패했습니다.')
        } finally {
            setPendingIds((ids) => ids.filter((id) => id !== article.id))
        }
    }, [pendingIds])

    if (routeNewsId !== null) {
        if (detail?.id === routeNewsId) {
            return (
                <CareerNewsDetailPage
                    news={detail}
                    onBack={backToList}
                    saved={detail.scrapped_by_me}
                    saving={pendingIds.includes(detail.id)}
                    saveError={scrapError}
                    onToggleSave={() => toggleScrap(detail)}
                />
            )
        }

        return (
            <div className="career-news-detail">
                <button type="button" className="career-news-back" onClick={backToList}>
                    ← 뉴스 목록으로
                </button>
                {detailError ? (
                    <div className="career-news-empty" role="alert">
                        <strong>뉴스를 볼 수 없어요.</strong>
                        <p>{detailError}</p>
                        <button type="button" onClick={() => setDetailReloadKey((key) => key + 1)}>
                            다시 시도
                        </button>
                    </div>
                ) : (
                    <div className="career-news-empty" role="status">
                        <strong>뉴스를 불러오는 중입니다.</strong>
                    </div>
                )}
            </div>
        )
    }

    return (
        <div className="career-briefing">
            <p className="career-briefing-intro">
                IT 직무 분야별 최근 뉴스를 한곳에서 살펴보는 공간입니다.
                뉴스는 Google 뉴스 RSS에서 제목·출처·발행일·기사 링크만 수집합니다.
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
                        placeholder="제목·언론사·분야 검색"
                        aria-label="뉴스 검색"
                    />
                    <button type="submit">검색</button>
                </form>

                {/* 수집 데이터에 뉴스 유형이 없는 동안에는 숨깁니다. */}
                {hasNewsTypes && (
                    <select
                        value={newsType}
                        onChange={(event) => setNewsType(event.target.value)}
                        aria-label="뉴스 유형"
                    >
                        {NEWS_TYPES.map((item) => <option key={item} value={item}>{item}</option>)}
                    </select>
                )}

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

            {scrapError && (
                <p className="career-news-error" role="alert">{scrapError}</p>
            )}

            {loading ? (
                <div className="career-news-empty" role="status">
                    <strong>뉴스를 불러오는 중입니다.</strong>
                </div>
            ) : error ? (
                <div className="career-news-empty" role="alert">
                    <strong>뉴스를 불러오지 못했어요.</strong>
                    <p>{error}</p>
                    <button type="button" onClick={() => setReloadKey((key) => key + 1)}>
                        다시 시도
                    </button>
                </div>
            ) : (
                <>
                    <p className="career-briefing-count" aria-live="polite">
                        표시 결과 <strong>{articles.length}</strong>건
                    </p>

                    <div className="career-news-list">
                        {articles.length > 0 ? articles.map((article) => (
                            <article key={article.id} className="career-news-item">
                                <div className="career-news-meta">
                                    <span className="career-news-category-pill">{article.category}</span>
                                    {article.news_type && <span>{article.news_type}</span>}
                                    <span>{formatDate(article.published_at)}</span>
                                </div>

                                <button
                                    type="button"
                                    className="career-news-title"
                                    onClick={() => openDetail(article)}
                                    aria-label={`${article.title} 상세 보기`}
                                >
                                    {article.title}
                                </button>

                                {article.summary && <p className="career-news-summary">{article.summary}</p>}
                                <div className="career-news-bottom">
                                    <span>{article.publisher || '출처 정보 없음'}</span>
                                    <div className="career-news-tags">
                                        {(article.keywords || []).slice(0, 3).map((tag) => (
                                            <span key={tag}>#{tag}</span>
                                        ))}
                                    </div>
                                    <button
                                        type="button"
                                        className={`career-news-save ${article.scrapped_by_me ? 'saved' : ''}`}
                                        onClick={() => toggleScrap(article)}
                                        disabled={pendingIds.includes(article.id)}
                                        aria-label={`${article.title} ${article.scrapped_by_me ? '스크랩 취소' : '스크랩'}`}
                                        aria-pressed={Boolean(article.scrapped_by_me)}
                                    >
                                        {article.scrapped_by_me ? '♥' : '♡'}
                                    </button>
                                </div>
                            </article>
                        )) : news.length === 0 ? (
                            <div className="career-news-empty">
                                <strong>
                                    {FIELD_CODES[activeMenu] ? `${activeMenu} 분야에 ` : ''}최근 30일 동안 수집된 뉴스가 없어요.
                                </strong>
                                <p>뉴스 수집 후 다시 확인해 주세요.</p>
                            </div>
                        ) : (
                            <div className="career-news-empty">
                                <strong>조건에 맞는 뉴스가 없어요.</strong>
                                <p>검색어나 정렬 조건을 변경해 주세요.</p>
                                <button
                                    type="button"
                                    onClick={() => {
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
                </>
            )}
            <p className="career-news-disclaimer">
                기사 본문은 저장하지 않습니다. 기사 링크는 Google 뉴스를 거쳐 언론사 기사로 이동합니다.
            </p>
        </div>
    )
}
