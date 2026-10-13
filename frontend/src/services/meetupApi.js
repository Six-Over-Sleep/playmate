const API_BASE =
  import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api'

const DEV_MEMBER_ID = import.meta.env.VITE_DEV_MEMBER_ID

function getErrorMessage(data) {
  const detail = data?.detail

  if (typeof detail === 'string') {
    return detail
  }

  if (Array.isArray(detail)) {
    return detail
      .map((item) => item?.msg || item?.message || JSON.stringify(item))
      .join(' / ')
  }

  if (detail && typeof detail === 'object') {
    return detail.message || detail.msg || JSON.stringify(detail)
  }

  return '요청 처리 중 오류가 발생했습니다.'
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(DEV_MEMBER_ID && {
        'X-Dev-Member-ID': DEV_MEMBER_ID,
      }),
      ...options.headers,
    },
    ...options,
  })

  if (!response.ok) {
    const data = await response.json().catch(() => null)
    throw new Error(getErrorMessage(data))
  }

  if (response.status === 204) return null
  return response.json()
}

export const meetupApi = {
  list: () =>
    request('/recruits'),

  detail: (id) =>
    request(`/recruits/${id}`),

  create: (payload) =>
    request('/recruits', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  update: (id, payload) =>
    request(`/recruits/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),

  remove: (id) =>
    request(`/recruits/${id}`, {
      method: 'DELETE',
    }),

  join: (id) =>
    request(`/recruits/${id}/join`, {
      method: 'POST',
    }),

  cancelJoin: (id) =>
    request(`/recruits/${id}/join`, {
      method: 'DELETE',
    }),

  members: (id) =>
    request(`/recruits/${id}/members`),

  count: (id) =>
    request(`/recruits/${id}/count`),
}