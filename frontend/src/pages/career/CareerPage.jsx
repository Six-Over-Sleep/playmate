import { useMemo, useRef, useState } from 'react'
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

// API 연결 전의 화면 테스트용 예시 데이터이며 실제 게시글이 아닙니다.
const SAMPLE_POSTS = {
    reviews: [
        {
            id: 1, menu: '서류 도감', title: '[예시] 신입 백엔드 서류 지원 후기',
            summary: '서류 준비 과정과 포트폴리오를 정리하며 느낀 점을 공유해요.',
            author: '익명', date: '2026. 10. 22.', comments: 2, likes: 6,
        },
        {
            id: 2, menu: '면접 도감', title: '[예시] 데이터 분석 직무 면접 후기',
            summary: '면접 진행 방식과 준비했던 내용을 정리했어요.',
            author: '익명', date: '2026. 10. 21.', comments: 1, likes: 4,
        },
    ],
    talk: [
        {
            id: 3, menu: '취업 고민', title: '[예시] 첫 취업 준비, 어디서부터 시작할까요?',
            summary: '포트폴리오부터 만들지, 코딩 테스트를 먼저 준비할지 고민이에요.',
            author: '플레이메이트', date: '2026. 10. 22.', comments: 4, likes: 8,
        },
        {
            id: 4, menu: '진로 고민', title: '[예시] 백엔드와 데이터 엔지니어 중 고민입니다',
            summary: '관심 있는 두 직무의 실무 차이가 궁금해요.',
            author: '익명', date: '2026. 10. 21.', comments: 2, likes: 3,
        },
        {
            id: 5, menu: '취준 일상', title: '[예시] 이번 주 공부 목표 공유해요',
            summary: '함께 공부하면서 동기부여 받아요!',
            author: '플레이메이트', date: '2026. 10. 20.', comments: 3, likes: 5,
        },
    ],
    lounge: [
        {
            id: 6, menu: '현직자의 하루', title: '[예시] 신입 개발자의 하루',
            summary: '업무 흐름과 협업 방식을 간단히 소개합니다.',
            author: '졸업생', date: '2026. 10. 22.', comments: 1, likes: 5,
        },
        {
            id: 7, menu: '직무 Q&A', title: '[예시] 현직자에게 코드 리뷰 문화를 물어보세요',
            summary: '실무에서 궁금했던 점을 질문해 보세요.',
            author: '현직자', date: '2026. 10. 21.', comments: 2, likes: 3,
        },
    ],
    lab: [
        {
            id: 8, menu: '포트폴리오 피드백', title: '[예시] 백엔드 포트폴리오 피드백 부탁드립니다',
            summary: '프로젝트 소개와 기술 선택을 개선하고 싶어요.',
            author: '플레이메이트', date: '2026. 10. 22.', comments: 2, likes: 3,
        },
        {
            id: 9, menu: '기술면접 스터디', title: '[예시] 기술면접 스터디 같이 할 분?',
            summary: 'CS 기초부터 차근차근 함께 공부해요.',
            author: '플레이메이트', date: '2026. 10. 21.', comments: 1, likes: 4,
        },
    ],

}

const REVIEW_STAGE_MENU = {
    DOCUMENT: '서류 도감',
    CODING_TEST: '코테·과제 도감',
    ASSIGNMENT: '코테·과제 도감',
    INTERVIEW: '면접 도감',
    FINAL: '최종 결과',
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
    const [activeId, setActiveId] = useState('talk')
    const [activeMenu, setActiveMenu] = useState('전체')
    const [input, setInput] = useState('')
    const [keyword, setKeyword] = useState('')
    const [sort, setSort] = useState('latest')

    // 취준 도감만 우선 프론트엔드 임시 CRUD를 지원합니다.
    const [draftReviews, setDraftReviews] = useState([])
    const [reviewView, setReviewView] = useState('list')
    const [selectedReview, setSelectedReview] = useState(null)
    const [editingReview, setEditingReview] = useState(false)
    const [notice, setNotice] = useState('')
    const nextReviewId = useRef(1000)

    // 커리어 톡톡도 서버 연결 전에는 브라우저 메모리에서만 작성/수정/삭제합니다.
    const [draftTalks, setDraftTalks] = useState([])
    const [talkView, setTalkView] = useState('list')
    const [selectedTalk, setSelectedTalk] = useState(null)
    const [editingTalk, setEditingTalk] = useState(false)
    const nextTalkId = useRef(2000)

    // 현직자 라운지는 화면 테스트용 임시 글만 작성/수정/삭제합니다.
    const [draftLoungePosts, setDraftLoungePosts] = useState([])
    const [loungeView, setLoungeView] = useState('list')
    const [selectedLoungePost, setSelectedLoungePost] = useState(null)
    const [editingLoungePost, setEditingLoungePost] = useState(false)
    const nextLoungeId = useRef(3000)

    // 커리어 연구소: 프론트엔드에서만 질문·토론·피드백 글을 관리합니다.
    const [draftLabPosts, setDraftLabPosts] = useState([])
    const [labView, setLabView] = useState('list')
    const [selectedLabPost, setSelectedLabPost] = useState(null)
    const [editingLabPost, setEditingLabPost] = useState(false)
    const nextLabId = useRef(4000)

    const active = CATEGORIES.find((item) => item.id === activeId)

    const posts = useMemo(() => {
        const allPosts = activeId === 'reviews'
            ? [...draftReviews, ...SAMPLE_POSTS.reviews]
            : activeId === 'talk'
                ? [...draftTalks, ...SAMPLE_POSTS.talk]
                : activeId === 'lounge'
                    ? [...draftLoungePosts, ...SAMPLE_POSTS.lounge]
                    : activeId === 'lab'
                        ? [...draftLabPosts, ...SAMPLE_POSTS.lab]
                        : (SAMPLE_POSTS[activeId] || [])

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
    }, [activeId, activeMenu, keyword, sort, draftReviews, draftTalks, draftLoungePosts, draftLabPosts])

    function selectCategory(id) {
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
        setSelectedReview(null)
        setEditingReview(false)
        setNotice('')
        setReviewView('editor')
    }

    function openReview(item) {
        setSelectedReview(item)
        setEditingReview(false)
        setNotice('')
        setReviewView('detail')
    }

    function backToReviews() {
        setReviewView('list')
        setEditingReview(false)
        setSelectedReview(null)
    }

    function saveReview(payload) {
        // Mock 데이터의 수정은 허용하지 않고, 화면에서 새로 만든 후기만 수정합니다.
        if (editingReview && selectedReview?.isDraft) {
            const updated = {
                ...selectedReview,
                ...payload,
                menu: REVIEW_STAGE_MENU[payload.process_stage],
                summary: payload.body.slice(0, 120),
            }
            setDraftReviews((items) => items.map((item) => (
                item.id === updated.id ? updated : item
            )))
            setSelectedReview(updated)
            setNotice('수정 내용이 화면에 임시 반영됐어요. 서버에 저장된 것은 아닙니다.')
            setReviewView('detail')
            setEditingReview(false)
            return
        }

        nextReviewId.current += 1
        const created = {
            ...payload,
            id: nextReviewId.current,
            menu: REVIEW_STAGE_MENU[payload.process_stage],
            summary: payload.body.slice(0, 120),
            author: '나 (임시)',
            date: new Date().toLocaleDateString('ko-KR'),
            comments: 0,
            likes: 0,
            isDraft: true,
        }

        setDraftReviews((items) => [created, ...items])
        setSelectedReview(created)
        setActiveMenu('전체')
        setInput('')
        setKeyword('')
        setReviewView('detail')
        setNotice('후기가 화면에 임시 등록됐어요. 서버에 저장된 것은 아닙니다.')
    }

    function editReview() {
        if (!selectedReview?.isDraft) return
        setEditingReview(true)
        setNotice('')
        setReviewView('editor')
    }

    function deleteReview() {
        if (!selectedReview?.isDraft) return
        if (!window.confirm('임시 후기를 삭제할까요?')) return

        setDraftReviews((items) => items.filter((item) => item.id !== selectedReview.id))
        backToReviews()
        setNotice('임시 후기를 삭제했어요.')
    }

    function openNewTalk() {
        setSelectedTalk(null)
        setEditingTalk(false)
        setNotice('')
        setTalkView('editor')
    }

    function openTalk(item) {
        setSelectedTalk(item)
        setEditingTalk(false)
        setNotice('')
        setTalkView('detail')
    }

    function backToTalks() {
        setTalkView('list')
        setSelectedTalk(null)
        setEditingTalk(false)
    }

    function saveTalk(payload) {
        if (editingTalk && selectedTalk?.isDraft) {
            const updated = {
                ...selectedTalk,
                ...payload,
                summary: payload.body.slice(0, 120),
                author: payload.anonymous ? '익명 (임시)' : '작성자 (임시)',
            }

            setDraftTalks((items) => items.map((item) => (
                item.id === updated.id ? updated : item
            )))
            setSelectedTalk(updated)
            setActiveMenu('전체')
            setInput('')
            setKeyword('')
            setTalkView('detail')
            setEditingTalk(false)
            setNotice('수정 내용이 화면에 임시 반영됐어요. 서버에는 저장되지 않았습니다.')
            return
        }

        nextTalkId.current += 1
        const created = {
            ...payload,
            id: nextTalkId.current,
            summary: payload.body.slice(0, 120),
            author: payload.anonymous ? '익명 (임시)' : '작성자 (임시)',
            date: new Date().toLocaleDateString('ko-KR'),
            comments: 0,
            likes: 0,
            isDraft: true,
        }

        setDraftTalks((items) => [created, ...items])
        setSelectedTalk(created)
        setActiveMenu('전체')
        setInput('')
        setKeyword('')
        setTalkView('detail')
        setNotice('게시글이 화면에 임시 등록됐어요. 서버에는 저장되지 않았습니다.')
    }

    function editTalk() {
        if (!selectedTalk?.isDraft) return
        setEditingTalk(true)
        setNotice('')
        setTalkView('editor')
    }

    function deleteTalk() {
        if (!selectedTalk?.isDraft) return
        if (!window.confirm('임시 게시글을 삭제할까요?')) return

        setDraftTalks((items) => items.filter((item) => item.id !== selectedTalk.id))
        backToTalks()
        setNotice('임시 게시글을 삭제했어요.')
    }


    function openNewLoungePost() {
        setSelectedLoungePost(null)
        setEditingLoungePost(false)
        setNotice('')
        setLoungeView('editor')
    }

    function openLoungePost(item) {
        setSelectedLoungePost(item)
        setEditingLoungePost(false)
        setNotice('')
        setLoungeView('detail')
    }

    function backToLounge() {
        setLoungeView('list')
        setSelectedLoungePost(null)
        setEditingLoungePost(false)
    }

    function saveLoungePost(payload) {
        if (editingLoungePost && selectedLoungePost?.isDraft) {
            const updated = {
                ...selectedLoungePost,
                ...payload,
                summary: payload.body.slice(0, 120),
            }

            setDraftLoungePosts((items) => items.map((item) => (
                item.id === updated.id ? updated : item
            )))
            setSelectedLoungePost(updated)
            setActiveMenu('전체')
            setInput('')
            setKeyword('')
            setLoungeView('detail')
            setEditingLoungePost(false)
            setNotice('수정 내용이 화면에 임시 반영됐어요. 서버에는 저장되지 않았습니다.')
            return
        }

        nextLoungeId.current += 1
        const created = {
            ...payload,
            id: nextLoungeId.current,
            summary: payload.body.slice(0, 120),
            author: '작성자 (임시)',
            date: new Date().toLocaleDateString('ko-KR'),
            comments: 0,
            likes: 0,
            isDraft: true,
        }

        setDraftLoungePosts((items) => [created, ...items])
        setSelectedLoungePost(created)
        setActiveMenu('전체')
        setInput('')
        setKeyword('')
        setLoungeView('detail')
        setNotice('현직자 라운지 글이 화면에 임시 등록됐어요. 서버에는 저장되지 않았습니다.')
    }

    function editLoungePost() {
        if (!selectedLoungePost?.isDraft) return
        setEditingLoungePost(true)
        setNotice('')
        setLoungeView('editor')
    }

    function deleteLoungePost() {
        if (!selectedLoungePost?.isDraft) return
        if (!window.confirm('임시 게시글을 삭제할까요?')) return

        setDraftLoungePosts((items) => items.filter((item) => item.id !== selectedLoungePost.id))
        backToLounge()
        setNotice('임시 게시글을 삭제했어요.')
    }

    function openNewLabPost() {
        setSelectedLabPost(null)
        setEditingLabPost(false)
        setNotice('')
        setLabView('editor')
    }

    function openLabPost(item) {
        setSelectedLabPost(item)
        setEditingLabPost(false)
        setNotice('')
        setLabView('detail')
    }

    function backToLab() {
        setLabView('list')
        setSelectedLabPost(null)
        setEditingLabPost(false)
    }

    function saveLabPost(payload) {
        if (editingLabPost && selectedLabPost?.isDraft) {
            // 같은 투표 선택지를 유지하는 수정만 기존 임시 투표 수를 유지합니다.
            const samePoll = JSON.stringify(selectedLabPost.poll_options || []) ===
                JSON.stringify(payload.poll_options || [])
            const updated = {
                ...selectedLabPost,
                ...payload,
                summary: payload.body.slice(0, 120),
                poll_votes: samePoll
                    ? selectedLabPost.poll_votes || []
                    : payload.poll_options.map(() => 0),
                my_vote: samePoll ? selectedLabPost.my_vote ?? null : null,
                resolved: payload.post_type === 'QUESTION' && selectedLabPost.post_type === 'QUESTION'
                    ? Boolean(selectedLabPost.resolved)
                    : false,
            }

            setDraftLabPosts((items) => items.map((item) => (
                item.id === updated.id ? updated : item
            )))
            setSelectedLabPost(updated)
            setActiveMenu('전체')
            setInput('')
            setKeyword('')
            setLabView('detail')
            setEditingLabPost(false)
            setNotice('수정 내용이 화면에 임시 반영됐어요. 서버에는 저장되지 않았습니다.')
            return
        }

        nextLabId.current += 1
        const created = {
            ...payload,
            id: nextLabId.current,
            summary: payload.body.slice(0, 120),
            author: '작성자 (임시)',
            date: new Date().toLocaleDateString('ko-KR'),
            comments: 0,
            likes: 0,
            isDraft: true,
            resolved: false,
            poll_votes: payload.poll_options.map(() => 0),
            my_vote: null,
        }

        setDraftLabPosts((items) => [created, ...items])
        setSelectedLabPost(created)
        setActiveMenu('전체')
        setInput('')
        setKeyword('')
        setLabView('detail')
        setNotice('커리어 연구소 글이 화면에 임시 등록됐어요. 서버에는 저장되지 않았습니다.')
    }

    function editLabPost() {
        if (!selectedLabPost?.isDraft) return
        setEditingLabPost(true)
        setNotice('')
        setLabView('editor')
    }

    function deleteLabPost() {
        if (!selectedLabPost?.isDraft) return
        if (!window.confirm('임시 게시글을 삭제할까요?')) return

        setDraftLabPosts((items) => items.filter((item) => item.id !== selectedLabPost.id))
        backToLab()
        setNotice('임시 게시글을 삭제했어요.')
    }

    function toggleLabResolved() {
        if (!selectedLabPost?.isDraft || selectedLabPost.post_type !== 'QUESTION') return
        const updated = { ...selectedLabPost, resolved: !selectedLabPost.resolved }
        setDraftLabPosts((items) => items.map((item) => (
            item.id === updated.id ? updated : item
        )))
        setSelectedLabPost(updated)
    }

    function voteLabPoll(index) {
        if (!selectedLabPost?.isDraft || selectedLabPost.post_type !== 'DISCUSSION') return
        if (selectedLabPost.my_vote !== null && selectedLabPost.my_vote !== undefined) return
        if (!selectedLabPost.poll_options?.[index]) return

        const votes = [...selectedLabPost.poll_votes]
        votes[index] = (votes[index] || 0) + 1
        const updated = { ...selectedLabPost, poll_votes: votes, my_vote: index }
        setDraftLabPosts((items) => items.map((item) => (
            item.id === updated.id ? updated : item
        )))
        setSelectedLabPost(updated)
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
                                disabled={activeId !== 'reviews' && activeId !== 'talk' && activeId !== 'lounge' && activeId !== 'lab'}
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
                            <h3>{editingReview ? '취준 도감 후기 수정' : '취준 도감 후기 작성'}</h3>
                            <p className="career-review-help">
                                프론트엔드 화면 테스트 단계입니다. 입력 내용은 서버에 저장되지 않습니다.
                            </p>
                            <CareerReviewForm
                                key={editingReview ? `edit-${selectedReview.id}` : 'new'}
                                initial={editingReview ? selectedReview : null}
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
                        <CareerReviewDetailPage
                            review={selectedReview}
                            onBack={backToReviews}
                            onEdit={editReview}
                            onDelete={deleteReview}
                        />
                    ) : activeId === 'talk' && talkView === 'editor' ? (
                        <div className="career-talk-editor">
                            <h3>{editingTalk ? '커리어 톡톡 글 수정' : '커리어 톡톡 글쓰기'}</h3>
                            <p className="career-talk-help">
                                자유롭게 고민과 경험을 나누는 공간입니다. 현재 글은 서버에 저장되지 않습니다.
                            </p>
                            <CareerTalkForm
                                key={editingTalk ? `talk-edit-${selectedTalk.id}` : 'talk-new'}
                                initial={editingTalk ? selectedTalk : null}
                                defaultMenu={activeMenu === '전체' ? '' : activeMenu}
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
                        />
                    ) : activeId === 'lounge' && loungeView === 'editor' ? (
                        <div className="career-lounge-editor">
                            <h3>{editingLoungePost ? '현직자 라운지 글 수정' : '현직자 라운지 글쓰기'}</h3>
                            <p className="career-lounge-help">
                                실무 경험과 직무 질문을 나눠요. 현재 작성 내용은 서버에 저장되지 않습니다.
                            </p>
                            <CareerLoungeForm
                                key={editingLoungePost ? `lounge-edit-${selectedLoungePost.id}` : 'lounge-new'}
                                initial={editingLoungePost ? selectedLoungePost : null}
                                defaultMenu={activeMenu === '전체' ? '' : activeMenu}
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
                        />
                    ) : activeId === 'lab' && labView === 'editor' ? (
                        <div className="career-lab-editor">
                            <h3>{editingLabPost ? '커리어 연구소 글 수정' : '커리어 연구소 글쓰기'}</h3>
                            <p className="career-lab-help">
                                질문·토론·피드백 유형에 따라 필요한 입력 항목이 달라집니다.
                                실제 서버에는 저장되지 않습니다.
                            </p>
                            <CareerLabForm
                                key={editingLabPost ? `lab-edit-${selectedLabPost.id}` : 'lab-new'}
                                initial={editingLabPost ? selectedLabPost : null}
                                defaultMenu={activeMenu === '전체' ? '' : activeMenu}
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
                                    <option value="oldest">오래된순</option>
                                    <option value="title">제목순</option>
                                </select>
                            </div>

                            <p className="career-sample-caption">
                                * 예시 글은 실제 게시물이 아닙니다. 새로 작성한 임시 글도 서버에는 저장되지 않습니다.
                            </p>

                            <div className="career-post-list" aria-live="polite">
                                {posts.length ? posts.map((item) => (
                                    <article className="career-post" key={item.id}>
                                        <span className="career-post-tag">{item.menu}</span>
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
                                            <span>♡ {item.likes}</span>
                                            <span>♧ {item.comments}</span>
                                            {item.isDraft && <span>임시 글</span>}
                                        </div>
                                    </article>
                                )) : (
                                    <div className="career-empty">
                                        <strong>표시할 게시글이 없어요.</strong>
                                        <span>하위 메뉴나 검색어를 변경해 주세요.</span>
                                    </div>
                                )}
                            </div>
                        </>
                    )}
                </section>
            </div>
        </main>
    )
}
