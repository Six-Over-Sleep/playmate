import { useState } from 'react'
import '../../styles/CareerReviewForm.css'

// 취업 카테고리 공통 직무 대분류 (추후 DB 직무 코드와 연동)
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

/** 취준 도감 전용 작성·수정 폼. 실제 저장은 상위 컴포넌트에서 처리한다. */
export default function CareerReviewForm({ initial = null, busy = false, onCancel, onSubmit }) {
    const [title, setTitle] = useState(initial?.title || '')
    const [companyName, setCompanyName] = useState(initial?.company_name || '')
    const [jobCategory, setJobCategory] = useState(initial?.job_category || '')
    const [experienceLevel, setExperienceLevel] = useState(initial?.experience_level || '')
    const [processStage, setProcessStage] = useState(initial?.process_stage || '')
    const [processResult, setProcessResult] = useState(initial?.process_result || '')
    const [body, setBody] = useState(initial?.body || '')

    const bodyLength = body.trim().length
    const isValid = Boolean(
        title.trim() &&
        jobCategory &&
        processStage &&
        processResult &&
        bodyLength >= 500
    )

    function handleSubmit(event) {
        event.preventDefault()
        if (!isValid || busy || !onSubmit) return

        onSubmit({
            title: title.trim(),
            body: body.trim(),
            company_name: companyName.trim() || null,
            job_category: jobCategory,
            experience_level: experienceLevel || null,
            process_stage: processStage,
            process_result: processResult,
        })
    }

    return (
        <form className="career-review-form" onSubmit={handleSubmit}>
            <label>
                제목 *
                <input
                    value={title}
                    maxLength={100}
                    required
                    disabled={busy}
                    onChange={(event) => setTitle(event.target.value)}
                    placeholder="취업 후기 제목을 입력하세요"
                />
            </label>

            <label>
                기업명 (선택)
                <input
                    value={companyName}
                    maxLength={100}
                    disabled={busy}
                    onChange={(event) => setCompanyName(event.target.value)}
                    placeholder="기업명을 입력하세요"
                />
            </label>

            <div className="career-review-row">
                <label>
                    지원 직무 *
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
                    지원 유형
                    <select
                        value={experienceLevel}
                        disabled={busy}
                        onChange={(event) => setExperienceLevel(event.target.value)}
                    >
                        <option value="">선택 안 함</option>
                        <option value="NEW">신입</option>
                        <option value="EXPERIENCED">경력</option>
                    </select>
                </label>
            </div>

            <div className="career-review-row">
                <label>
                    전형 단계 *
                    <select
                        value={processStage}
                        required
                        disabled={busy}
                        onChange={(event) => setProcessStage(event.target.value)}
                    >
                        <option value="">전형 단계를 선택하세요</option>
                        <option value="DOCUMENT">서류</option>
                        <option value="CODING_TEST">코딩 테스트</option>
                        <option value="ASSIGNMENT">과제</option>
                        <option value="INTERVIEW">면접</option>
                        <option value="FINAL">최종</option>
                    </select>
                </label>

                <label>
                    전형 결과 *
                    <select
                        value={processResult}
                        required
                        disabled={busy}
                        onChange={(event) => setProcessResult(event.target.value)}
                    >
                        <option value="">결과를 선택하세요</option>
                        <option value="PASS">합격</option>
                        <option value="FAIL">불합격</option>
                        <option value="PENDING">대기</option>
                    </select>
                </label>
            </div>

            <label>
                취업 후기 * (최소 500자)
                <textarea
                    value={body}
                    rows={12}
                    minLength={500}
                    maxLength={20000}
                    required
                    disabled={busy}
                    onChange={(event) => setBody(event.target.value)}
                    placeholder="전형 과정, 준비 방법, 경험과 느낀 점을 자세히 적어 주세요."
                />
            </label>

            <p className={`career-review-count ${bodyLength >= 500 ? 'valid' : ''}`}>
                {bodyLength.toLocaleString()}자 / 최소 500자
            </p>

            <p className="career-review-privacy">
                개인정보·기업 기밀·공개 제한 면접 문제는 포함하지 마세요.
                현재 입력 내용은 서버에 저장되지 않으며 새로고침 시 사라집니다.
            </p>

            <div className="career-review-actions">
                <button
                    type="button"
                    className="career-review-cancel"
                    disabled={busy}
                    onClick={onCancel}
                >
                    취소
                </button>
                <button
                    type="submit"
                    className="career-review-submit"
                    disabled={busy || !isValid || !onSubmit}
                >
                    {initial ? '수정 내용 임시 반영' : '후기 임시 등록'}
                </button>
            </div>
        </form>
    )
}
