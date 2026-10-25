import { useEffect, useMemo, useRef, useState } from 'react'
import '../../styles/CareerPage.css'
import CareerReviewForm from '../../components/career/CareerReviewForm'
import CareerReviewDetailPage from './CareerReviewDetailPage'
import CareerTalkForm from '../../components/career/CareerTalkForm'
import CareerTalkDetailPage from './CareerTalkDetailPage'
import CareerLoungeForm from '../../components/career/CareerLoungeForm'
import CareerLoungeDetailPage from './CareerLoungeDetailPage'
import CareerLabForm from '../../components/career/CareerLabForm'
import CareerLabDetailPage from './CareerLabDetailPage'
import CareerBriefing from '../../components/career/CareerBriefing'
import CareerInsights from '../../components/career/CareerInsights'
import {
    createCareerReview,
    getCareerReviews,
    getCareerReview,
    updateCareerReview,
    deleteCareerReview,
    getCareerTalks,
    getCareerTalk,
    createCareerTalk,
    updateCareerTalk,
    deleteCareerTalk,
    getCareerLounges,
    getCareerLounge,
    createCareerLounge,
    updateCareerLounge,
    deleteCareerLounge,
    getCareerLabs,
    getCareerLab,
    createCareerLab,
    updateCareerLab,
    deleteCareerLab,
    resolveCareerLab,
    voteCareerLab,
} from '../../services/careerApi'

// 취업 메인 6개 카테고리. 채용 인사이트는 게시판이 아닌 대시보드입니다.
const CATEGORIES = [
    {
        id: 'insights', name: '채용 인사이트', icon: 'chart',
        description: '채용 통계와 트렌드', menus: [],
    },
    {
        id: 'reviews', name: '취준 도감', icon: 'book',
        description: '전형별 합격·탈락 후기',
        menus: ['전체', '서류 도감', '코테·과제 도감', '면접 도감', '최종 결과', '취업 성공기'],
    },
    {
        id: 'talk', name: '커리어 톡톡', icon: 'chat',
        description: '취업과 이직 이야기',
        menus: ['전체', '취업 고민', '이직 고민', '진로 고민', '취준 일상', '취업 근황', '연봉·처우 고민'],
    },
    {
        id: 'lounge', name: '현직자 라운지', icon: 'users',
        description: '졸업생과 현직자 이야기',
        menus: ['전체', '현직자의 하루', '실무 기술', '회사 생활', '직무 Q&A', '주니어 생존기', '졸업생 인터뷰'],
    },
    {
        id: 'lab', name: '커리어 연구소', icon: 'light',
        description: '질문·토론·피드백',
        menus: ['전체', '취업 전략', '포트폴리오 피드백', '이력서·자소서', '기술면접 스터디', '자격증·스펙 전략', '직무 비교'],
    },
    {
        id: 'briefing', name: '커리어 브리핑', icon: 'news',
        description: '직무별 취업 뉴스',
        menus: ['전체', '개발·소프트웨어', '데이터·AI', '클라우드·인프라', '정보보안', 'IT 산업·채용', 'IT 기획·디자인·QA'],
    },
]

// 취준 도감에 표시할 메뉴와 API에서 사용하는 값의 대응표
const REVIEW_MENU_CODES = {
    '전체': null,
    '서류 도감': 'DOCUMENT',
    '코테·과제 도감': 'CODING_ASSIGNMENT',
    '면접 도감': 'INTERVIEW',
    '최종 결과': 'FINAL',
    '취업 성공기': 'SUCCESS',
}

const REVIEW_MENU_NAMES = Object.fromEntries(
    Object.entries(REVIEW_MENU_CODES)
        .filter(([, code]) => code)
        .map(([name, code]) => [code, name])
)

const JOB_CATEGORY_CODES = {
    '소프트웨어 개발': 'SOFTWARE_DEVELOPMENT',
    '데이터·AI': 'DATA_AI',
    '인프라·클라우드': 'INFRA_CLOUD',
    '정보보안': 'SECURITY',
    'IT 기획·관리': 'IT_PLANNING',
    'QA·테스트': 'QA_TEST',
    '디자인·UX': 'DESIGN_UX',
    '기타 IT 직무': 'OTHER_IT',
}

const JOB_CATEGORY_NAMES = Object.fromEntries(
    Object.entries(JOB_CATEGORY_CODES).map(([name, code]) => [code, name])
)

const STAGE_CATEGORY_CODES = {
    DOCUMENT: 'DOCUMENT',
    CODING_TEST: 'CODING_ASSIGNMENT',
    ASSIGNMENT: 'CODING_ASSIGNMENT',
    INTERVIEW: 'INTERVIEW',
    FINAL: 'FINAL',
}

const APPLICATION_TYPE_CODES = {
    '신입': 'NEW',
    '경력': 'EXPERIENCED',
    NEW: 'NEW',
    EXPERIENCED: 'EXPERIENCED',
}

// 커리어 연구소 하위 메뉴 ↔ 서버 코드
const LAB_MENU_CODES = {
    '전체': null,
    '취업 전략': 'JOB_STRATEGY',
    '포트폴리오 피드백': 'PORTFOLIO_FEEDBACK',
    '이력서·자소서': 'RESUME',
    '기술면접 스터디': 'TECH_INTERVIEW',
    '자격증·스펙 전략': 'CERTIFICATION',
    '직무 비교': 'JOB_COMPARISON',
}

const LAB_MENU_NAMES = Object.fromEntries(
    Object.entries(LAB_MENU_CODES)
        .filter(([, code]) => code)
        .map(([name, code]) => [code, name])
)

const LAB_PAGE_SIZE = 10

function toLabPost(data) {
    return {
        ...data,
        menu: LAB_MENU_NAMES[data.subcategory_code] || '취업 전략',
        summary: data.body_preview || data.body?.slice(0, 150) || '',
        author: data.author_name,
        date: data.created_at
            ? new Date(data.created_at).toLocaleDateString('ko-KR')
            : '',
        poll_options: data.poll_options || [],
        isServer: true,
        isDraft: false,
    }
}

function toLabPayload(form) {
    const subcategory = form.subcategory_code || LAB_MENU_CODES[form.menu]
    const title = String(form.title || '').trim()
    const body = String(form.body || '').trim()

    if (!subcategory) throw new Error('하위 게시판을 선택해 주세요.')
    if (!title || !body) throw new Error('제목과 본문을 입력해 주세요.')

    return {
        title,
        body,
        subcategory_code: subcategory,
        is_anonymous: form.is_anonymous ?? true,
    }
}

// 커리어 톡톡 화면 선택값 <-> 서버 코드
const TALK_MENU_CODES = {
    '전체': null,
    '취업 고민': 'JOB_SEARCH',
    '이직 고민': 'JOB_CHANGE',
    '진로 고민': 'CAREER_PATH',
    '취준 일상': 'DAILY',
    '취업 근황': 'UPDATE',
    '연봉·처우 고민': 'SALARY',
}

const TALK_MENU_NAMES = Object.fromEntries(
    Object.entries(TALK_MENU_CODES)
        .filter(([, code]) => code)
        .map(([name, code]) => [code, name])
)

const TALK_STATUS_CODES = {
    '취업 준비 중': 'PREPARING',
    '신입': 'NEW',
    '경력': 'EXPERIENCED',
    '이직 준비 중': 'JOB_CHANGE',
    '기타': 'OTHER',
}

const TALK_STATUS_NAMES = Object.fromEntries(
    Object.entries(TALK_STATUS_CODES).map(([name, code]) => [code, name])
)

const TALK_PAGE_SIZE = 10

// 현직자 라운지 하위 카테고리 ↔ API 코드
const LOUNGE_MENU_CODES = {
    '전체': null,
    '현직자의 하루': 'DAILY_WORK',
    '실무 기술': 'WORK_SKILLS',
    '회사 생활': 'COMPANY_LIFE',
    '직무 Q&A': 'JOB_QNA',
    '주니어 생존기': 'JUNIOR_TIPS',
    '졸업생 인터뷰': 'ALUMNI_INTERVIEW',
}

const LOUNGE_MENU_NAMES = Object.fromEntries(
    Object.entries(LOUNGE_MENU_CODES)
        .filter(([, code]) => code)
        .map(([name, code]) => [code, name])
)

const LOUNGE_PAGE_SIZE = 10

// API 응답을 기존 라운지 화면 표시값으로 변환
function toLoungePost(data) {
    return {
        ...data,
        menu: LOUNGE_MENU_NAMES[data.subcategory_code] || '현직자의 하루',
        summary: data.body_preview || data.body?.slice(0, 150) || '',
        author: data.author_name,
        date: data.created_at
            ? new Date(data.created_at).toLocaleDateString('ko-KR')
            : '',
        job_category: JOB_CATEGORY_NAMES[data.job_category_code]
            || data.job_category_code || '',
        career_years: data.experience_years,
        anonymous: data.is_anonymous,
        post_type: data.subcategory_code === 'JOB_QNA' ? 'QUESTION' : 'EXPERIENCE',
        isServer: true,
        isDraft: false,
    }
}

// 실제 Backend의 CareerLoungeCreate/Update 필드만 전송
function toLoungePayload(form) {
    const subcategory = LOUNGE_MENU_CODES[form.menu]
    if (!subcategory) {
        throw new Error('게시글 주제를 선택해 주세요.')
    }

    const title = String(form.title || '').trim()
    const body = String(form.body || '').trim()
    if (!title || !body) {
        throw new Error('제목과 본문을 입력해 주세요.')
    }

    const jobCode = form.job_category
        ? JOB_CATEGORY_CODES[form.job_category] || form.job_category
        : null

    const years = form.career_years === '' || form.career_years == null
        ? null
        : Number(form.career_years)

    if (years !== null && (!Number.isInteger(years) || years < 0 || years > 50)) {
        throw new Error('경력 연차는 0~50 사이의 정수로 입력해 주세요.')
    }

    return {
        title,
        body,
        subcategory_code: subcategory,
        job_category_code: jobCode,
        experience_years: years,
        company_name: form.company_name?.trim() || null,
        is_anonymous: form.anonymous ?? true,
    }
}

// 커리어 톡톡 API 응답을 기존 화면에서 사용하는 한글 형식으로 변환
function toTalkPost(data) {
    return {
        ...data,
        menu: TALK_MENU_NAMES[data.subcategory_code] || '취업 고민',
        summary: data.body_preview || data.body?.slice(0, 150) || '',
        author: data.author_name,
        date: data.created_at
            ? new Date(data.created_at).toLocaleDateString('ko-KR')
            : '',
        job_category: JOB_CATEGORY_NAMES[data.job_category_code]
            || data.job_category_code || '',
        current_status: TALK_STATUS_NAMES[data.current_status]
            || data.current_status || '',
        anonymous: data.is_anonymous,
        isServer: true,
        isDraft: false,
    }
}

// 기존 TalkForm의 한글 값 -> CareerTalkCreate/Update 형식으로 변환
function toTalkPayload(form) {
    const subcategory = TALK_MENU_CODES[form.menu]
    if (!subcategory) {
        throw new Error('고민 유형을 선택해 주세요.')
    }

    const title = String(form.title || '').trim()
    const body = String(form.body || '').trim()
    if (!title || !body) {
        throw new Error('제목과 내용을 입력해 주세요.')
    }

    return {
        title,
        body,
        subcategory_code: subcategory,
        job_category_code: form.job_category
            ? JOB_CATEGORY_CODES[form.job_category] || form.job_category
            : null,
        current_status: form.current_status
            ? TALK_STATUS_CODES[form.current_status] || form.current_status
            : null,
        is_anonymous: form.anonymous ?? true,
    }
}

const REVIEW_PAGE_SIZE = 10

// API 응답을 기존 상세/목록 컴포넌트에서 사용하는 형태로 변환한다.
function toReviewPost(data) {
    return {
        ...data,
        menu: REVIEW_MENU_NAMES[data.subcategory_code] || '서류 도감',
        summary: data.body_preview || data.body?.slice(0, 150) || '',
        author: data.author_name,
        date: data.created_at
            ? new Date(data.created_at).toLocaleDateString('ko-KR')
            : '',
        job_category: JOB_CATEGORY_NAMES[data.job_category_code]
            || data.job_category_code,
        experience_level: data.application_type || '',
        isServer: true,
        isDraft: false,
    }
}

// 화면 작성 폼의 값을 FastAPI CareerReviewCreate 형식으로 변환한다.
function toReviewPayload(form) {
    const stage = form.process_stage
    const result = form.process_result
    const jobCode = JOB_CATEGORY_CODES[form.job_category]
        || form.job_category_code
        || form.job_category

    const data = {
        title: String(form.title || '').trim(),
        body: String(form.body || '').trim(),
        subcategory_code: form.subcategory_code || (
            stage === 'FINAL' && result === 'PASS'
                ? 'SUCCESS'
                : STAGE_CATEGORY_CODES[stage]
        ),
        company_name: form.company_name?.trim() || null,
        is_company_private: form.is_company_private ?? false,
        job_category_code: jobCode || '',
        application_type: APPLICATION_TYPE_CODES[form.experience_level || form.application_type] || null,
        process_stage: stage,
        process_result: result,
        process_date: form.process_date || null,
        interview_format: form.interview_format || null,
        is_anonymous: form.is_anonymous ?? form.anonymous ?? true,
    }

    if (data.body.length < 500) {
        throw new Error('후기 본문은 최소 500자 이상 입력해야 합니다.')
    }

    return data
}

// 기존 카테고리 카드 아이콘을 그대로 사용합니다.
function CategoryIcon({ type }) {
    const common = {
        fill: 'none',
        stroke: 'currentColor',
        strokeWidth: 1.9,
        strokeLinecap: 'round',
        strokeLinejoin: 'round',
    }

    return (
        <svg width="23" height="23" viewBox="0 0 24 24" aria-hidden="true" {...common}>
            {type === 'chart' && <><path d="M4 19h16"/><path d="M6 15v-5M11 15V5M16 15v-7M21 15V3"/></>}
            {type === 'book' && <><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v17H6.5A2.5 2.5 0 0 1 4 17.5z"/><path d="M4 17.5A2.5 2.5 0 0 1 6.5 15H20M9 7h6"/></>}
            {type === 'chat' && <><path d="M20 11.5c0 4.5-4 7.5-8 7.5-1.5 0-3-.3-4.3-1L3 20l1.2-4.2A7.1 7.1 0 0 1 4 11.5C4 7.1 7.6 4 12 4s8 3.1 8 7.5Z"/><path d="M8 11.5h8"/></>}
            {type === 'users' && <><circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2M16 5.5a3 3 0 0 1 0 5.5M17 14a5 5 0 0 1 4 5v1"/></>}
            {type === 'light' && <><path d="M9 18h6M10 21h4M9 14.8a7 7 0 1 1 6 0l-.5 3h-5z"/><path d="M12 6v2M8 10h1M15 10h1"/></>}
            {type === 'news' && <><path d="M6 4h14v15a2 2 0 0 1-2 2H6a3 3 0 0 1-3-3V6h3z"/><path d="M6 4v14a3 3 0 0 1-3 3M9 8h7M9 12h7M9 16h4"/></>}
        </svg>
    )
}

export default function CareerPage() {
    const [activeId, setActiveId] = useState(() => {
        const saved = sessionStorage.getItem('playmate-career-category')
        return CATEGORIES.some((category) => category.id === saved) ? saved : 'talk'
    })
    const [activeMenu, setActiveMenu] = useState('전체')
    const [input, setInput] = useState('')
    const [keyword, setKeyword] = useState('')
    const [sort, setSort] = useState('latest')

    // 취준 도감과 커리어 톡톡은 서버 연동, 나머지 게시판은 임시 동작 유지
    const [serverReviews, setServerReviews] = useState([])
    const [reviewView, setReviewView] = useState('list')
    const [selectedReview, setSelectedReview] = useState(null)
    const [editingReview, setEditingReview] = useState(false)
    const [reviewLoading, setReviewLoading] = useState(false)
    const [reviewBusy, setReviewBusy] = useState(false)
    const [reviewPage, setReviewPage] = useState(1)
    const [reviewTotal, setReviewTotal] = useState(0)
    const [reviewRefresh, setReviewRefresh] = useState(0)
    const reviewMutationLock = useRef(false)
    const reviewDetailRequest = useRef(0)
    const [notice, setNotice] = useState('')

    // 커리어 톡톡: 서버 목록 및 CRUD
    const [serverTalks, setServerTalks] = useState([])
    const [talkView, setTalkView] = useState('list')
    const [selectedTalk, setSelectedTalk] = useState(null)
    const [editingTalk, setEditingTalk] = useState(false)
    const [talkLoading, setTalkLoading] = useState(false)
    const [talkBusy, setTalkBusy] = useState(false)
    const [talkPage, setTalkPage] = useState(1)
    const [talkTotal, setTalkTotal] = useState(0)
    const [talkRefresh, setTalkRefresh] = useState(0)
    const talkMutationLock = useRef(false)
    const talkDetailRequest = useRef(0)

    // 현직자 라운지: 실제 PostgreSQL 목록 및 CRUD
    const [serverLounges, setServerLounges] = useState([])
    const [loungeView, setLoungeView] = useState('list')
    const [selectedLoungePost, setSelectedLoungePost] = useState(null)
    const [editingLoungePost, setEditingLoungePost] = useState(false)
    const [loungeLoading, setLoungeLoading] = useState(false)
    const [loungeBusy, setLoungeBusy] = useState(false)
    const [loungePage, setLoungePage] = useState(1)
    const [loungeTotal, setLoungeTotal] = useState(0)
    const [loungeRefresh, setLoungeRefresh] = useState(0)
    const loungeMutationLock = useRef(false)
    const loungeDetailRequest = useRef(0)

    // 커리어 연구소: 실제 PostgreSQL 기반 CRUD · 질문 상태 · 투표
    const [serverLabs, setServerLabs] = useState([])
    const [labView, setLabView] = useState('list')
    const [selectedLabPost, setSelectedLabPost] = useState(null)
    const [editingLabPost, setEditingLabPost] = useState(false)
    const [labLoading, setLabLoading] = useState(false)
    const [labBusy, setLabBusy] = useState(false)
    const [labPage, setLabPage] = useState(1)
    const [labTotal, setLabTotal] = useState(0)
    const [labRefresh, setLabRefresh] = useState(0)
    const labMutationLock = useRef(false)
    const labDetailRequest = useRef(0)

    const active = CATEGORIES.find((item) => item.id === activeId)

    // 취업 탭 내부에서 선택한 카테고리도 새로고침 후 유지
    useEffect(() => {
        sessionStorage.setItem('playmate-career-category', activeId)
    }, [activeId])

    // 취준 도감 목록 조회: 메뉴/검색/페이지 변경 시 서버에서 다시 받아온다.
    useEffect(() => {
        if (activeId !== 'reviews' || reviewView !== 'list') return

        let canceled = false

        async function loadReviews() {
            setReviewLoading(true)
            setNotice('')

            try {
                const response = await getCareerReviews({
                    page: reviewPage,
                    page_size: REVIEW_PAGE_SIZE,
                    q: keyword || undefined,
                    subcategory_code: REVIEW_MENU_CODES[activeMenu] || undefined,
                })

                if (!canceled) {
                    setServerReviews(response.items.map(toReviewPost))
                    setReviewTotal(response.total)
                }
            } catch (error) {
                if (!canceled) {
                    setServerReviews([])
                    setReviewTotal(0)
                    setNotice(`후기 목록 조회 실패: ${error.message}`)
                }
            } finally {
                if (!canceled) setReviewLoading(false)
            }
        }

        loadReviews()
        return () => { canceled = true }
    }, [activeId, reviewView, activeMenu, keyword, reviewPage, reviewRefresh])

    // 커리어 톡톡 목록 조회: 필터, 검색, 페이지 변경 시 서버 재요청
    useEffect(() => {
        if (activeId !== 'talk' || talkView !== 'list') return

        let canceled = false

        async function loadTalks() {
            setTalkLoading(true)

            try {
                const response = await getCareerTalks({
                    page: talkPage,
                    page_size: TALK_PAGE_SIZE,
                    q: keyword || undefined,
                    subcategory_code: TALK_MENU_CODES[activeMenu] || undefined,
                })

                if (!canceled) {
                    setServerTalks(response.items.map(toTalkPost))
                    setTalkTotal(response.total)
                }
            } catch (error) {
                if (!canceled) {
                    setServerTalks([])
                    setTalkTotal(0)
                    setNotice(`커리어 톡톡 목록 조회 실패: ${error.message}`)
                }
            } finally {
                if (!canceled) setTalkLoading(false)
            }
        }

        loadTalks()
        return () => { canceled = true }
    }, [activeId, talkView, activeMenu, keyword, talkPage, talkRefresh])

    // 현직자 라운지 목록: 검색·하위 메뉴·페이지가 바뀌면 서버에 요청
    useEffect(() => {
        if (activeId !== 'lounge' || loungeView !== 'list') return

        let canceled = false

        async function loadLounges() {
            setLoungeLoading(true)

            try {
                const response = await getCareerLounges({
                    page: loungePage,
                    page_size: LOUNGE_PAGE_SIZE,
                    q: keyword || undefined,
                    subcategory_code: LOUNGE_MENU_CODES[activeMenu] || undefined,
                })

                if (!canceled) {
                    setServerLounges(response.items.map(toLoungePost))
                    setLoungeTotal(response.total)
                }
            } catch (error) {
                if (!canceled) {
                    setServerLounges([])
                    setLoungeTotal(0)
                    setNotice(`현직자 라운지 목록 조회 실패: ${error.message}`)
                }
            } finally {
                if (!canceled) setLoungeLoading(false)
            }
        }

        loadLounges()
        return () => { canceled = true }
    }, [activeId, loungeView, activeMenu, keyword, loungePage, loungeRefresh])

    // 커리어 연구소 목록은 서버에서 검색·필터·페이지 처리를 수행한다.
    useEffect(() => {
        if (activeId !== 'lab' || labView !== 'list') return

        let canceled = false

        async function loadLabs() {
            setLabLoading(true)
            try {
                const response = await getCareerLabs({
                    page: labPage,
                    page_size: LAB_PAGE_SIZE,
                    q: keyword || undefined,
                    subcategory_code: LAB_MENU_CODES[activeMenu] || undefined,
                })
                if (!canceled) {
                    setServerLabs(response.items.map(toLabPost))
                    setLabTotal(response.total)
                }
            } catch (error) {
                if (!canceled) {
                    setServerLabs([])
                    setLabTotal(0)
                    setNotice(`커리어 연구소 목록 조회 실패: ${error.message}`)
                }
            } finally {
                if (!canceled) setLabLoading(false)
            }
        }

        loadLabs()
        return () => { canceled = true }
    }, [activeId, labView, activeMenu, keyword, labPage, labRefresh])

    const posts = useMemo(() => {
        const allPosts = activeId === 'reviews'
            ? serverReviews
            : activeId === 'talk'
                ? serverTalks
                : activeId === 'lounge'
                    ? serverLounges
                    : activeId === 'lab'
                        ? serverLabs
                        : []

        // 서버 연동 게시판은 서버에서 필터·검색·페이지 처리를 한다.
        if (['reviews', 'talk', 'lounge', 'lab'].includes(activeId)) return allPosts

        const filtered = allPosts.filter((item) => (
            (activeMenu === '전체' || item.menu === activeMenu) &&
            `${item.title} ${item.summary} ${item.author} ${item.menu}`
                .toLowerCase()
                .includes(keyword.trim().toLowerCase())
        ))

        if (sort === 'oldest') return [...filtered].reverse()
        if (sort === 'title') {
            return [...filtered].sort((a, b) => a.title.localeCompare(b.title, 'ko'))
        }
        return filtered
    }, [activeId, activeMenu, keyword, sort, serverReviews, serverTalks, serverLounges, serverLabs])

    function selectCategory(id) {
        if (reviewMutationLock.current || talkMutationLock.current || loungeMutationLock.current || labMutationLock.current) return
        reviewDetailRequest.current += 1
        talkDetailRequest.current += 1
        loungeDetailRequest.current += 1
        labDetailRequest.current += 1
        setReviewBusy(false)
        setTalkBusy(false)
        setLoungeBusy(false)
        setLabBusy(false)
        setReviewPage(1)
        setTalkPage(1)
        setLoungePage(1)
        setLabPage(1)
        setActiveId(id)
        setActiveMenu('전체')
        setInput('')
        setKeyword('')
        setSort('latest')
        setReviewView('list')
        setSelectedReview(null)
        setEditingReview(false)
        setTalkView('list')
        setSelectedTalk(null)
        setEditingTalk(false)
        setLoungeView('list')
        setSelectedLoungePost(null)
        setEditingLoungePost(false)
        setLabView('list')
        setSelectedLabPost(null)
        setEditingLabPost(false)
        setNotice('')
    }

    function openNewReview() {
        if (reviewMutationLock.current) return
        setSelectedReview(null)
        setEditingReview(false)
        setNotice('')
        setReviewView('editor')
    }

    async function openReview(item) {
        if (reviewMutationLock.current || reviewBusy) return

        const requestId = ++reviewDetailRequest.current
        setReviewBusy(true)
        setNotice('')

        try {
            const detail = await getCareerReview(item.id)
            if (requestId !== reviewDetailRequest.current) return

            setSelectedReview(toReviewPost(detail))
            setEditingReview(false)
            setReviewView('detail')
        } catch (error) {
            if (requestId === reviewDetailRequest.current) {
                setNotice(`후기 조회 실패: ${error.message}`)
            }
        } finally {
            if (requestId === reviewDetailRequest.current) setReviewBusy(false)
        }
    }

    function backToReviews() {
        if (reviewMutationLock.current) return
        reviewDetailRequest.current += 1
        setReviewBusy(false)
        setReviewView('list')
        setEditingReview(false)
        setSelectedReview(null)
    }

    async function saveReview(form) {
        // 동일 화면에서 저장 버튼을 연속으로 눌러도 요청을 한 번만 보낸다.
        if (reviewMutationLock.current) return null
        reviewMutationLock.current = true
        setReviewBusy(true)
        setNotice('')

        try {
            const payload = toReviewPayload(form)
            const saved = editingReview && selectedReview
                ? await updateCareerReview(selectedReview.id, payload)
                : await createCareerReview(payload)

            const converted = toReviewPost(saved)
            setSelectedReview(converted)
            setEditingReview(false)
            setReviewPage(1)
            setActiveMenu('전체')
            setKeyword('')
            setInput('')
            setReviewView('detail')
            setNotice(editingReview ? '후기를 수정했습니다.' : '후기를 등록했습니다.')
            return saved
        } catch (error) {
            setNotice(`후기 저장 실패: ${error.message}`)
            return null
        } finally {
            reviewMutationLock.current = false
            setReviewBusy(false)
        }
    }

    function editReview() {
        if (reviewMutationLock.current || !selectedReview?.is_owner) return
        setEditingReview(true)
        setNotice('')
        setReviewView('editor')
    }

    async function deleteReview() {
        if (reviewMutationLock.current || !selectedReview?.is_owner) return
        if (!window.confirm('이 후기를 삭제할까요?')) return

        reviewMutationLock.current = true
        setReviewBusy(true)
        setNotice('')

        try {
            await deleteCareerReview(selectedReview.id)
            reviewDetailRequest.current += 1
            setReviewPage(1)
            setSelectedReview(null)
            setEditingReview(false)
            setReviewView('list')
            setReviewRefresh((value) => value + 1)
            setNotice('후기를 삭제했습니다.')
        } catch (error) {
            setNotice(`후기 삭제 실패: ${error.message}`)
        } finally {
            reviewMutationLock.current = false
            setReviewBusy(false)
        }
    }

    // =========================================
    // 커리어 톡톡: 작성·상세·수정·삭제
    // =========================================

    function openNewTalk() {
        if (talkMutationLock.current) return
        setSelectedTalk(null)
        setEditingTalk(false)
        setNotice('')
        setTalkView('editor')
    }

    async function openTalk(item) {
        if (talkMutationLock.current || talkBusy) return

        const requestId = ++talkDetailRequest.current
        setTalkBusy(true)
        setNotice('')

        try {
            const detail = await getCareerTalk(item.id)
            if (requestId !== talkDetailRequest.current) return

            setSelectedTalk(toTalkPost(detail))
            setEditingTalk(false)
            setTalkView('detail')
        } catch (error) {
            if (requestId === talkDetailRequest.current) {
                setNotice(`게시글 조회 실패: ${error.message}`)
            }
        } finally {
            if (requestId === talkDetailRequest.current) setTalkBusy(false)
        }
    }

    function backToTalks() {
        if (talkMutationLock.current) return
        talkDetailRequest.current += 1
        setTalkBusy(false)
        setTalkView('list')
        setSelectedTalk(null)
        setEditingTalk(false)
    }

    async function saveTalk(form) {
        if (talkMutationLock.current) return null
        talkMutationLock.current = true
        setTalkBusy(true)
        setNotice('')

        try {
            const payload = toTalkPayload(form)
            const saved = editingTalk && selectedTalk
                ? await updateCareerTalk(selectedTalk.id, payload)
                : await createCareerTalk(payload)

            setSelectedTalk(toTalkPost(saved))
            setEditingTalk(false)
            setTalkPage(1)
            setActiveMenu('전체')
            setInput('')
            setKeyword('')
            setTalkView('detail')
            setNotice(editingTalk ? '게시글을 수정했습니다.' : '게시글을 등록했습니다.')
            return saved
        } catch (error) {
            setNotice(`게시글 저장 실패: ${error.message}`)
            return null
        } finally {
            talkMutationLock.current = false
            setTalkBusy(false)
        }
    }

    function editTalk() {
        if (talkMutationLock.current || !selectedTalk?.is_owner) return
        setEditingTalk(true)
        setNotice('')
        setTalkView('editor')
    }

    async function deleteTalk() {
        if (talkMutationLock.current || !selectedTalk?.is_owner) return
        if (!window.confirm('이 게시글을 삭제할까요?')) return

        talkMutationLock.current = true
        setTalkBusy(true)
        setNotice('')

        try {
            await deleteCareerTalk(selectedTalk.id)
            talkDetailRequest.current += 1
            setTalkPage(1)
            setSelectedTalk(null)
            setEditingTalk(false)
            setTalkView('list')
            setTalkRefresh((value) => value + 1)
            setNotice('게시글을 삭제했습니다.')
        } catch (error) {
            setNotice(`게시글 삭제 실패: ${error.message}`)
        } finally {
            talkMutationLock.current = false
            setTalkBusy(false)
        }
    }

    // =========================================
    // 현직자 라운지: 작성·상세·수정·삭제
    // =========================================

    function openNewLoungePost() {
        if (loungeMutationLock.current) return
        setSelectedLoungePost(null)
        setEditingLoungePost(false)
        setNotice('')
        setLoungeView('editor')
    }

    async function openLoungePost(item) {
        if (loungeMutationLock.current || loungeBusy) return

        const requestId = ++loungeDetailRequest.current
        setLoungeBusy(true)
        setNotice('')

        try {
            const detail = await getCareerLounge(item.id)
            if (requestId !== loungeDetailRequest.current) return

            setSelectedLoungePost(toLoungePost(detail))
            setEditingLoungePost(false)
            setLoungeView('detail')
        } catch (error) {
            if (requestId === loungeDetailRequest.current) {
                setNotice(`게시글 조회 실패: ${error.message}`)
            }
        } finally {
            if (requestId === loungeDetailRequest.current) setLoungeBusy(false)
        }
    }

    function backToLounge() {
        if (loungeMutationLock.current) return
        loungeDetailRequest.current += 1
        setLoungeBusy(false)
        setLoungeView('list')
        setSelectedLoungePost(null)
        setEditingLoungePost(false)
    }

    async function saveLoungePost(form) {
        if (loungeMutationLock.current) return null
        loungeMutationLock.current = true
        setLoungeBusy(true)
        setNotice('')

        try {
            const payload = toLoungePayload(form)
            const saved = editingLoungePost && selectedLoungePost
                ? await updateCareerLounge(selectedLoungePost.id, payload)
                : await createCareerLounge(payload)

            setSelectedLoungePost(toLoungePost(saved))
            setEditingLoungePost(false)
            setLoungePage(1)
            setActiveMenu('전체')
            setInput('')
            setKeyword('')
            setLoungeView('detail')
            setNotice(editingLoungePost ? '게시글을 수정했습니다.' : '게시글을 등록했습니다.')
            return saved
        } catch (error) {
            setNotice(`게시글 저장 실패: ${error.message}`)
            return null
        } finally {
            loungeMutationLock.current = false
            setLoungeBusy(false)
        }
    }

    function editLoungePost() {
        if (loungeMutationLock.current || !selectedLoungePost?.is_owner) return
        setEditingLoungePost(true)
        setNotice('')
        setLoungeView('editor')
    }

    async function deleteLoungePost() {
        if (loungeMutationLock.current || !selectedLoungePost?.is_owner) return
        if (!window.confirm('이 게시글을 삭제할까요?')) return

        loungeMutationLock.current = true
        setLoungeBusy(true)
        setNotice('')

        try {
            await deleteCareerLounge(selectedLoungePost.id)
            loungeDetailRequest.current += 1
            setLoungePage(1)
            setSelectedLoungePost(null)
            setEditingLoungePost(false)
            setLoungeView('list')
            setLoungeRefresh((value) => value + 1)
            setNotice('게시글을 삭제했습니다.')
        } catch (error) {
            setNotice(`게시글 삭제 실패: ${error.message}`)
        } finally {
            loungeMutationLock.current = false
            setLoungeBusy(false)
        }
    }

    // =========================================
    // 커리어 연구소: 서버 CRUD · 해결 상태 · 투표
    // =========================================

    function openNewLabPost() {
        if (labMutationLock.current) return
        setSelectedLabPost(null)
        setEditingLabPost(false)
        setNotice('')
        setLabView('editor')
    }

    async function openLabPost(item) {
        if (labMutationLock.current || labBusy) return

        const requestId = ++labDetailRequest.current
        setLabBusy(true)
        setNotice('')

        try {
            const detail = await getCareerLab(item.id)
            if (requestId !== labDetailRequest.current) return
            setSelectedLabPost(toLabPost(detail))
            setEditingLabPost(false)
            setLabView('detail')
        } catch (error) {
            if (requestId === labDetailRequest.current) {
                setNotice(`게시글 조회 실패: ${error.message}`)
            }
        } finally {
            if (requestId === labDetailRequest.current) setLabBusy(false)
        }
    }

    function backToLab() {
        if (labMutationLock.current) return
        labDetailRequest.current += 1
        setLabBusy(false)
        setLabView('list')
        setSelectedLabPost(null)
        setEditingLabPost(false)
    }

    async function saveLabPost(form) {
        if (labMutationLock.current) return null
        labMutationLock.current = true
        setLabBusy(true)
        setNotice('')

        try {
            const payload = toLabPayload(form)
            const saved = editingLabPost && selectedLabPost
                ? await updateCareerLab(selectedLabPost.id, payload)
                : await createCareerLab({
                    ...payload,
                    post_type: form.post_type,
                    poll_options: form.poll_options || [],
                })

            setSelectedLabPost(toLabPost(saved))
            setEditingLabPost(false)
            setLabPage(1)
            setActiveMenu('전체')
            setInput('')
            setKeyword('')
            setLabView('detail')
            setLabRefresh((value) => value + 1)
            setNotice(editingLabPost ? '게시글을 수정했습니다.' : '게시글을 등록했습니다.')
            return saved
        } catch (error) {
            setNotice(`게시글 저장 실패: ${error.message}`)
            return null
        } finally {
            labMutationLock.current = false
            setLabBusy(false)
        }
    }

    function editLabPost() {
        if (labMutationLock.current || !selectedLabPost?.is_owner) return
        setEditingLabPost(true)
        setNotice('')
        setLabView('editor')
    }

    async function deleteLabPost() {
        if (labMutationLock.current || !selectedLabPost?.is_owner) return
        if (!window.confirm('이 게시글을 삭제할까요?')) return

        labMutationLock.current = true
        setLabBusy(true)
        setNotice('')

        try {
            await deleteCareerLab(selectedLabPost.id)
            labDetailRequest.current += 1
            setLabPage(1)
            setSelectedLabPost(null)
            setEditingLabPost(false)
            setLabView('list')
            setLabRefresh((value) => value + 1)
            setNotice('게시글을 삭제했습니다.')
        } catch (error) {
            setNotice(`게시글 삭제 실패: ${error.message}`)
        } finally {
            labMutationLock.current = false
            setLabBusy(false)
        }
    }

    async function toggleLabResolved() {
        if (labMutationLock.current || !selectedLabPost?.is_owner) return
        if (selectedLabPost.post_type !== 'QUESTION') return
        labMutationLock.current = true
        setLabBusy(true)
        setNotice('')

        try {
            const saved = await resolveCareerLab(selectedLabPost.id, !selectedLabPost.is_resolved)
            setSelectedLabPost(toLabPost(saved))
            setLabRefresh((value) => value + 1)
            setNotice('질문 해결 상태를 변경했습니다.')
        } catch (error) {
            setNotice(`질문 상태 변경 실패: ${error.message}`)
        } finally {
            labMutationLock.current = false
            setLabBusy(false)
        }
    }

    async function voteLabPoll(optionId) {
        if (labMutationLock.current || selectedLabPost?.post_type !== 'DISCUSSION') return
        if (selectedLabPost.my_vote_option_id != null) return
        labMutationLock.current = true
        setLabBusy(true)
        setNotice('')

        try {
            const saved = await voteCareerLab(selectedLabPost.id, optionId)
            setSelectedLabPost(toLabPost(saved))
            setNotice('투표가 반영되었습니다.')
        } catch (error) {
            setNotice(`투표 실패: ${error.message}`)
            // 중복 투표 등으로 서버 상태가 달라진 경우 최신 데이터 다시 조회
            try {
                const latest = await getCareerLab(selectedLabPost.id)
                setSelectedLabPost(toLabPost(latest))
            } catch {
                // 원래 API 오류 메시지는 그대로 표시한다.
            }
        } finally {
            labMutationLock.current = false
            setLabBusy(false)
        }
    }

    return (
        <main className="career-page">
            <div className="career-container">
                <div className="career-page-heading">
                    <h1>취업</h1>
                    <p>취업 준비부터 실무 이야기까지, 함께 나누는 커리어 공간</p>
                </div>

                {/* 왼쪽 사이드바 대신 상단 6개 카테고리를 유지합니다. */}
                <nav className="career-category-grid" aria-label="취업 카테고리">
                    {CATEGORIES.map((item) => (
                        <button
                            key={item.id}
                            type="button"
                            className={`career-category-card ${activeId === item.id ? 'active' : ''}`}
                            onClick={() => selectCategory(item.id)}
                            aria-current={activeId === item.id ? 'page' : undefined}
                        >
                            <span className="career-category-icon">
                                <CategoryIcon type={item.icon} />
                            </span>
                            <span className="career-category-text">
                                <strong>{item.name}</strong>
                                <small>{item.description}</small>
                            </span>
                        </button>
                    ))}
                </nav>

                <section className="career-board" aria-label={`${active.name} 콘텐츠`}>
                    <div className="career-section-head">
                        <div>
                            <span className="career-eyebrow">{activeId === 'briefing' ? 'CAREER NEWS' : activeId === 'insights' ? 'CAREER DATA' : 'CAREER COMMUNITY'}</span>
                            <h2>{active.name}</h2>
                        </div>

                        {activeId !== 'insights' && activeId !== 'briefing' && (
                            <button
                                type="button"
                                className="career-write-btn"
                                disabled={reviewBusy || talkBusy || loungeBusy || labBusy || (activeId !== 'reviews' && activeId !== 'talk' && activeId !== 'lounge' && activeId !== 'lab')}
                                title={activeId !== 'reviews' && activeId !== 'talk' && activeId !== 'lounge' && activeId !== 'lab'
                                    ? '추후 작성 기능을 연결합니다'
                                    : undefined}
                                onClick={() => {
                                    if (activeId === 'reviews') {
                                        if (reviewView === 'list') openNewReview()
                                        else backToReviews()
                                    } else if (activeId === 'talk') {
                                        if (talkView === 'list') openNewTalk()
                                        else backToTalks()
                                    } else if (activeId === 'lounge') {
                                        if (loungeView === 'list') openNewLoungePost()
                                        else backToLounge()
                                    } else if (activeId === 'lab') {
                                        if (labView === 'list') openNewLabPost()
                                        else backToLab()
                                    }
                                }}
                            >
                                {(activeId === 'reviews' && reviewView !== 'list') ||
                                 (activeId === 'talk' && talkView !== 'list') ||
                                 (activeId === 'lounge' && loungeView !== 'list') ||
                                 (activeId === 'lab' && labView !== 'list')
                                    ? '← 목록으로'
                                    : '+ 글쓰기'}
                            </button>
                        )}
                    </div>

                    {(activeId === 'reviews' || activeId === 'talk' || activeId === 'lounge' || activeId === 'lab') && notice && (
                        <p
                            className={activeId === 'reviews'
                                ? 'career-review-notice'
                                : activeId === 'lounge'
                                    ? 'career-lounge-notice'
                                    : activeId === 'lab'
                                        ? 'career-lab-notice'
                                        : 'career-talk-notice'}
                            role="status"
                        >
                            {notice}
                        </p>
                    )}

                    {activeId === 'reviews' && reviewView === 'editor' ? (
                        <div className="career-review-editor">
                            <h3>{editingReview ? '후기 수정' : '후기 작성'}</h3>
                            <p className="career-review-help">
                                작성한 후기는 PLAYMATE 서버에 저장됩니다. 본문은 500자 이상 입력해 주세요.
                            </p>
                            <CareerReviewForm
                                key={editingReview ? `edit-${selectedReview.id}` : 'new'}
                                initial={editingReview ? selectedReview : null}
                                busy={reviewBusy}
                                onCancel={() => {
                                    if (editingReview) {
                                        setReviewView('detail')
                                        setEditingReview(false)
                                    } else {
                                        backToReviews()
                                    }
                                }}
                                onSubmit={saveReview}
                            />
                        </div>
                    ) : activeId === 'reviews' && reviewView === 'detail' ? (
                        <div>
                            <CareerReviewDetailPage
                                review={selectedReview}
                                onBack={backToReviews}
                                onEdit={editReview}
                                onDelete={deleteReview}
                            />
                        </div>
                    ) : activeId === 'talk' && talkView === 'editor' ? (
                        <div className="career-talk-editor">
                            <h3>{editingTalk ? '커리어 톡톡 글 수정' : '커리어 톡톡 글쓰기'}</h3>
                            <p className="career-talk-help">
                                자유롭게 고민과 경험을 나누는 공간입니다. 작성한 글은 서버에 저장됩니다.
                            </p>
                            <CareerTalkForm
                                key={editingTalk ? `talk-edit-${selectedTalk.id}` : 'talk-new'}
                                initial={editingTalk ? selectedTalk : null}
                                defaultMenu={activeMenu === '전체' ? '' : activeMenu}
                                busy={talkBusy}
                                onCancel={() => {
                                    if (editingTalk) {
                                        setTalkView('detail')
                                        setEditingTalk(false)
                                    } else {
                                        backToTalks()
                                    }
                                }}
                                onSubmit={saveTalk}
                            />
                        </div>
                    ) : activeId === 'talk' && talkView === 'detail' ? (
                        <CareerTalkDetailPage
                            talk={selectedTalk}
                            onBack={backToTalks}
                            onEdit={editTalk}
                            onDelete={deleteTalk}
                            busy={talkBusy}
                        />
                    ) : activeId === 'lounge' && loungeView === 'editor' ? (
                        <div className="career-lounge-editor">
                            <h3>{editingLoungePost ? '현직자 라운지 글 수정' : '현직자 라운지 글쓰기'}</h3>
                            <p className="career-lounge-help">
                                실무 경험과 직무 질문을 나눠요. 작성한 글은 서버에 저장됩니다.
                            </p>
                            <CareerLoungeForm
                                key={editingLoungePost ? `lounge-edit-${selectedLoungePost.id}` : 'lounge-new'}
                                initial={editingLoungePost ? selectedLoungePost : null}
                                defaultMenu={activeMenu === '전체' ? '' : activeMenu}
                                busy={loungeBusy}
                                onCancel={() => {
                                    if (editingLoungePost) {
                                        setLoungeView('detail')
                                        setEditingLoungePost(false)
                                    } else {
                                        backToLounge()
                                    }
                                }}
                                onSubmit={saveLoungePost}
                            />
                        </div>
                    ) : activeId === 'lounge' && loungeView === 'detail' ? (
                        <CareerLoungeDetailPage
                            post={selectedLoungePost}
                            onBack={backToLounge}
                            onEdit={editLoungePost}
                            onDelete={deleteLoungePost}
                            busy={loungeBusy}
                        />
                    ) : activeId === 'lab' && labView === 'editor' ? (
                        <div className="career-lab-editor">
                            <h3>{editingLabPost ? '커리어 연구소 글 수정' : '커리어 연구소 글쓰기'}</h3>
                            <p className="career-lab-help">
                                질문·토론 게시글이 서버에 저장됩니다. 피드백 요청은 질문 유형으로 등록해 주세요.
                            </p>
                            <CareerLabForm
                                key={editingLabPost ? `lab-edit-${selectedLabPost.id}` : 'lab-new'}
                                initial={editingLabPost ? selectedLabPost : null}
                                defaultMenu={activeMenu === '전체' ? '' : activeMenu}
                                busy={labBusy}
                                onCancel={() => {
                                    if (editingLabPost) {
                                        setLabView('detail')
                                        setEditingLabPost(false)
                                    } else {
                                        backToLab()
                                    }
                                }}
                                onSubmit={saveLabPost}
                            />
                        </div>
                    ) : activeId === 'lab' && labView === 'detail' ? (
                        <CareerLabDetailPage
                            post={selectedLabPost}
                            onBack={backToLab}
                            onEdit={editLabPost}
                            onDelete={deleteLabPost}
                            onVote={voteLabPoll}
                            onToggleResolved={toggleLabResolved}
                            busy={labBusy}
                        />
                    ) : activeId === 'briefing' ? (
                        <CareerBriefing menus={active.menus} />
                    ) : activeId === 'insights' ? (
                        <CareerInsights />
                    ) : (
                        <>
                            <div className="career-subnav" aria-label={`${active.name} 하위 게시판`}>
                                {active.menus.map((menu) => (
                                    <button
                                        key={menu}
                                        type="button"
                                        className={activeMenu === menu ? 'active' : ''}
                                        onClick={() => {
                                            setActiveMenu(menu)
                                            setReviewPage(1)
                                            setTalkPage(1)
                                            setLoungePage(1)
                                            setLabPage(1)
                                            setInput('')
                                            setKeyword('')
                                        }}
                                        aria-pressed={activeMenu === menu}
                                    >
                                        {menu}
                                    </button>
                                ))}
                            </div>

                            <div className="career-board-toolbar">
                                <form
                                    className="career-search"
                                    onSubmit={(event) => {
                                        event.preventDefault()
                                        setReviewPage(1)
                                        setTalkPage(1)
                                        setLoungePage(1)
                                        setLabPage(1)
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
                                        placeholder="게시글 검색"
                                        aria-label="게시글 검색"
                                    />
                                    <button type="submit">검색</button>
                                </form>
                                <select
                                    value={sort}
                                    onChange={(event) => setSort(event.target.value)}
                                    aria-label="게시글 정렬"
                                >
                                    <option value="latest">최신순</option>
                                    {activeId !== 'reviews' && activeId !== 'talk' && activeId !== 'lounge' && activeId !== 'lab' && <option value="oldest">오래된순</option>}
                                    {activeId !== 'reviews' && activeId !== 'talk' && activeId !== 'lounge' && activeId !== 'lab' && <option value="title">제목순</option>}
                                </select>
                            </div>

                            <p className="career-sample-caption">
                                {activeId === 'reviews'
                                    ? reviewLoading
                                        ? '후기를 불러오는 중입니다.'
                                        : `서버에 저장된 후기 ${reviewTotal}개 · 최신순`
                                    : activeId === 'talk'
                                        ? talkLoading
                                            ? '게시글을 불러오는 중입니다.'
                                            : `서버에 저장된 게시글 ${talkTotal}개 · 최신순`
                                        : activeId === 'lounge'
                                            ? loungeLoading
                                                ? '게시글을 불러오는 중입니다.'
                                                : `서버에 저장된 게시글 ${loungeTotal}개 · 최신순`
                                            : activeId === 'lab'
                                                ? labLoading
                                                    ? '게시글을 불러오는 중입니다.'
                                                    : `서버에 저장된 게시글 ${labTotal}개 · 최신순`
                                                : ''}
                            </p>

                            <div className="career-post-list" aria-live="polite">
                                {(activeId === 'reviews' && reviewLoading) || (activeId === 'talk' && talkLoading) || (activeId === 'lounge' && loungeLoading) || (activeId === 'lab' && labLoading) ? (
                                    <div className="career-empty">게시글을 불러오는 중입니다.</div>
                                ) : posts.length ? posts.map((item) => (
                                    <article className="career-post" key={item.id}>
                                        {/* 하위 카테고리 + 커리어 연구소 질문 상태/토론 유형 */}
                                        <div className="career-post-labels">
                                            <span className="career-post-tag">{item.menu}</span>

                                            {activeId === 'lab' && item.post_type === 'QUESTION' && (
                                                <span className={`career-lab-state ${item.is_resolved ? 'is-complete' : 'is-open'}`}>
                                                    {item.is_resolved ? '✓ 해결 완료' : '○ 미해결'}
                                                </span>
                                            )}

                                            {activeId === 'lab' && item.post_type === 'DISCUSSION' && (
                                                <span className="career-lab-state is-discussion">
                                                    ◇ 토론
                                                </span>
                                            )}
                                        </div>
                                        {activeId === 'reviews' || activeId === 'talk' || activeId === 'lounge' || activeId === 'lab' ? (
                                            <button
                                                type="button"
                                                className="career-review-post-open"
                                                onClick={() => activeId === 'reviews'
                                                    ? openReview(item)
                                                    : activeId === 'talk'
                                                        ? openTalk(item)
                                                        : activeId === 'lounge'
                                                            ? openLoungePost(item)
                                                            : openLabPost(item)}
                                                aria-label={`${item.title} 상세 보기`}
                                            >
                                                <h3>{item.title}</h3>
                                                <p>{item.summary}</p>
                                            </button>
                                        ) : (
                                            <>
                                                <h3>{item.title}</h3>
                                                <p>{item.summary}</p>
                                            </>
                                        )}
                                        <div className="career-post-footer">
                                            <strong>{item.author}</strong>
                                            <span>{item.date}</span>
                                            {!item.isServer && <span>♡ {item.likes}</span>}
                                            {!item.isServer && <span>♧ {item.comments}</span>}
                                        </div>
                                    </article>
                                )) : (
                                    <div className="career-empty">
                                        <strong>표시할 게시글이 없어요.</strong>
                                        <span>하위 메뉴나 검색어를 변경해 주세요.</span>
                                    </div>
                                )}
                            </div>

                            {activeId === 'lab' && labTotal > LAB_PAGE_SIZE && (
                                <div className="career-board-toolbar">
                                    <button
                                        type="button"
                                        disabled={labLoading || labPage <= 1}
                                        onClick={() => setLabPage((page) => page - 1)}
                                    >
                                        이전
                                    </button>
                                    <span>
                                        {labPage} / {Math.ceil(labTotal / LAB_PAGE_SIZE)} 페이지
                                    </span>
                                    <button
                                        type="button"
                                        disabled={labLoading || labPage >= Math.ceil(labTotal / LAB_PAGE_SIZE)}
                                        onClick={() => setLabPage((page) => page + 1)}
                                    >
                                        다음
                                    </button>
                                </div>
                            )}

                            {activeId === 'lounge' && loungeTotal > LOUNGE_PAGE_SIZE && (
                                <div className="career-board-toolbar">
                                    <button
                                        type="button"
                                        disabled={loungeLoading || loungePage <= 1}
                                        onClick={() => setLoungePage((page) => page - 1)}
                                    >
                                        이전
                                    </button>
                                    <span>
                                        {loungePage} / {Math.ceil(loungeTotal / LOUNGE_PAGE_SIZE)} 페이지
                                    </span>
                                    <button
                                        type="button"
                                        disabled={loungeLoading || loungePage >= Math.ceil(loungeTotal / LOUNGE_PAGE_SIZE)}
                                        onClick={() => setLoungePage((page) => page + 1)}
                                    >
                                        다음
                                    </button>
                                </div>
                            )}

                            {activeId === 'talk' && talkTotal > TALK_PAGE_SIZE && (
                                <div className="career-board-toolbar">
                                    <button
                                        type="button"
                                        disabled={talkLoading || talkPage <= 1}
                                        onClick={() => setTalkPage((page) => page - 1)}
                                    >
                                        이전
                                    </button>
                                    <span>
                                        {talkPage} / {Math.ceil(talkTotal / TALK_PAGE_SIZE)} 페이지
                                    </span>
                                    <button
                                        type="button"
                                        disabled={talkLoading || talkPage >= Math.ceil(talkTotal / TALK_PAGE_SIZE)}
                                        onClick={() => setTalkPage((page) => page + 1)}
                                    >
                                        다음
                                    </button>
                                </div>
                            )}

                            {activeId === 'reviews' && reviewTotal > REVIEW_PAGE_SIZE && (
                                <div className="career-board-toolbar">
                                    <button
                                        type="button"
                                        disabled={reviewLoading || reviewPage <= 1}
                                        onClick={() => setReviewPage((page) => page - 1)}
                                    >
                                        이전
                                    </button>
                                    <span>
                                        {reviewPage} / {Math.ceil(reviewTotal / REVIEW_PAGE_SIZE)} 페이지
                                    </span>
                                    <button
                                        type="button"
                                        disabled={reviewLoading || reviewPage >= Math.ceil(reviewTotal / REVIEW_PAGE_SIZE)}
                                        onClick={() => setReviewPage((page) => page + 1)}
                                    >
                                        다음
                                    </button>
                                </div>
                            )}
                        </>
                    )}
                </section>
            </div>
        </main>
    )
}
