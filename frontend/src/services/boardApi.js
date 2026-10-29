import { apiRequest } from './apiClient'
import { resolveMediaUrl } from '../config/api'

/** 기존 게시판 개발용 헤더만 연결한다. 인증·모임에는 이 헤더를 강제하지 않는다. */
function request(path, options = {}) {
  const headers = new Headers(options.headers)
  const devMemberId = import.meta.env.VITE_DEV_MEMBER_ID
  if (devMemberId) headers.set('X-Dev-Member-ID', devMemberId)
  return apiRequest(path, { ...options, headers })
}

/** endpoint와 payload만 정의한다. 조회 options는 취소 신호 전달에 사용한다. */
export const boardApi = {
  /** 게시판 목록을 조회한다. options로 AbortSignal 등 조회 옵션을 전달할 수 있다. */
  boards(options = {}) {
    return request('/boards', options)
  },

  /** 이름·소개·생성 사유를 JSON으로 보내고 생성된 게시판을 반환한다. */
  createBoard(payload) {
    return request('/boards', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  /** 게시판 글 목록을 검색한다. 서버 정렬 계약은 latest를 유지하고 검색어는 인코딩한다. */
  posts(boardId, query = '', options = {}) {
    return request(
      `/boards/${boardId}/posts?sort=latest&q=${encodeURIComponent(query)}`,
      options,
    )
  },

  /** 좋아요 기준으로 자동 선정된 읽기 전용 게시글 목록 */
  featuredPosts(kind, query = '', options = {}) {
    return request(
      `/boards/featured/${kind}/posts?q=${encodeURIComponent(query)}`,
      options,
    )
  },

  /** 지정한 게시판에 속한 글의 본문·소유자 여부·이미지 정보를 조회한다. */
  post(boardId, postId, options = {}) {
    return request(`/boards/${boardId}/posts/${postId}`, options)
  },

  /** 제목·본문과 파일을 FormData로 보낸다. 이미지 필드 이름 images는 서버 계약을 유지한다. */
  createPost(boardId, payload) {
    const form = new FormData()
    form.append('title', payload.title)
    form.append('body', payload.body)
    payload.images.forEach((image) => form.append('images', image))
    return request(`/boards/${boardId}/posts`, { method: 'POST', body: form })
  },

  /** 기존 API가 지원하는 제목·본문만 수정하며 이미지 수정 기능은 추가하지 않는다. */
  updatePost(boardId, postId, payload) {
    return request(`/boards/${boardId}/posts/${postId}`, {
      method: 'PATCH',
      body: JSON.stringify({ title: payload.title, body: payload.body }),
    })
  },

  /** 글 삭제를 요청한다. 서버가 204를 반환하면 공용 client의 결과는 null이다. */
  deletePost(boardId, postId) {
    return request(`/boards/${boardId}/posts/${postId}`, { method: 'DELETE' })
  },

  /** 상세 글의 댓글 목록을 서버 순서대로 조회한다. options로 요청 취소를 지원한다. */
  comments(boardId, postId, options = {}) {
    return request(`/boards/${boardId}/posts/${postId}/comments`, options)
  },

  /**
   * 댓글 본문을 저장하고 생성 응답을 반환해 화면에서 추가 GET 없이 반영하게 한다.
   * parentCommentId를 주면 그 댓글의 대댓글로 저장한다. (서버는 1단계 대댓글만 허용)
   */
  createComment(boardId, postId, body, parentCommentId = null) {
    return request(`/boards/${boardId}/posts/${postId}/comments`, {
      method: 'POST',
      body: JSON.stringify({ body, parent_comment_id: parentCommentId }),
    })
  },

  /** 게시글 좋아요를 등록하고 { post_id, like_count, liked_by_me }를 반환한다. 반복 요청해도 한 번만 반영된다. */
  likePost(boardId, postId) {
    return request(`/boards/${boardId}/posts/${postId}/like`, { method: 'PUT' })
  },

  /** 게시글 좋아요를 취소하고 같은 형태의 현재 상태를 반환한다. */
  unlikePost(boardId, postId) {
    return request(`/boards/${boardId}/posts/${postId}/like`, { method: 'DELETE' })
  },

  /** 게시글 스크랩을 등록하고 { post_id, scrapped_by_me }를 반환한다. 스크랩 수는 제공하지 않는다. */
  scrapPost(boardId, postId) {
    return request(`/boards/${boardId}/posts/${postId}/scrap`, { method: 'PUT' })
  },

  /** 게시글 스크랩을 취소하고 같은 형태의 현재 상태를 반환한다. */
  unscrapPost(boardId, postId) {
    return request(`/boards/${boardId}/posts/${postId}/scrap`, { method: 'DELETE' })
  },

  /** 댓글 id와 수정 본문을 보내며 수정된 댓글을 반환한다. */
  updateComment(commentId, body) {
    return request(`/comments/${commentId}`, {
      method: 'PATCH',
      body: JSON.stringify({ body }),
    })
  },

  /** 댓글 삭제를 요청한다. 삭제 성공의 빈 응답 처리 방식은 글 삭제와 동일하다. */
  deleteComment(commentId) {
    return request(`/comments/${commentId}`, { method: 'DELETE' })
  },
}

/** 기존 화면의 mediaUrl import를 유지하며 공통 이미지 주소 설정에 연결한다. */
export function mediaUrl(path) {
  return resolveMediaUrl(path)
}
