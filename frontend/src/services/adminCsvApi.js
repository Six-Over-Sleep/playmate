import { getApiUrl } from '../config/api'

export async function downloadAdminUsageCsv(
  days, kind, startDate, endDate,
) {
  if (![7, 30].includes(days) || !['members', 'boards'].includes(kind)) {
    throw new Error('CSV ???? ??? ???? ????.')
  }

  const query = new URLSearchParams({
    days: String(days),
    kind,
  })

  const validDate = /^\d{4}-\d{2}-\d{2}$/

  if (startDate || endDate) {
    if (
      !validDate.test(startDate || '') ||
      !validDate.test(endDate || '') ||
      startDate > endDate
    ) {
      throw new Error('Invalid CSV date range')
    }

    query.set('start_date', startDate)
    query.set('end_date', endDate)
  }

  let response
  try {
    response = await fetch(
      getApiUrl(`/admin/usage/export?${query}`),
      {
        method: 'GET',
        credentials: 'include',
        headers: { Accept: 'text/csv' },
        cache: 'no-store',
      },
    )
  } catch {
    throw new Error('CSV ??? ??? ? ????.')
  }

  if (!response.ok) {
    if ([401, 403].includes(response.status)) {
      window.dispatchEvent(
        new CustomEvent('playmate:admin-auth-error', {
          detail: { status: response.status },
        }),
      )
      throw new Error('??? ??? ?? ?? ??? ??????.')
    }

    let detail = ''
    try {
      const data = await response.json()
      if (typeof data?.detail === 'string') {
        detail = data.detail
      }
    } catch {
      // A non-JSON error must not be treated as CSV.
    }

    throw new Error(
      detail || `CSV ????? ??????. (${response.status})`,
    )
  }

  const contentType = response.headers.get('content-type') || ''
  if (!contentType.toLowerCase().includes('text/csv')) {
    throw new Error('???? ??? CSV ??? ???? ?????.')
  }

  const blob = await response.blob()
  if (blob.size === 0) {
    throw new Error('???? ??? ?? ????.')
  }

  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')

  link.href = objectUrl
  const period = startDate && endDate
    ? `${startDate}_${endDate}`
    : `${days}d`
  link.download = `playmate_usage_${kind}_${period}.csv`

  document.body.appendChild(link)

  try {
    link.click()
  } finally {
    link.remove()
    // Give the browser time to start the download before revocation.
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000)
  }
}
