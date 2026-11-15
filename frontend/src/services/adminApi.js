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
  /** 확정 참여자가 제출한 모임 활동 기록(최신순)을 조회합니다. */
  meetupXPActivities: (limit = 50) => apiRequest(`${base}/meetup-xp/activities?limit=${limit}`),
  /** 활동 증빙을 검토해 개인 XP를 승인합니다. 지급량은 서버 정책으로 결정됩니다. */
  approveMeetupXP: (recruitId, payload) => apiRequest(`/recruits/${recruitId}/xp/approve`, {
    method: 'POST', body: JSON.stringify(payload),
  }),
  /** 승인한 모임 XP를 사유와 함께 회수합니다. */
  revokeMeetupXP: (recruitId, payload) => apiRequest(`/recruits/${recruitId}/xp/revoke`, {
    method: 'POST', body: JSON.stringify(payload),
  }),
}
