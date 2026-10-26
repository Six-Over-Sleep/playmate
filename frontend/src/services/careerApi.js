
/**
 * PLAYMATE 취업 카테고리 API
 *
 * - 취준 도감
 * - 커리어 톡톡
 * - 현직자 라운지
 * - 커리어 연구소
 *
 * Vite /api 프록시를 사용하므로
 * 실제 Backend 포트는 이 파일에 적지 않습니다.
 */


// =========================================================
// 1. 공통 API 요청 함수
// =========================================================

async function request(url, options = {}) {
    const headers = {
        Accept: 'application/json',
        ...options.headers,
    }

    // 개발·테스트 환경에서만 사용하는 회원 ID
    if (import.meta.env.DEV && import.meta.env.VITE_DEV_MEMBER_ID) {
        headers['X-Dev-Member-ID'] = import.meta.env.VITE_DEV_MEMBER_ID
    }

    const response = await fetch(url, {
        ...options,
        headers,
        credentials: 'include',
    })

    // HTTP 오류 처리
    if (!response.ok) {
        const error = await response.json().catch(() => ({}))

        const message = typeof error.detail === 'string'
            ? error.detail
            : Array.isArray(error.detail)
                ? error.detail
                    .map((item) => item.msg)
                    .filter(Boolean)
                    .join(', ')
                : `API 요청 실패 (${response.status})`

        throw new Error(message)
    }

    // 삭제 성공: 응답 본문 없음
    if (response.status === 204) {
        return null
    }

    return response.json()
}


// =========================================================
// 2. 목록 조회 URL 생성
// =========================================================

function listUrl(base, params) {
    const query = new URLSearchParams()

    Object.entries(params).forEach(([key, value]) => {
        if (
            value !== undefined &&
            value !== null &&
            value !== ''
        ) {
            query.append(key, String(value))
        }
    })

    return query.toString()
        ? `${base}?${query.toString()}`
        : base
}


// =========================================================
// 3. 취준 도감 API
// =========================================================

const REVIEW_URL = '/api/career/reviews'


// 게시글 목록 조회
export function getCareerReviews(params = {}) {
    return request(listUrl(REVIEW_URL, params))
}


// 게시글 상세 조회
export function getCareerReview(postId) {
    return request(`${REVIEW_URL}/${postId}`)
}


// 게시글 등록
export function createCareerReview(data) {
    return request(REVIEW_URL, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
    })
}


// 게시글 수정
export function updateCareerReview(postId, data) {
    return request(`${REVIEW_URL}/${postId}`, {
        method: 'PATCH',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
    })
}


// 게시글 삭제
export function deleteCareerReview(postId) {
    return request(`${REVIEW_URL}/${postId}`, {
        method: 'DELETE',
    })
}


// =========================================================
// 4. 커리어 톡톡 API
// =========================================================

const TALK_URL = '/api/career/talks'


// 게시글 목록 조회
export function getCareerTalks(params = {}) {
    return request(listUrl(TALK_URL, params))
}


// 게시글 상세 조회
export function getCareerTalk(postId) {
    return request(`${TALK_URL}/${postId}`)
}


// 게시글 등록
export function createCareerTalk(data) {
    return request(TALK_URL, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
    })
}


// 게시글 수정
export function updateCareerTalk(postId, data) {
    return request(`${TALK_URL}/${postId}`, {
        method: 'PATCH',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
    })
}


// 게시글 삭제
export function deleteCareerTalk(postId) {
    return request(`${TALK_URL}/${postId}`, {
        method: 'DELETE',
    })
}


// =========================================================
// 5. 현직자 라운지 API
// =========================================================

const LOUNGE_URL = '/api/career/lounges'


// 게시글 목록 조회
export function getCareerLounges(params = {}) {
    return request(listUrl(LOUNGE_URL, params))
}


// 게시글 상세 조회
export function getCareerLounge(postId) {
    return request(`${LOUNGE_URL}/${postId}`)
}


// 게시글 등록
export function createCareerLounge(data) {
    return request(LOUNGE_URL, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
    })
}


// 게시글 수정
export function updateCareerLounge(postId, data) {
    return request(`${LOUNGE_URL}/${postId}`, {
        method: 'PATCH',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
    })
}


// 게시글 삭제
export function deleteCareerLounge(postId) {
    return request(`${LOUNGE_URL}/${postId}`, {
        method: 'DELETE',
    })
}


// =========================================================
// 6. 커리어 연구소 API
// =========================================================

const LAB_URL = '/api/career/labs'


// 6-1. 게시글 목록 조회
export function getCareerLabs(params = {}) {
    return request(listUrl(LAB_URL, params))
}


// 6-2. 게시글 상세 조회
export function getCareerLab(postId) {
    return request(`${LAB_URL}/${postId}`)
}


// 6-3. 게시글 등록
export function createCareerLab(data) {
    return request(LAB_URL, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
    })
}


// 6-4. 게시글 수정
export function updateCareerLab(postId, data) {
    return request(`${LAB_URL}/${postId}`, {
        method: 'PATCH',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
    })
}


// 6-5. 게시글 삭제
export function deleteCareerLab(postId) {
    return request(`${LAB_URL}/${postId}`, {
        method: 'DELETE',
    })
}


// 6-6. 질문 해결 상태 변경
export function resolveCareerLab(postId, isResolved) {
    return request(`${LAB_URL}/${postId}/resolve`, {
        method: 'PATCH',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            is_resolved: isResolved,
        }),
    })
}


// 6-7. 토론 투표
export function voteCareerLab(postId, optionId) {
    return request(`${LAB_URL}/${postId}/votes`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            option_id: optionId,
        }),
    })
}


// =========================================================
// 7. 취업 게시글 4종 공통 - 좋아요·스크랩·댓글
// 취준 도감·커리어 톡톡·현직자 라운지·커리어 연구소 모두 post_id로 요청한다.
// =========================================================

const POST_URL = '/api/career/posts'

// 댓글 수정·삭제는 게시판과 같은 공통 댓글 API를 사용한다.
const COMMENT_URL = '/api/comments'


// 7-1. 좋아요 등록 → { post_id, like_count, liked_by_me }
export function likeCareerPost(postId) {
    return request(`${POST_URL}/${postId}/like`, {
        method: 'PUT',
    })
}


// 7-2. 좋아요 취소 → { post_id, like_count, liked_by_me }
export function unlikeCareerPost(postId) {
    return request(`${POST_URL}/${postId}/like`, {
        method: 'DELETE',
    })
}


// 7-3. 스크랩 등록 → { post_id, scrapped_by_me } (스크랩 수는 제공하지 않음)
export function scrapCareerPost(postId) {
    return request(`${POST_URL}/${postId}/scrap`, {
        method: 'PUT',
    })
}


// 7-4. 스크랩 취소 → { post_id, scrapped_by_me }
export function unscrapCareerPost(postId) {
    return request(`${POST_URL}/${postId}/scrap`, {
        method: 'DELETE',
    })
}


// 7-5. 댓글 목록 조회 (부모 → 대댓글 순서, 삭제된 부모 자리표시 포함)
export function getCareerComments(postId) {
    return request(`${POST_URL}/${postId}/comments`)
}


// 7-6. 댓글·대댓글 작성 (익명 여부 포함)

export function createCareerComment(
    postId,
    body,
    parentCommentId = null,
    isAnonymous = false
) {
    return request(`${POST_URL}/${postId}/comments`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            body,
            parent_comment_id: parentCommentId,
            is_anonymous: isAnonymous,
        }),
    })
}


// 7-7. 댓글 수정
export function updateCareerComment(commentId, body) {
    return request(`${COMMENT_URL}/${commentId}`, {
        method: 'PATCH',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ body }),
    })
}


// 7-8. 댓글 삭제 (응답 본문 없음)
export function deleteCareerComment(commentId) {
    return request(`${COMMENT_URL}/${commentId}`, {
        method: 'DELETE',
    })
}
