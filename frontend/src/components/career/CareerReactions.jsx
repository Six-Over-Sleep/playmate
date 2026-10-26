
import { useEffect, useRef, useState } from 'react'
import '../../styles/CareerReactions.css'

import {
    createCareerComment,
    deleteCareerComment,
    getCareerComments,
    likeCareerPost,
    scrapCareerPost,
    unlikeCareerPost,
    unscrapCareerPost,
    updateCareerComment,
} from '../../services/careerApi'


function formatCommentDate(value) {
    if (!value) return ''

    // 시간대 정보가 없으면 UTC로 해석
    const hasTimezone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value)
    const dateValue = hasTimezone ? value : `${value}Z`

    return new Date(dateValue).toLocaleString('ko-KR', {
        timeZone: 'Asia/Seoul',
    })
}


/**
 * 취업 게시글 4종 공통 좋아요·스크랩·댓글 영역.
 *
 * - 댓글과 대댓글의 익명 여부를 각각 선택
 * - 댓글 작성 후 서버에서 댓글 목록 재조회
 * - 댓글 수정·삭제 및 XP 기능 유지
 * - 대댓글은 1단계까지만 허용
 */
export default function CareerReactions({ post, onChange }) {

    const [comments, setComments] = useState([])
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState('')

    // 일반 댓글
    const [body, setBody] = useState('')
    const [isAnonymous, setIsAnonymous] = useState(false)

    // 대댓글
    const [replyTargetId, setReplyTargetId] = useState(null)
    const [replyBody, setReplyBody] = useState('')
    const [replyAnonymous, setReplyAnonymous] = useState(false)

    // 댓글 수정
    const [editingId, setEditingId] = useState(null)
    const [editBody, setEditBody] = useState('')

    const mutationLock = useRef(false)


    // =========================================
    // 1. 댓글 목록 조회
    // =========================================
    useEffect(() => {
        let canceled = false

        getCareerComments(post.id)
            .then((data) => {
                if (!canceled) {
                    setComments(Array.isArray(data) ? data : [])
                }
            })
            .catch((cause) => {
                if (!canceled) {
                    setError(`댓글 조회 실패: ${cause.message}`)
                }
            })

        return () => {
            canceled = true
        }
    }, [post.id])


    async function loadComments() {
        const data = await getCareerComments(post.id)
        setComments(Array.isArray(data) ? data : [])
    }


    // =========================================
    // 2. 중복 요청 방지
    // =========================================
    async function mutate(task, failMessage) {
        if (mutationLock.current) return false

        mutationLock.current = true
        setBusy(true)
        setError('')

        try {
            await task()
            return true
        } catch (cause) {
            setError(`${failMessage}: ${cause.message}`)
            return false
        } finally {
            mutationLock.current = false
            setBusy(false)
        }
    }


    // =========================================
    // 3. 좋아요
    // =========================================
    function toggleLike() {
        return mutate(async () => {
            const result = post.liked_by_me
                ? await unlikeCareerPost(post.id)
                : await likeCareerPost(post.id)

            onChange({
                like_count: result.like_count,
                liked_by_me: result.liked_by_me,
            })
        }, '좋아요 처리 실패')
    }


    // =========================================
    // 4. 스크랩
    // =========================================
    function toggleScrap() {
        return mutate(async () => {
            const result = post.scrapped_by_me
                ? await unscrapCareerPost(post.id)
                : await scrapCareerPost(post.id)

            onChange({
                scrapped_by_me: result.scrapped_by_me,
            })
        }, '스크랩 처리 실패')
    }


    // =========================================
    // 5. 댓글·대댓글 작성
    // =========================================
    function addComment(
        text,
        parentCommentId = null,
        anonymous = false
    ) {
        return mutate(async () => {
            await createCareerComment(
                post.id,
                text,
                parentCommentId,
                anonymous
            )

            await loadComments()
        }, '댓글 작성 실패')
    }


    // =========================================
    // 6. 댓글 수정
    // =========================================
    function editComment(commentId, text) {
        return mutate(async () => {
            await updateCareerComment(commentId, text)
            await loadComments()
        }, '댓글 수정 실패')
    }


    // =========================================
    // 7. 댓글 삭제
    // =========================================
    async function deleteComment(commentId) {
        if (!window.confirm('이 댓글을 삭제할까요?')) {
            return
        }

        await mutate(async () => {
            await deleteCareerComment(commentId)
            await loadComments()
        }, '댓글 삭제 실패')
    }


    // =========================================
    // 8. 일반 댓글 제출
    // =========================================
    async function submitComment(event) {
        event.preventDefault()

        if (!body.trim()) return

        if (await addComment(
            body.trim(),
            null,
            isAnonymous
        )) {
            setBody('')
            setIsAnonymous(false)
        }
    }


    // =========================================
    // 9. 대댓글 제출
    // =========================================
    async function submitReply(event) {
        event.preventDefault()

        if (!replyBody.trim() || replyTargetId === null) {
            return
        }

        if (await addComment(
            replyBody.trim(),
            replyTargetId,
            replyAnonymous
        )) {
            setReplyTargetId(null)
            setReplyBody('')
            setReplyAnonymous(false)
        }
    }


    // =========================================
    // 10. 수정 저장
    // =========================================
    async function saveEdit(commentId) {
        if (!editBody.trim()) return

        if (await editComment(commentId, editBody.trim())) {
            setEditingId(null)
        }
    }


    // =========================================
    // 11. 답글 입력창 열기·닫기
    // =========================================
    function toggleReply(commentId) {
        setReplyTargetId(
            (current) => current === commentId
                ? null
                : commentId
        )

        setReplyBody('')
        setReplyAnonymous(false)
    }


    // =========================================
    // 12. 댓글·대댓글 공통 입력 폼
    // =========================================
    function renderForm(
        value,
        setValue,
        onSubmit,
        placeholder,
        label,
        anonymous,
        setAnonymous,
    ) {
        return (
            <form
                className="career-comment-form"
                onSubmit={onSubmit}
            >
                <textarea
                    aria-label={placeholder}
                    rows={3}
                    maxLength={2000}
                    value={value}
                    disabled={busy}
                    placeholder={placeholder}
                    onChange={(event) =>
                        setValue(event.target.value)
                    }
                />

                <div className="career-comment-form-footer">
                    <label className="career-comment-anonymous">
                        <input
                            type="checkbox"
                            checked={anonymous}
                            disabled={busy}
                            onChange={(event) =>
                                setAnonymous(event.target.checked)
                            }
                        />
                        익명으로 작성
                    </label>

                    <button
                        type="submit"
                        disabled={busy || !value.trim()}
                    >
                        {label}
                    </button>
                </div>
            </form>
        )
    }


    // 삭제된 부모 댓글은 댓글 수에서 제외
    const commentCount = comments.filter(
        (comment) => !comment.is_deleted
    ).length


    // =========================================
    // 13. 화면
    // =========================================
    return (
        <section className="career-reactions">

            {/* 좋아요·스크랩 */}
            <div className="career-reaction-buttons">
                <button
                    type="button"
                    className={post.liked_by_me ? 'active' : ''}
                    aria-pressed={Boolean(post.liked_by_me)}
                    disabled={busy}
                    onClick={toggleLike}
                >
                    {post.liked_by_me ? '♥' : '♡'} 좋아요 {post.like_count ?? 0}
                </button>

                <button
                    type="button"
                    className={post.scrapped_by_me ? 'active' : ''}
                    aria-pressed={Boolean(post.scrapped_by_me)}
                    disabled={busy}
                    onClick={toggleScrap}
                >
                    {post.scrapped_by_me ? '스크랩됨' : '스크랩'}
                </button>
            </div>

            {error && (
                <p
                    className="career-reaction-error"
                    role="alert"
                >
                    {error}
                </p>
            )}

            <h4>댓글 {commentCount}</h4>

            {/* 댓글·대댓글 목록 */}
            {comments.length > 0 ? (
                <ul className="career-comment-list">
                    {comments.map((comment) => {
                        const isReply =
                            comment.parent_comment_id != null

                        // 삭제된 부모 댓글
                        if (comment.is_deleted) {
                            return (
                                <li
                                    key={comment.id}
                                    className="career-comment deleted"
                                >
                                    <p>삭제된 댓글입니다.</p>
                                </li>
                            )
                        }

                        return (
                            <li
                                key={comment.id}
                                className={
                                    isReply
                                        ? 'career-comment reply'
                                        : 'career-comment'
                                }
                            >
                                <div className="career-comment-head">
                                    <strong>{comment.author_name}</strong>
                                    <span>
                                        {formatCommentDate(comment.created_at)}
                                    </span>
                                </div>

                                {editingId === comment.id ? (
                                    <div className="career-comment-edit">
                                        <textarea
                                            aria-label="댓글 수정 내용"
                                            rows={3}
                                            maxLength={2000}
                                            value={editBody}
                                            disabled={busy}
                                            onChange={(event) =>
                                                setEditBody(event.target.value)
                                            }
                                        />

                                        <div className="career-comment-actions">
                                            <button
                                                type="button"
                                                disabled={busy || !editBody.trim()}
                                                onClick={() =>
                                                    saveEdit(comment.id)
                                                }
                                            >
                                                저장
                                            </button>

                                            <button
                                                type="button"
                                                disabled={busy}
                                                onClick={() =>
                                                    setEditingId(null)
                                                }
                                            >
                                                취소
                                            </button>
                                        </div>
                                    </div>
                                ) : (
                                    <>
                                        <p>{comment.body}</p>

                                        <div className="career-comment-actions">
                                            {!isReply && (
                                                <button
                                                    type="button"
                                                    disabled={busy}
                                                    onClick={() =>
                                                        toggleReply(comment.id)
                                                    }
                                                >
                                                    {replyTargetId === comment.id
                                                        ? '답글 취소'
                                                        : '답글'}
                                                </button>
                                            )}

                                            {comment.is_owner && (
                                                <>
                                                    <button
                                                        type="button"
                                                        disabled={busy}
                                                        onClick={() => {
                                                            setEditingId(comment.id)
                                                            setEditBody(comment.body)
                                                        }}
                                                    >
                                                        수정
                                                    </button>

                                                    <button
                                                        type="button"
                                                        className="delete"
                                                        disabled={busy}
                                                        onClick={() =>
                                                            deleteComment(comment.id)
                                                        }
                                                    >
                                                        삭제
                                                    </button>
                                                </>
                                            )}
                                        </div>
                                    </>
                                )}

                                {/* 대댓글 입력 폼 */}
                                {replyTargetId === comment.id && renderForm(
                                    replyBody,
                                    setReplyBody,
                                    submitReply,
                                    '답글을 입력해 주세요.',
                                    '답글 작성',
                                    replyAnonymous,
                                    setReplyAnonymous,
                                )}
                            </li>
                        )
                    })}
                </ul>
            ) : (
                <p className="career-comment-empty">
                    첫 댓글을 남겨 보세요.
                </p>
            )}

            {/* 일반 댓글 입력 폼 */}
            {renderForm(
                body,
                setBody,
                submitComment,
                '댓글을 입력해 주세요.',
                '댓글 작성',
                isAnonymous,
                setIsAnonymous,
            )}
        </section>
    )
}
