import { useState } from 'react'
import '../../styles/CareerLoungeForm.css'

// 현직자 라운지 6개 주제
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

// 현재 Backend에서 지원하는 입력값만 활성화
export default function CareerLoungeForm({
    initial = null,
    defaultMenu = '',
    busy = false,
    onCancel,
    onSubmit,
}) {
    const [title, setTitle] = useState(initial?.title || '')
    const [menu, setMenu] = useState(initial?.menu || defaultMenu)
    const [jobCategory, setJobCategory] = useState(initial?.job_category || '')
    const [careerYears, setCareerYears] = useState(initial?.career_years ?? '')
    const [companyName, setCompanyName] = useState(initial?.company_name || '')
    const [body, setBody] = useState(initial?.body || '')
    const [anonymous, setAnonymous] = useState(initial?.anonymous ?? false)

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
            job_category: jobCategory,
            career_years: careerYears === '' ? null : Number(careerYears),
            company_name: companyName.trim() || null,
            body: body.trim(),
            anonymous,
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
                        onChange={(event) => setMenu(event.target.value)}
                    >
                        <option value="">주제를 선택하세요</option>
                        {LOUNGE_TOPICS.map((topic) => (
                            <option key={topic} value={topic}>{topic}</option>
                        ))}
                    </select>
                </label>

                <label>
                    글 유형
                    <select
                        value={menu === '직무 Q&A' ? 'QUESTION' : 'EXPERIENCE'}
                        disabled
                        aria-label="게시글 주제에 따른 자동 분류"
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

            <label>
                회사명 (선택)
                <input
                    value={companyName}
                    maxLength={150}
                    disabled={busy}
                    onChange={(event) => setCompanyName(event.target.value)}
                    placeholder="회사명 (공개해도 되는 경우에만 입력)"
                />
            </label>

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

            <p className="career-lounge-count">
                {body.length.toLocaleString()} / 20,000자
            </p>

            <label className="career-lounge-anonymous">
                <input
                    type="checkbox"
                    checked={anonymous}
                    disabled={busy}
                    onChange={(event) => setAnonymous(event.target.checked)}
                />
                익명으로 작성하기
            </label>

            <p className="career-lounge-privacy">
                게시글은 PLAYMATE 서버에 저장됩니다. 익명 설정은 작성자 닉네임에만 적용되며,
                회사명을 입력하면 본문과 함께 공개됩니다. 재직 인증 기능은 아직 제공하지 않습니다.
                기업 규모·기술 스택·업무 세부 항목·회원 전용 공개 설정은 서버 저장 기능이 준비되면 추가합니다.
            </p>

            <div className="career-lounge-actions">
                <button
                    type="button"
                    className="career-lounge-cancel"
                    disabled={busy}
                    onClick={onCancel}
                >
                    취소
                </button>
                <button
                    type="submit"
                    className="career-lounge-submit"
                    disabled={busy || !canSubmit}
                >
                    {busy ? '저장 중...' : initial ? '수정하기' : '게시글 등록'}
                </button>
            </div>
        </form>
    )
}
