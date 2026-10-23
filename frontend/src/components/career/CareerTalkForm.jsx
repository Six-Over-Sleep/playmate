import { useState } from 'react'
import '../../styles/CareerTalkForm.css'

// 커리어 톡톡 하위 게시판: 선택한 고민 유형에 맞춰 글을 분류합니다.
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

const USER_STATUS = ['취업 준비 중', '신입', '경력', '이직 준비 중', '기타']
const MAX_FILES = 5
const MAX_FILE_BYTES = 10 * 1024 * 1024

/** 커리어 톡톡 작성/수정 폼. 저장은 상위 페이지의 Mock 상태에서 처리합니다. */
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
    const [anonymous, setAnonymous] = useState(initial?.anonymous ?? true)
    const [attachments, setAttachments] = useState(initial?.attachments || [])
    const [fileError, setFileError] = useState('')

    const canSubmit = Boolean(title.trim() && menu && body.trim())

    function chooseFiles(event) {
        const incoming = Array.from(event.target.files || [])
        event.target.value = ''

        if (attachments.length + incoming.length > MAX_FILES) {
            setFileError(`파일은 최대 ${MAX_FILES}개까지 첨부할 수 있어요.`)
            return
        }
        if (incoming.some((file) => file.size > MAX_FILE_BYTES)) {
            setFileError('첨부 파일 하나의 크기는 10MB를 넘을 수 없어요.')
            return
        }
        setAttachments((items) => [...items, ...incoming])
        setFileError('')
    }

    function submit(event) {
        event.preventDefault()
        if (!canSubmit || busy || !onSubmit) return

        onSubmit({
            title: title.trim(),
            menu,
            body: body.trim(),
            job_category: jobCategory || null,
            current_status: currentStatus || null,
            anonymous,
            attachments,
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
            <p className="career-talk-count">{body.length.toLocaleString()} / 20,000자</p>

            <label className="career-talk-file-label">
                사진·파일 (선택, 최대 5개 · 각 10MB)
                <input
                    type="file"
                    accept="image/*,.pdf,.doc,.docx,.txt"
                    multiple
                    disabled={busy}
                    onChange={chooseFiles}
                />
            </label>

            {fileError && <p className="career-talk-file-error" role="alert">{fileError}</p>}
            {attachments.length > 0 && (
                <ul className="career-talk-files" aria-label="첨부 파일 목록">
                    {attachments.map((file, index) => (
                        <li key={`${file.name}-${index}`}>
                            <span>{file.name}</span>
                            <button
                                type="button"
                                disabled={busy}
                                aria-label={`${file.name} 제거`}
                                onClick={() => setAttachments((items) => items.filter((_, i) => i !== index))}
                            >
                                제거
                            </button>
                        </li>
                    ))}
                </ul>
            )}

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
                작성자 공개 방식은 추후 PLAYMATE 회원 정책에 맞춰 확정합니다.
                현재 글과 첨부 파일은 화면 테스트용 임시 데이터이며 서버에 저장되지 않습니다.
            </p>

            <div className="career-talk-actions">
                <button type="button" className="career-talk-cancel" disabled={busy} onClick={onCancel}>
                    취소
                </button>
                <button type="submit" className="career-talk-submit" disabled={busy || !canSubmit}>
                    {initial ? '수정 내용 임시 반영' : '게시글 임시 등록'}
                </button>
            </div>
        </form>
    )
}
