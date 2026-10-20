import { apiRequest } from './apiClient'

// 로그인 세션 쿠키를 포함한 모임 API 요청
export const meetupApi = {
  // 참여 인원수를 포함한 모임 목록 조회
  list: () =>
    apiRequest('/recruits', {
      credentials: 'include',
    }),

  // 모임 상세 조회
  detail: (id) =>
    apiRequest(`/recruits/${id}`, {
      credentials: 'include',
    }),

  // 모임 등록
  create: (payload) =>
    apiRequest('/recruits', {
      method: 'POST',
      credentials: 'include',
      body: JSON.stringify(payload),
    }),

  // 모임 정보 수정
  update: (id, payload) =>
    apiRequest(`/recruits/${id}`, {
      method: 'PATCH',
      credentials: 'include',
      body: JSON.stringify(payload),
    }),

  // 모임 삭제
  remove: (id) =>
    apiRequest(`/recruits/${id}`, {
      method: 'DELETE',
      credentials: 'include',
    }),

  // 모임 참여
  join: (id) =>
    apiRequest(`/recruits/${id}/join`, {
      method: 'POST',
      credentials: 'include',
    }),

  // 모임 참여 취소
  cancelJoin: (id) =>
    apiRequest(`/recruits/${id}/join`, {
      method: 'DELETE',
      credentials: 'include',
    }),

  // 참여 멤버 목록 조회
  members: (id) =>
    apiRequest(`/recruits/${id}/members`, {
      credentials: 'include',
    }),

  // 상세 화면의 참여 인원 조회
  count: (id) =>
    apiRequest(`/recruits/${id}/count`, {
      credentials: 'include',
    }),
}
