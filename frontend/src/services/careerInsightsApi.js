export async function fetchInsight(path, params = {}, signal) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => { if (value) query.set(key, value) })
  const response = await fetch(`/api/career/insights/db/${path}${query.size ? `?${query}` : ''}`, { credentials: 'include', signal })
  if (!response.ok) throw new Error(`통계 API 조회 실패 (${response.status})`)
  return response.json()
}
