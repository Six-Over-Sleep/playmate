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
  members: () => apiRequest(`${base}/members`),
}
