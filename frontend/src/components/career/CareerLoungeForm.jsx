import { useState } from 'react'
import '../../styles/CareerLoungeForm.css'

// 현직자 라운지 6개 하위 게시판
const LOUNGE_TOPICS = [
    '현직자의 하루',
    '실무 기술',
    '회사 생활',
    '직무 Q&A',
    '주니어 생존기',
    '졸업생 인터뷰',
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

const COMPANY_SIZES = [
    '스타트업',
    '중소기업',
    '중견기업',
    '대기업',
    '공공기관',
    '기타',
]

/** 현직자 라운지 작성/수정 폼. 인증 상태는 입력받거나 임의로 부여하지 않습니다. */
export default function CareerLoungeForm({
    initial = null,
    defaultMenu = '',
    busy = false,
    onCancel,
    onSubmit,
}) {
    const [title, setTitle] = useState(initial?.title || '')
    const [menu, setMenu] = useState(initial?.menu || defaultMenu)
    const [postType, setPostType] = useState(
        initial?.post_type || (defaultMenu === '직무 Q&A' ? 'QUESTION' : 'EXPERIENCE')
    )
    const [jobCategory, setJobCategory] = useState(initial?.job_category || '')
    const [careerYears, setCareerYears] = useState(initial?.career_years ?? '')
    const [companySize, setCompanySize] = useState(initial?.company_size || '')
    const [techStack, setTechStack] = useState(initial?.tech_stack || '')
    const [body, setBody] = useState(initial?.body || '')
    const [workDetails, setWorkDetails] = useState(initial?.work_details || '')
    const [challenges, setChallenges] = useState(initial?.challenges || '')
    const [advice, setAdvice] = useState(initial?.advice || '')
    const [visibility, setVisibility] = useState(initial?.visibility || 'PUBLIC')

    const yearsValid = careerYears === '' || (
        Number.isInteger(Number(careerYears)) &&
        Number(careerYears) >= 0 &&
        Number(careerYears) <= 50
    )
    const canSubmit = Boolean(title.trim() && menu && jobCategory && body.trim() && yearsValid)

    function submit(event) {
        event.preventDefault()
        if (!canSubmit || busy || !onSubmit) return

        onSubmit({
            title: title.trim(),
            menu,
            post_type: postType,
            job_category: jobCategory,
            career_years: careerYears === '' ? null : Number(careerYears),
            company_size: companySize || null,
            tech_stack: techStack.trim() || null,
            body: body.trim(),
            work_details: workDetails.trim() || null,
            challenges: challenges.trim() || null,
            advice: advice.trim() || null,
            visibility,
        })
    }

    return (
        <form className="career-lounge-form" onSubmit={submit}>
            <label>
                제목 *
                <input
                    value={title}
                    maxLength={100}
                    required
                    disabled={busy}
                    onChange={(event) => setTitle(event.target.value)}
                    placeholder="실무 경험이나 질문의 제목을 입력하세요"
                />
            </label>

            <div className="career-lounge-row">
                <label>
                    게시글 주제 *
                    <select
                        value={menu}
                        required
                        disabled={busy}
                        onChange={(event) => {
                            setMenu(event.target.value)
                            if (event.target.value === '직무 Q&A') setPostType('QUESTION')
                            else setPostType('EXPERIENCE')
                        }}
                    >
                        <option value="">주제를 선택하세요</option>
                        {LOUNGE_TOPICS.map((topic) => (
                            <option key={topic} value={topic}>{topic}</option>
                        ))}
                    </select>
                </label>

                <label>
                    글 유형 *
                    <select
                        value={postType}
                        disabled={busy}
                        onChange={(event) => setPostType(event.target.value)}
                    >
                        <option value="EXPERIENCE">실무 경험 공유</option>
                        <option value="QUESTION">직무 질문</option>
                    </select>
                </label>
            </div>

            <div className="career-lounge-row">
                <label>
                    직무 *
                    <select
                        value={jobCategory}
                        required
                        disabled={busy}
                        onChange={(event) => setJobCategory(event.target.value)}
                    >
                        <option value="">직무를 선택하세요</option>
                        {JOB_CATEGORIES.map((job) => (
                            <option key={job} value={job}>{job}</option>
                        ))}
                    </select>
                </label>

                <label>
                    경력 연차 (선택)
                    <input
                        type="number"
                        min="0"
                        max="50"
                        step="1"
                        value={careerYears}
                        disabled={busy}
                        onChange={(event) => setCareerYears(event.target.value)}
                        placeholder="예: 3"
                    />
                </label>
            </div>

            <div className="career-lounge-row">
                <label>
                    기업 규모 (선택)
                    <select
                        value={companySize}
                        disabled={busy}
                        onChange={(event) => setCompanySize(event.target.value)}
                    >
                        <option value="">선택 안 함</option>
                        {COMPANY_SIZES.map((size) => (
                            <option key={size} value={size}>{size}</option>
                        ))}
                    </select>
                </label>

                <label>
                    기술 스택 (선택)
                    <input
                        value={techStack}
                        maxLength={150}
                        disabled={busy}
                        onChange={(event) => setTechStack(event.target.value)}
                        placeholder="예: Python, FastAPI, React"
                    />
                </label>
            </div>

            <label>
                본문 *
                <textarea
                    value={body}
                    maxLength={20000}
                    rows={10}
                    required
                    disabled={busy}
                    onChange={(event) => setBody(event.target.value)}
                    placeholder="경험이나 궁금한 내용을 작성해 주세요. 회사 기밀과 개인정보는 제외해 주세요."
                />
            </label>
            <p className="career-lounge-count">{body.length.toLocaleString()} / 20,000자</p>

            <label>
                실제 업무 (선택)
                <textarea
                    value={workDetails}
                    maxLength={3000}
                    rows={3}
                    disabled={busy}
                    onChange={(event) => setWorkDetails(event.target.value)}
                    placeholder="담당 업무나 하루 일과를 공유해 주세요"
                />
            </label>

            <label>
                어려웠던 점 (선택)
                <textarea
                    value={challenges}
                    maxLength={3000}
                    rows={3}
                    disabled={busy}
                    onChange={(event) => setChallenges(event.target.value)}
                    placeholder="업무 중 겪은 어려움과 해결 방법"
                />
            </label>

            <label>
                조언 (선택)
                <textarea
                    value={advice}
                    maxLength={3000}
                    rows={3}
                    disabled={busy}
                    onChange={(event) => setAdvice(event.target.value)}
                    placeholder="취준생·주니어에게 남기고 싶은 조언"
                />
            </label>

            <label>
                공개 범위 (UI 시연용)
                <select
                    value={visibility}
                    disabled={busy}
                    onChange={(event) => setVisibility(event.target.value)}
                >
                    <option value="PUBLIC">전체 공개</option>
                    <option value="MEMBERS">회원에게만 공개 (추후 구현)</option>
                </select>
            </label>

            <p className="career-lounge-privacy">
                회사명·연봉은 입력하지 않아도 됩니다. 졸업생/재직 인증은 별도 검증이 필요한 기능으로,
                현재는 인증 배지를 표시하지 않습니다. 공개 범위 선택은 프론트엔드 시연용이며
                실제 접근 제한은 적용되지 않습니다.
            </p>

            <div className="career-lounge-actions">
                <button type="button" className="career-lounge-cancel" disabled={busy} onClick={onCancel}>
                    취소
                </button>
                <button type="submit" className="career-lounge-submit" disabled={busy || !canSubmit}>
                    {initial ? '수정 내용 임시 반영' : '게시글 임시 등록'}
                </button>
            </div>
        </form>
    )
}
