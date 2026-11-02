import { apiRequest } from './apiClient'

const base = '/admin'

export const adminApi = {
  dashboard: () => apiRequest(`${base}/dashboard`),
  notices: () => apiRequest(`${base}/notices`),
  createNotice: (data) => apiRequest(`${base}/notices`, {
    method: 'POST', body: JSON.stringify(data),
  }),
  updateNotice: (id, data) => apiRequest(`${base}/notices/${id}`, {
    method: 'PATCH', body: JSON.stringify(data),
  }),
  deleteNotice: (id) => apiRequest(`${base}/notices/${id}`, { method: 'DELETE' }),
  posts: (q = '') => apiRequest(`${base}/posts?q=${encodeURIComponent(q)}`),
  setVisibility: (id, hidden) => apiRequest(`${base}/posts/${id}/visibility`, {
    method: 'PATCH', body: JSON.stringify({ hidden }),
  }),
  /** 신고받은 글과 신고별 상세 사유를 관리자에게 조회합니다. */
  reportedPosts: () => apiRequest(`${base}/board-reports/details`),
  members: () => apiRequest(`${base}/members`),
}
