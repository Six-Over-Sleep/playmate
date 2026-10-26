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
    return value ? new Date(value).toLocaleString('ko-KR') : ''
}


/**
 * 취업 게시글 4종 상세 하단의 좋아요·스크랩·댓글 영역.
 *
 * - 좋아요·스크랩은 서버 응답 값으로 상위 상세 state를 갱신한다. (onChange)
 * - 댓글은 작성·수정·삭제 후 서버에서 다시 조회한다.
 *   삭제된 부모 댓글의 자리표시 여부도 서버 목록 응답을 그대로 따른다.
 * - 대댓글은 1단계까지만 허용되므로 최상위 댓글에만 답글 버튼을 둔다.
 */
export default function CareerReactions({ post, onChange }) {
    const [comments, setComments] = useState([])
    const [busy, setBusy] = useState(false)
    const [error, setError] = useState('')
    const [body, setBody] = useState('')
    const [replyTargetId, setReplyTargetId] = useState(null)
    const [replyBody, setReplyBody] = useState('')
    const [editingId, setEditingId] = useState(null)
    const [editBody, setEditBody] = useState('')
    const mutationLock = useRef(false)

    // 상세 글이 바뀌면 해당 글의 댓글을 서버에서 받아온다.
    useEffect(() => {
        let canceled = false

        getCareerComments(post.id)
            .then((data) => {
                if (!canceled) setComments(Array.isArray(data) ? data : [])
            })
            .catch((cause) => {
                if (!canceled) setError(`댓글 조회 실패: ${cause.message}`)
            })

        return () => { canceled = true }
    }, [post.id])

    async function loadComments() {
        const data = await getCareerComments(post.id)
        setComments(Array.isArray(data) ? data : [])
    }

    // 연속 클릭을 막고 실패 메시지를 표시하는 공통 처리. 성공하면 true를 반환한다.
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

    function toggleScrap() {
        return mutate(async () => {
            const result = post.scrapped_by_me
                ? await unscrapCareerPost(post.id)
                : await scrapCareerPost(post.id)

            onChange({ scrapped_by_me: result.scrapped_by_me })
        }, '스크랩 처리 실패')
    }

    function addComment(text, parentCommentId = null) {
        return mutate(async () => {
            await createCareerComment(post.id, text, parentCommentId)
            await loadComments()
        }, '댓글 작성 실패')
    }

    function editComment(commentId, text) {
        return mutate(async () => {
            await updateCareerComment(commentId, text)
            await loadComments()
        }, '댓글 수정 실패')
    }

    async function deleteComment(commentId) {
        if (!window.confirm('이 댓글을 삭제할까요?')) return
        await mutate(async () => {
            await deleteCareerComment(commentId)
            await loadComments()
        }, '댓글 삭제 실패')
    }

    async function submitComment(event) {
        event.preventDefault()
        if (!body.trim()) return
        if (await addComment(body.trim())) setBody('')
    }

    async function submitReply(event) {
        event.preventDefault()
        if (!replyBody.trim()) return
        if (await addComment(replyBody.trim(), replyTargetId)) {
            setReplyTargetId(null)
            setReplyBody('')
        }
    }

    async function saveEdit(commentId) {
        if (!editBody.trim()) return
        if (await editComment(commentId, editBody.trim())) setEditingId(null)
    }

    function toggleReply(commentId) {
        setReplyTargetId((current) => (current === commentId ? null : commentId))
        setReplyBody('')
    }

    // 일반 댓글과 답글이 같은 입력 모양을 사용한다.
    function renderForm(value, setValue, onSubmit, placeholder, label) {
        return (
            <form className="career-comment-form" onSubmit={onSubmit}>
                <textarea
                    aria-label={placeholder}
                    rows={3}
                    maxLength={2000}
                    value={value}
                    disabled={busy}
                    placeholder={placeholder}
                    onChange={(event) => setValue(event.target.value)}
                />
                <button type="submit" disabled={busy || !value.trim()}>
                    {label}
                </button>
            </form>
        )
    }

    // 삭제 자리표시는 실제 댓글이 아니므로 개수에서 제외한다.
    const commentCount = comments.filter((comment) => !comment.is_deleted).length

    return (
        <section className="career-reactions">
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

            {error && <p className="career-reaction-error" role="alert">{error}</p>}

            <h4>댓글 {commentCount}</h4>

            {comments.length > 0 ? (
                <ul className="career-comment-list">
                    {comments.map((comment) => {
                        const isReply = comment.parent_comment_id != null

                        // 삭제된 부모 댓글은 살아 있는 대댓글이 있을 때만 서버가 자리표시로 내려준다.
                        if (comment.is_deleted) {
                            return (
                                <li key={comment.id} className="career-comment deleted">
                                    <p>삭제된 댓글입니다.</p>
                                </li>
                            )
                        }

                        return (
                            <li
                                key={comment.id}
                                className={isReply ? 'career-comment reply' : 'career-comment'}
                            >
                                <div className="career-comment-head">
                                    <strong>{comment.author_name}</strong>
                                    <span>{formatCommentDate(comment.created_at)}</span>
                                </div>

                                {editingId === comment.id ? (
                                    <div className="career-comment-edit">
                                        <textarea
                                            aria-label="댓글 수정 내용"
                                            rows={3}
                                            maxLength={2000}
                                            value={editBody}
                                            disabled={busy}
                                            onChange={(event) => setEditBody(event.target.value)}
                                        />
                                        <div className="career-comment-actions">
                                            <button
                                                type="button"
                                                disabled={busy || !editBody.trim()}
                                                onClick={() => saveEdit(comment.id)}
                                            >
                                                저장
                                            </button>
                                            <button
                                                type="button"
                                                disabled={busy}
                                                onClick={() => setEditingId(null)}
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
                                                    onClick={() => toggleReply(comment.id)}
                                                >
                                                    {replyTargetId === comment.id ? '답글 취소' : '답글'}
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
                                                        onClick={() => deleteComment(comment.id)}
                                                    >
                                                        삭제
                                                    </button>
                                                </>
                                            )}
                                        </div>
                                    </>
                                )}

                                {replyTargetId === comment.id && renderForm(
                                    replyBody,
                                    setReplyBody,
                                    submitReply,
                                    '답글을 입력해 주세요.',
                                    '답글 작성',
                                )}
                            </li>
                        )
                    })}
                </ul>
            ) : (
                <p className="career-comment-empty">첫 댓글을 남겨 보세요.</p>
            )}

            {renderForm(body, setBody, submitComment, '댓글을 입력해 주세요.', '댓글 작성')}
        </section>
    )
}
