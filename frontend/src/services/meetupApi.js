import { apiRequest } from './apiClient'

export const meetupApi = {
  list: () =>
    apiRequest('/recruits'),

  detail: (id) =>
    apiRequest(`/recruits/${id}`),

  create: (payload) =>
    apiRequest('/recruits', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  update: (id, payload) =>
    apiRequest(`/recruits/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  // 기존 DELETE /recruits/{id}는 게시글 논리 삭제용이다.
  // 프로젝트 운영 취소는 cancelProject()를 사용한다.
  remove: (id) =>
    apiRequest(`/recruits/${id}`, {
      method: 'DELETE',
    }),

  // 프로젝트는 신청서 payload를 전달하고,
  // 스터디는 본문 없이 신청할 수 있다.
  join: (id, payload = null) =>
    apiRequest(`/recruits/${id}/join`, {
      method: 'POST',
      ...(payload != null
        ? {
            body: JSON.stringify(payload),
          }
        : {}),
    }),

  // 시작 전 신청 취소와 시작 후 자발적 중도이탈은
  // 동일한 DELETE /join을 사용하고 서버가 상태를 구분한다.
  cancelJoin: (id) =>
    apiRequest(`/recruits/${id}/join`, {
      method: 'DELETE',
    }),

  members: (id) =>
    apiRequest(`/recruits/${id}/members`),

  count: (id) =>
    apiRequest(`/recruits/${id}/count`),

  // 프로젝트 일정 연장
  extendProject: (id, payload) =>
    apiRequest(`/recruits/${id}/extension`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // 2회 연장 후 필수 기술만 부족한 경우
  // 현재 확정 구성으로 예정 시각에 시작하도록 결정
  chooseExceptionStart: (id, payload) =>
    apiRequest(`/recruits/${id}/exception-start`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // 팀장의 시작 전 프로젝트 운영 취소
  cancelProject: (id, payload) =>
    apiRequest(`/recruits/${id}/cancel`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // 진행 중 1인 프로젝트의 중도 종료
  abortProject: (id, payload) =>
    apiRequest(`/recruits/${id}/abort`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
}
