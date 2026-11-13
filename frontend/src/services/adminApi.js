import { apiRequest } from './apiClient'

const base = '/admin'

export const adminApi = {
  dashboard: () => apiRequest(`${base}/dashboard`),
  notices: (page = 1, q = '') => apiRequest(`${base}/notices?page=${page}&q=${encodeURIComponent(q)}`),
  createNotice: (data) => apiRequest(`${base}/notices`, {
    method: 'POST', body: JSON.stringify(data),
  }),
  updateNotice: (id, data) => apiRequest(`${base}/notices/${id}`, {
    method: 'PATCH', body: JSON.stringify(data),
  }),
  deleteNotice: (id) => apiRequest(`${base}/notices/${id}`, { method: 'DELETE' }),
  posts: (q = '', page = 1) => apiRequest(`${base}/posts?q=${encodeURIComponent(q)}&page=${page}`),
  setVisibility: (id, hidden) => apiRequest(`${base}/posts/${id}/visibility`, {
    method: 'PATCH', body: JSON.stringify({ hidden }),
  }),
  /** 신고받은 글과 신고별 상세 사유를 관리자에게 조회합니다. */
  reportedPosts: (page = 1, q = '', status = 'all') =>
    apiRequest(`${base}/board-reports/details?page=${page}&q=${encodeURIComponent(q)}&status_filter=${status}`),
  members: (page = 1, q = '') => apiRequest(`${base}/members?page=${page}&q=${encodeURIComponent(q)}`),
}
