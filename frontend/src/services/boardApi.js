const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'
const DEV_MEMBER_ID = import.meta.env.VITE_DEV_MEMBER_ID

async function request(path, options = {}) {
  const headers = { ...options.headers }
  if (!(options.body instanceof FormData)) headers['Content-Type'] = 'application/json'
  if (DEV_MEMBER_ID) headers['X-Dev-Member-ID'] = DEV_MEMBER_ID
  let response
  try {
    response = await fetch(`${API_BASE}${path}`, { ...options, headers })
  } catch {
    throw new Error('백엔드에 연결할 수 없습니다. FastAPI 서버와 API 주소를 확인해주세요.')
  }
  if (response.status === 204) return null
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.detail || `API 요청 실패 (${response.status})`)
  return data
}

export const boardApi = {
  boards: () => request('/boards'),
  createBoard: (payload) => request('/boards', { method: 'POST', body: JSON.stringify(payload) }),
  posts: (boardId, q = '') => request(`/boards/${boardId}/posts?sort=latest&q=${encodeURIComponent(q)}`),
  post: (boardId, postId) => request(`/boards/${boardId}/posts/${postId}`),
  createPost: (boardId, payload) => {
    const form = new FormData()
    form.append('title', payload.title)
    form.append('body', payload.body)
    payload.images.forEach((image) => form.append('images', image))
    return request(`/boards/${boardId}/posts`, { method: 'POST', body: form })
  },
  updatePost: (boardId, postId, payload) => request(`/boards/${boardId}/posts/${postId}`, { method: 'PATCH', body: JSON.stringify({ title: payload.title, body: payload.body }) }),
  deletePost: (boardId, postId) => request(`/boards/${boardId}/posts/${postId}`, { method: 'DELETE' }),
  comments: (boardId, postId) => request(`/boards/${boardId}/posts/${postId}/comments`),
  createComment: (boardId, postId, body) => request(`/boards/${boardId}/posts/${postId}/comments`, { method: 'POST', body: JSON.stringify({ body }) }),
  updateComment: (commentId, body) => request(`/comments/${commentId}`, { method: 'PATCH', body: JSON.stringify({ body }) }),
  deleteComment: (commentId) => request(`/comments/${commentId}`, { method: 'DELETE' }),
}

export function mediaUrl(path) {
  if (!path || /^https?:/.test(path)) return path
  return `${new URL(API_BASE).origin}${path}`
}
