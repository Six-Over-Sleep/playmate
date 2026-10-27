import { useState } from 'react'
import '../../styles/CareerLabForm.css'

// 기존 커리어 연구소 하위 메뉴를 그대로 사용합니다.
const LAB_MENUS = [
    '취업 전략',
    '포트폴리오 피드백',
    '이력서·자소서',
    '기술면접 스터디',
    '자격증·스펙 전략',
    '직무 비교',
]

const LAB_CODES = {
    '취업 전략': 'JOB_STRATEGY',
    '포트폴리오 피드백': 'PORTFOLIO_FEEDBACK',
    '이력서·자소서': 'RESUME',
    '기술면접 스터디': 'TECH_INTERVIEW',
    '자격증·스펙 전략': 'CERTIFICATION',
    '직무 비교': 'JOB_COMPARISON',
}

const POST_TYPES = [
    {
        value: 'QUESTION',
        label: '질문',
        description: '취업·이력서·포트폴리오에 대해 질문해요.',
    },
    {
        value: 'DISCUSSION',
        label: '토론',
        description: '의견을 나누고 투표를 진행해요.',
    },
    {
        value: 'GUIDE',
        label: '커리어 가이드',
        description: '취업 준비 경험과 실질적인 조언을 공유하면 +50XP!',
    },
]

/** 서버 저장용 커리어 연구소 작성/수정 폼 */
export default function CareerLabForm({
    initial = null,
    defaultMenu = '',
    busy = false,
    onCancel,
    onSubmit,
}) {
    const editing = Boolean(initial)
    const [title, setTitle] = useState(initial?.title || '')
    const [menu, setMenu] = useState(initial?.menu || defaultMenu)
    const [postType, setPostType] = useState(
        initial?.post_type || (defaultMenu === '직무 비교' ? 'DISCUSSION' : 'QUESTION')
    )
    
    // 게시글 본문
    const [body, setBody] = useState(initial?.body || '')

    // 커리어 가이드 전용 입력값
    const [guideExperience, setGuideExperience] = useState(
        initial?.guide_experience || ''
    )

    const [guideAdvice, setGuideAdvice] = useState(
        initial?.guide_advice || ''
    )

    const [anonymous, setAnonymous] = useState(initial?.is_anonymous ?? true)
    const savedOptions = (initial?.poll_options || []).map((option) => (
        typeof option === 'string' ? option : option.option_text
    ))
    const [pollEnabled, setPollEnabled] = useState(savedOptions.length >= 2)
    const [pollOptions, setPollOptions] = useState(savedOptions.length ? savedOptions : ['', ''])

    const cleanedOptions = pollOptions.map((option) => option.trim())
    const validPoll = !pollEnabled || (
        cleanedOptions.length >= 2 &&
        cleanedOptions.length <= 10 &&
        cleanedOptions.every((option) => option.length >= 1 && option.length <= 200) &&
        new Set(cleanedOptions).size === cleanedOptions.length
    )
    // 커리어 가이드 최소 작성 조건
    const validGuide =
        body.trim().length >= 500 &&
        guideExperience.trim().length >= 100 &&
        guideAdvice.trim().length >= 100

    const canSubmit = Boolean(
        title.trim() &&
        menu &&
        body.trim() &&
        !busy &&
        (editing || postType !== 'DISCUSSION' || validPoll) &&
        (postType !== 'GUIDE' || validGuide)
    )

    function submit(event) {
        event.preventDefault()
        if (!canSubmit || !onSubmit) return

        const payload = {
            title: title.trim(),
            body: body.trim(),
            subcategory_code: LAB_CODES[menu],
            is_anonymous: anonymous,
        }

        // 생성 시에만 글 유형과 투표 선택지를 받습니다.
        if (!editing) {
            payload.post_type = postType
            payload.poll_options = postType === 'DISCUSSION' && pollEnabled ? cleanedOptions : []
        }
        // GUIDE 게시글일 때만 가이드 전용 항목 전달
        if (postType === 'GUIDE') {
            payload.guide_experience = guideExperience.trim()
            payload.guide_advice = guideAdvice.trim()
        }
        onSubmit(payload)
    }

    return (
        <form className="career-lab-form" onSubmit={submit}>
            <label>
                제목 *
                <input
                    value={title}
                    maxLength={100}
                    required
                    disabled={busy}
                    onChange={(event) => setTitle(event.target.value)}
                    placeholder="질문이나 토론 주제를 입력해 주세요"
                />
            </label>

            <div className="career-lab-row">
                <label>
                    하위 게시판 *
                    <select value={menu} required disabled={busy} onChange={(event) => setMenu(event.target.value)}>
                        <option value="">게시판 선택</option>
                        {LAB_MENUS.map((item) => <option key={item} value={item}>{item}</option>)}
                    </select>
                </label>
                <label>
                    게시글 유형 *
                    <select
                        value={postType}
                        disabled={busy || editing}
                        onChange={(event) => {
                            setPostType(event.target.value)
                            if (event.target.value !== 'DISCUSSION') setPollEnabled(false)
                        }}
                    >
                        {POST_TYPES.map((item) => (
                            <option key={item.value} value={item.value}>{item.label}</option>
                        ))}
                    </select>
                </label>
            </div>
            <p className="career-lab-type-help">
                {POST_TYPES.find((item) => item.value === postType)?.description}
                {editing ? ' 게시글 유형과 투표 선택지는 등록 후 변경할 수 없습니다.' : ''}
            </p>

            <label>
                본문 *
                <textarea
                    value={body}
                    maxLength={20000}
                    rows={10}
                    required
                    disabled={busy}
                    onChange={(event) => setBody(event.target.value)}
                    placeholder="상황, 희망 직무, 질문, 피드백 요청 사항, 참고 링크 등을 본문에 작성해 주세요. 개인정보는 제외해 주세요."
                />
            </label>
            <p className="career-lab-count">{body.length.toLocaleString()} / 20,000자</p>
            {/* 커리어 가이드 전용 입력 폼 */}
            {postType === 'GUIDE' && (
                <div className="career-lab-guide">

                    <div className="career-lab-input-note">
                        <strong>커리어 가이드 작성</strong>
                        <span>
                            경험과 노하우를 공유하고 50XP를 획득하세요.
                        </span>
                    </div>

                    {/* 경험 및 근거 */}
                    <label>
                        경험 및 근거 *
                        <textarea
                            value={guideExperience}
                            onChange={(e) => setGuideExperience(e.target.value)}
                            maxLength={10000}
                            rows={6}
                            required
                            disabled={busy}
                            placeholder="취업 준비 과정, 프로젝트 경험, 실제 사례 등을 작성해 주세요."
                        />
                    </label>

                    <p className="career-lab-count">
                        {guideExperience.trim().length} / 최소 100자
                    </p>

                    {/* 실질적인 조언 */}
                    <label>
                        실질적인 조언 *
                        <textarea
                            value={guideAdvice}
                            onChange={(e) => setGuideAdvice(e.target.value)}
                            maxLength={10000}
                            rows={6}
                            required
                            disabled={busy}
                            placeholder="다른 취업 준비생에게 추천하는 방법과 주의할 점을 작성해 주세요."
                        />
                    </label>

                    <p className="career-lab-count">
                        {guideAdvice.trim().length} / 최소 100자
                    </p>

                    {/* 작성 조건 안내 */}
                    <div className="career-lab-input-note">
                        <strong>XP 지급 조건</strong>
                        <span>
                            본문 500자 이상 · 경험 100자 이상 · 조언 100자 이상
                        </span>
                    </div>

                </div>
            )}
            {postType === 'QUESTION' && (
                <div className="career-lab-input-note">
                    <strong>질문 해결 상태</strong>
                    <span>등록 후 작성자가 상세 화면에서 해결 완료 여부를 변경할 수 있습니다.</span>
                </div>
            )}

            {postType === 'DISCUSSION' && (
                <>
                    {editing ? (
                        savedOptions.length >= 2 && (
                            <div className="career-lab-poll-editor">
                                <strong>투표 선택지 (수정 불가)</strong>
                                {savedOptions.map((option, index) => (
                                    <p key={`${index}-${option}`}>{index + 1}. {option}</p>
                                ))}
                            </div>
                        )
                    ) : (
                        <>
                            <label className="career-lab-checkbox">
                                <input
                                    type="checkbox"
                                    checked={pollEnabled}
                                    disabled={busy}
                                    onChange={(event) => setPollEnabled(event.target.checked)}
                                />
                                선택지 투표 추가 (선택)
                            </label>
                            {pollEnabled && (
                                <div className="career-lab-poll-editor">
                                    <strong>투표 선택지 (2~10개, 각 200자 이하)</strong>
                                    {pollOptions.map((option, index) => (
                                        <div className="career-lab-poll-option" key={index}>
                                            <input
                                                value={option}
                                                maxLength={200}
                                                disabled={busy}
                                                onChange={(event) => setPollOptions((items) => (
                                                    items.map((item, i) => i === index ? event.target.value : item)
                                                ))}
                                                placeholder={`선택지 ${index + 1}`}
                                                aria-label={`투표 선택지 ${index + 1}`}
                                            />
                                            <button
                                                type="button"
                                                disabled={busy || pollOptions.length <= 2}
                                                onClick={() => setPollOptions((items) => items.filter((_, i) => i !== index))}
                                            >
                                                삭제
                                            </button>
                                        </div>
                                    ))}
                                    <button
                                        type="button"
                                        className="career-lab-add-option"
                                        disabled={busy || pollOptions.length >= 10}
                                        onClick={() => setPollOptions((items) => [...items, ''])}
                                    >
                                        + 선택지 추가
                                    </button>
                                    {!validPoll && (
                                        <p className="career-lab-error">2~10개의 중복 없는 선택지를 입력해 주세요.</p>
                                    )}
                                </div>
                            )}
                        </>
                    )}
                </>
            )}

            <label className="career-lab-checkbox">
                <input
                    type="checkbox"
                    checked={anonymous}
                    disabled={busy}
                    onChange={(event) => setAnonymous(event.target.checked)}
                />
                익명으로 작성
            </label>
            <p className="career-lab-privacy">
                게시글과 투표는 PLAYMATE 서버에 저장됩니다. 파일 첨부 기능은 S3 연동 후 제공됩니다.
                회사 기밀과 개인정보는 게시하지 마세요.
            </p>

            <div className="career-lab-actions">
                <button type="button" className="career-lab-cancel" disabled={busy} onClick={onCancel}>
                    취소
                </button>
                <button type="submit" className="career-lab-submit" disabled={!canSubmit}>
                    {busy ? '저장 중...' : editing ? '수정 완료' : '게시글 등록'}
                </button>
            </div>
        </form>
    )
}
