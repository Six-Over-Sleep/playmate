import { useState } from 'react'
import '../../styles/CareerTalkForm.css'

// 기존 디자인과 선택지를 그대로 사용합니다.
const TALK_TYPES = [
    '취업 고민',
    '이직 고민',
    '진로 고민',
    '취준 일상',
    '취업 근황',
    '연봉·처우 고민',
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

const USER_STATUS = [
    '취업 준비 중',
    '신입',
    '경력',
    '이직 준비 중',
    '기타',
]

/** 커리어 톡톡 게시글 작성 및 수정 폼. 저장은 부모의 API 함수에 위임합니다. */
export default function CareerTalkForm({
    initial = null,
    defaultMenu = '',
    busy = false,
    onCancel,
    onSubmit,
}) {
    const [title, setTitle] = useState(initial?.title || '')
    const [menu, setMenu] = useState(initial?.menu || defaultMenu)
    const [body, setBody] = useState(initial?.body || '')
    const [jobCategory, setJobCategory] = useState(initial?.job_category || '')
    const [currentStatus, setCurrentStatus] = useState(initial?.current_status || '')
    const [anonymous, setAnonymous] = useState(initial?.anonymous ?? initial?.is_anonymous ?? true)

    const canSubmit = Boolean(title.trim() && menu && body.trim())

    function submit(event) {
        event.preventDefault()
        if (busy || !canSubmit || !onSubmit) return

        onSubmit({
            title: title.trim(),
            menu,
            body: body.trim(),
            job_category: jobCategory || null,
            current_status: currentStatus || null,
            anonymous,
        })
    }

    return (
        <form className="career-talk-form" onSubmit={submit}>
            <label>
                제목 *
                <input
                    value={title}
                    maxLength={100}
                    required
                    disabled={busy}
                    onChange={(event) => setTitle(event.target.value)}
                    placeholder="공유하고 싶은 이야기의 제목을 입력하세요"
                />
            </label>

            <div className="career-talk-row">
                <label>
                    고민 유형 *
                    <select
                        value={menu}
                        required
                        disabled={busy}
                        onChange={(event) => setMenu(event.target.value)}
                    >
                        <option value="">유형을 선택하세요</option>
                        {TALK_TYPES.map((type) => (
                            <option key={type} value={type}>{type}</option>
                        ))}
                    </select>
                </label>

                <label>
                    현재 상태 (선택)
                    <select
                        value={currentStatus}
                        disabled={busy}
                        onChange={(event) => setCurrentStatus(event.target.value)}
                    >
                        <option value="">선택 안 함</option>
                        {USER_STATUS.map((status) => (
                            <option key={status} value={status}>{status}</option>
                        ))}
                    </select>
                </label>
            </div>

            <label>
                직무 태그 (선택)
                <select
                    value={jobCategory}
                    disabled={busy}
                    onChange={(event) => setJobCategory(event.target.value)}
                >
                    <option value="">선택 안 함</option>
                    {JOB_CATEGORIES.map((job) => (
                        <option key={job} value={job}>{job}</option>
                    ))}
                </select>
            </label>

            <label>
                내용 *
                <textarea
                    value={body}
                    maxLength={20000}
                    rows={10}
                    required
                    disabled={busy}
                    onChange={(event) => setBody(event.target.value)}
                    placeholder="취업 고민이나 경험을 자유롭게 나눠주세요. 개인 연락처와 민감한 정보는 작성하지 마세요."
                />
            </label>

            <p className="career-talk-count">
                {body.length.toLocaleString()} / 20,000자
            </p>

            {/* 파일 저장 API가 없으므로 첨부 UI만 비활성화합니다. */}
            <label className="career-talk-file-label">
                사진·파일 첨부 (준비 중)
                <input
                    type="file"
                    accept="image/*,.pdf,.doc,.docx,.txt"
                    multiple
                    disabled
                />
            </label>

            <label className="career-talk-anonymous">
                <input
                    type="checkbox"
                    checked={anonymous}
                    disabled={busy}
                    onChange={(event) => setAnonymous(event.target.checked)}
                />
                익명으로 작성하기
            </label>

            <p className="career-talk-privacy">
                개인정보·기업 기밀 등 민감한 정보는 포함하지 마세요.
                제목과 본문은 서버에 저장됩니다. 파일 첨부 기능은 추후 제공됩니다.
            </p>

            <div className="career-talk-actions">
                <button
                    type="button"
                    className="career-talk-cancel"
                    disabled={busy}
                    onClick={onCancel}
                >
                    취소
                </button>
                <button
                    type="submit"
                    className="career-talk-submit"
                    disabled={busy || !canSubmit}
                >
                    {busy ? '저장 중...' : initial ? '수정하기' : '게시글 등록'}
                </button>
            </div>
        </form>
    )
}
