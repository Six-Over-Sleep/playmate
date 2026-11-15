import { useEffect, useState } from 'react'
import { getMyXPHistoryPage } from '../../services/mypageApi'
import { xpActivityLabel } from '../../utils/xpLabels'

const PAGE_SIZE = 10

function formatDate(date) {
  return date ? String(date).replace('T', ' ').slice(0, 16) : '날짜 정보 없음'
}

// 페이지가 많을 때도 페이지 버튼을 최대 7개만 표시합니다.
function getPageNumbers(page, totalPages) {
  const first = Math.max(1, Math.min(page - 3, totalPages - 6))
  const last = Math.min(totalPages, first + 6)
  return Array.from({ length: Math.max(0, last - first + 1) }, (_, i) => first + i)
}

export default function MyPageXPLog() {
  const [history, setHistory] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')

    getMyXPHistoryPage(page, PAGE_SIZE)
      .then((data) => {
        if (!active) return
        if (!data || !Array.isArray(data.items)) {
          throw new Error('XP 이력 응답 형식이 올바르지 않습니다.')
        }
        setHistory(data.items)
        setTotal(Number(data.total) || 0)
      })
      .catch((cause) => {
        if (active) {
          setHistory([])
          setError(cause.message || 'XP 이력을 불러오지 못했습니다.')
        }
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => { active = false }
  }, [page, refresh])

  const totalPages = Math.ceil(total / PAGE_SIZE)
  const startNumber = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1
  const endNumber = Math.min(page * PAGE_SIZE, total)

  return (
    <div className="mypage-xplog">
      <div className="mypage-xplog-heading">
        <div>
          <h3>XP 획득 및 회수 내역</h3>
          <p>전체 기록을 10건씩 조회합니다. {total > 0 && `(${startNumber}–${endNumber} / 총 ${total.toLocaleString('ko-KR')}건)`}</p>
        </div>
        <button type="button" onClick={() => setRefresh((n) => n + 1)} disabled={loading}>
          새로고침
        </button>
      </div>

      {loading ? (
        <p className="mypage-xplog-empty">XP 이력을 불러오는 중...</p>
      ) : error ? (
        <p className="mypage-xplog-error" role="alert">{error}</p>
      ) : history.length === 0 ? (
        <p className="mypage-xplog-empty">아직 XP 획득·회수 이력이 없습니다.</p>
      ) : (
        <ul className="mypage-xplog-list">
          {history.map((item) => {
            const amount = Number(item.xp_change) || 0
            const label = xpActivityLabel(item.activity_type)
            return (
              <li key={item.history_id}>
                <div>
                  <strong>{amount < 0 ? `${label} · 회수` : label}</strong>
                  <span>{formatDate(item.created_at || item.activity_date)}</span>
                </div>
                <strong className={amount < 0 ? 'mypage-xplog-negative' : 'mypage-xplog-positive'}>
                  {amount > 0 ? '+' : ''}{amount.toLocaleString('ko-KR')} XP
                </strong>
              </li>
            )
          })}
        </ul>
      )}

      {!loading && !error && totalPages > 1 && (
        <nav className="mypage-pagination mypage-xplog-pagination" aria-label="XP 이력 페이지 이동">
          <button type="button" onClick={() => setPage(1)} disabled={page === 1}>
            처음
          </button>
          <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>
            이전
          </button>
          {getPageNumbers(page, totalPages).map((number) => (
            <button
              type="button"
              key={number}
              className={page === number ? 'active' : ''}
              aria-current={page === number ? 'page' : undefined}
              aria-label={`XP 이력 ${number}페이지`}
              onClick={() => setPage(number)}
            >
              {number}
            </button>
          ))}
          <button type="button" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page === totalPages}>
            다음
          </button>
          <button type="button" onClick={() => setPage(totalPages)} disabled={page === totalPages}>
            마지막
          </button>
        </nav>
      )}
    </div>
  )
}
