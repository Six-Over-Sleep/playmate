import { useState } from 'react'
import '../../styles/CareerLabForm.css'

// 커리어 연구소 하위 게시판. 기존 취업 메인 메뉴명과 일치시킵니다.
const LAB_MENUS = [
    '취업 전략',
    '포트폴리오 피드백',
    '이력서·자소서',
    '기술면접 스터디',
    '자격증·스펙 전략',
    '직무 비교',
]

const JOB_CATEGORIES = [
    '소프트웨어 개발',
    '데이터·AI',
    '인프라·클라우드',
    '정보보안',
    'IT 기획·관리',
    'QA·테스트',
    '디자인·UX',
    '기타 IT 직무',
]

const POST_TYPES = [
    { value: 'QUESTION', label: '질문', description: '구체적인 고민을 질문하고 해결 방법을 구해요.' },
    { value: 'DISCUSSION', label: '토론', description: '주장과 근거를 나누고 선택지 투표를 진행해요.' },
    { value: 'FEEDBACK', label: '피드백', description: '이력서·포트폴리오 등을 검토받을 수 있어요.' },
]

function isValidWebLink(value) {
    if (!value.trim()) return true
    try {
        const url = new URL(value.trim())
        return url.protocol === 'https:' || url.protocol === 'http:'
    } catch {
        return false
    }
}

/** 커리어 연구소 전용 폼. onSubmit은 화면 임시 데이터에만 반영됩니다. */
export default function CareerLabForm({
    initial = null,
    defaultMenu = '',
    busy = false,
    onCancel,
    onSubmit,
}) {
    const [title, setTitle] = useState(initial?.title || '')
    const [menu, setMenu] = useState(initial?.menu || defaultMenu)
    // 선택한 하위 게시판에 맞는 글 유형을 기본값으로 제안합니다.
    const suggestedType = ['포트폴리오 피드백', '이력서·자소서'].includes(defaultMenu)
        ? 'FEEDBACK'
        : defaultMenu === '직무 비교'
            ? 'DISCUSSION'
            : 'QUESTION'
    const [postType, setPostType] = useState(initial?.post_type || suggestedType)
    const [body, setBody] = useState(initial?.body || '')
    const [desiredJob, setDesiredJob] = useState(initial?.desired_job || '')
    const [questionDetail, setQuestionDetail] = useState(initial?.question_detail || '')
    const [discussionStance, setDiscussionStance] = useState(initial?.discussion_stance || '')
    const [feedbackFocus, setFeedbackFocus] = useState(initial?.feedback_focus || '')
    const [referenceUrl, setReferenceUrl] = useState(initial?.reference_url || '')
    const [fileNames, setFileNames] = useState(initial?.file_names || [])
    const [pollEnabled, setPollEnabled] = useState(Boolean(initial?.poll_options?.length))
    const [pollOptions, setPollOptions] = useState(initial?.poll_options || ['', ''])

    const trimmedOptions = pollOptions.map((item) => item.trim())
    const pollValid = !pollEnabled || (
        trimmedOptions.length >= 2 &&
        trimmedOptions.length <= 5 &&
        trimmedOptions.every(Boolean) &&
        new Set(trimmedOptions).size === trimmedOptions.length
    )
    const linkValid = isValidWebLink(referenceUrl)
    const typeValid = postType === 'DISCUSSION'
        ? Boolean(discussionStance.trim() && pollValid)
        : postType === 'FEEDBACK'
            ? Boolean(feedbackFocus.trim() && linkValid)
            : true

    const canSubmit = Boolean(
        title.trim() && menu && body.trim() && typeValid && !busy
    )

    function updatePollOption(index, value) {
        setPollOptions((items) => items.map((item, i) => i === index ? value : item))
    }

    function chooseFiles(event) {
        // 업로드 API가 없으므로 파일 내용은 읽지 않고 이름만 화면에 남깁니다.
        setFileNames(Array.from(event.target.files || []).map((file) => file.name))
    }

    function submit(event) {
        event.preventDefault()
        if (!canSubmit || !onSubmit) return

        onSubmit({
            title: title.trim(),
            menu,
            post_type: postType,
            body: body.trim(),
            desired_job: postType === 'QUESTION' ? desiredJob || null : null,
            question_detail: postType === 'QUESTION' ? questionDetail.trim() || null : null,
            discussion_stance: postType === 'DISCUSSION' ? discussionStance.trim() : null,
            poll_options: postType === 'DISCUSSION' && pollEnabled ? trimmedOptions : [],
            feedback_focus: postType === 'FEEDBACK' ? feedbackFocus.trim() : null,
            reference_url: postType === 'FEEDBACK' ? referenceUrl.trim() || null : null,
            file_names: postType === 'FEEDBACK' ? fileNames : [],
        })
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
                    placeholder="질문·토론·피드백 요청 제목을 입력하세요"
                />
            </label>

            <div className="career-lab-row">
                <label>
                    하위 게시판 *
                    <select
                        value={menu}
                        required
                        disabled={busy}
                        onChange={(event) => setMenu(event.target.value)}
                    >
                        <option value="">게시판 선택</option>
                        {LAB_MENUS.map((item) => (
                            <option key={item} value={item}>{item}</option>
                        ))}
                    </select>
                </label>
                <label>
                    게시글 유형 *
                    <select
                        value={postType}
                        disabled={busy}
                        onChange={(event) => setPostType(event.target.value)}
                    >
                        {POST_TYPES.map((item) => (
                            <option key={item.value} value={item.value}>{item.label}</option>
                        ))}
                    </select>
                </label>
            </div>

            <p className="career-lab-type-help">
                {POST_TYPES.find((item) => item.value === postType)?.description}
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
                    placeholder="상황과 궁금한 점을 구체적으로 작성해 주세요. 개인 정보는 제외해 주세요."
                />
            </label>
            <p className="career-lab-count">{body.length.toLocaleString()} / 20,000자</p>

            {postType === 'QUESTION' && (
                <>
                    <div className="career-lab-row">
                        <label>
                            희망 직무 (선택)
                            <select
                                value={desiredJob}
                                disabled={busy}
                                onChange={(event) => setDesiredJob(event.target.value)}
                            >
                                <option value="">선택 안 함</option>
                                {JOB_CATEGORIES.map((item) => (
                                    <option key={item} value={item}>{item}</option>
                                ))}
                            </select>
                        </label>
                        <div className="career-lab-input-note">
                            <strong>질문 상태</strong>
                            <span>등록 후 상세 화면에서 해결 여부를 표시할 수 있어요.</span>
                        </div>
                    </div>
                    <label>
                        구체적으로 답변받고 싶은 내용 (선택)
                        <textarea
                            value={questionDetail}
                            maxLength={3000}
                            rows={3}
                            disabled={busy}
                            onChange={(event) => setQuestionDetail(event.target.value)}
                            placeholder="예: 신입 데이터 분석가의 프로젝트 구성은 어떻게 하면 좋을까요?"
                        />
                    </label>
                </>
            )}

            {postType === 'DISCUSSION' && (
                <>
                    <label>
                        나의 주장·의견 *
                        <textarea
                            value={discussionStance}
                            maxLength={3000}
                            rows={4}
                            required
                            disabled={busy}
                            onChange={(event) => setDiscussionStance(event.target.value)}
                            placeholder="선택한 입장과 그 이유를 적어 주세요"
                        />
                    </label>
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
                            <strong>투표 선택지 (2~5개)</strong>
                            {pollOptions.map((option, index) => (
                                <div className="career-lab-poll-option" key={index}>
                                    <input
                                        value={option}
                                        maxLength={80}
                                        disabled={busy}
                                        onChange={(event) => updatePollOption(index, event.target.value)}
                                        placeholder={`선택지 ${index + 1}`}
                                        aria-label={`투표 선택지 ${index + 1}`}
                                    />
                                    <button
                                        type="button"
                                        disabled={busy || pollOptions.length <= 2}
                                        onClick={() => setPollOptions((items) => items.filter((_, i) => i !== index))}
                                        aria-label={`선택지 ${index + 1} 삭제`}
                                    >
                                        삭제
                                    </button>
                                </div>
                            ))}
                            <button
                                type="button"
                                className="career-lab-add-option"
                                disabled={busy || pollOptions.length >= 5}
                                onClick={() => setPollOptions((items) => [...items, ''])}
                            >
                                + 선택지 추가
                            </button>
                            {!pollValid && (
                                <p className="career-lab-error">모든 선택지를 채우고 중복되지 않게 입력해 주세요.</p>
                            )}
                        </div>
                    )}
                </>
            )}

            {postType === 'FEEDBACK' && (
                <>
                    <label>
                        집중적으로 피드백받고 싶은 부분 *
                        <textarea
                            value={feedbackFocus}
                            rows={4}
                            maxLength={3000}
                            required
                            disabled={busy}
                            onChange={(event) => setFeedbackFocus(event.target.value)}
                            placeholder="예: 포트폴리오 설명의 설득력과 프로젝트 성과 표현 방식"
                        />
                    </label>
                    <label>
                        참고 링크 (선택)
                        <input
                            type="url"
                            value={referenceUrl}
                            disabled={busy}
                            onChange={(event) => setReferenceUrl(event.target.value)}
                            placeholder="https://example.com/portfolio"
                        />
                    </label>
                    {!linkValid && <p className="career-lab-error">http 또는 https로 시작하는 주소를 입력해 주세요.</p>}
                    <label>
                        참고 파일 (선택 · 파일명만 표시)
                        <input
                            type="file"
                            multiple
                            disabled={busy}
                            onChange={chooseFiles}
                        />
                    </label>
                    {fileNames.length > 0 && (
                        <p className="career-lab-files">선택한 파일: {fileNames.join(', ')}</p>
                    )}
                </>
            )}

            <p className="career-lab-privacy">
                현재는 프론트엔드 화면 테스트 단계입니다. 작성 내용은 서버에 저장되지 않고,
                선택한 파일도 업로드되지 않습니다. 공개가 제한된 자료 및 개인정보는 올리지 마세요.
                투표와 해결 상태도 임시 화면에서만 동작합니다.
            </p>

            <div className="career-lab-actions">
                <button type="button" className="career-lab-cancel" disabled={busy} onClick={onCancel}>
                    취소
                </button>
                <button type="submit" className="career-lab-submit" disabled={!canSubmit}>
                    {initial ? '수정 내용 임시 반영' : '게시글 임시 등록'}
                </button>
            </div>
        </form>
    )
}
