import { apiRequest } from './apiClient'

export const meetupApi = {
  list: () =>
    apiRequest('/recruits', {
      credentials: 'include',
    }),

  detail: (id) =>
    apiRequest(`/recruits/${id}`, {
      credentials: 'include',
    }),

  create: (payload) =>
    apiRequest('/recruits', {
      method: 'POST',
      credentials: 'include',
      body: JSON.stringify(payload),
    }),

  update: (id, payload) =>
    apiRequest(`/recruits/${id}`, {
      method: 'PATCH',
      credentials: 'include',
      body: JSON.stringify(payload),
    }),

  remove: (id) =>
    apiRequest(`/recruits/${id}`, {
      method: 'DELETE',
      credentials: 'include',
    }),

  join: (id) =>
    apiRequest(`/recruits/${id}/join`, {
      method: 'POST',
      credentials: 'include',
    }),

  cancelJoin: (id) =>
    apiRequest(`/recruits/${id}/join`, {
      method: 'DELETE',
      credentials: 'include',
    }),

  members: (id) =>
    apiRequest(`/recruits/${id}/members`, {
      credentials: 'include',
    }),

  count: (id) =>
    apiRequest(`/recruits/${id}/count`, {
      credentials: 'include',
    }),
}
