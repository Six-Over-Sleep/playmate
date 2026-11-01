import { useEffect, useState } from 'react'
import { getMyActivitySummary } from '../../services/mypageApi'

const SUMMARY_ITEMS = [
  { key: 'posts_count', label: '작성 게시글', unit: '개' },
  { key: 'comments_count', label: '작성 댓글', unit: '개' },
  { key: 'scraps_count', label: '스크랩', unit: '개' },
  { key: 'meetups_count', label: '참여 모임', unit: '개' },
  { key: 'total_xp', label: '종합 XP', unit: 'XP' },
]

export default function MyPageActivityOverview() {
  const [summary, setSummary] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError('')

    getMyActivitySummary()
      .then((data) => {
        if (active) setSummary(data)
      })
      .catch((cause) => {
        if (active) setError(cause.message || '활동 요약을 불러오지 못했습니다.')
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => { active = false }
  }, [reload])

  return (
    <section className="mypage-overview" aria-labelledby="mypage-overview-heading">
      <div className="mypage-overview-heading">
        <div>
          <h3 id="mypage-overview-heading">활동 요약</h3>
          <p>지금까지 PLAYMATE에서 기록한 활동입니다.</p>
        </div>
        <button type="button" onClick={() => setReload((n) => n + 1)} disabled={loading}>
          새로고침
        </button>
      </div>
      {error && <p className="mypage-overview-message" role="alert">{error}</p>}
      {summary ? (
        <div className="mypage-overview-grid" aria-busy={loading}>
          {SUMMARY_ITEMS.map((item) => (
            <div className="mypage-overview-stat" key={item.key}>
              <span>{item.label}</span>
              <strong>
                {Number(summary[item.key] ?? 0).toLocaleString('ko-KR')}
                <small>{item.unit}</small>
              </strong>
            </div>
          ))}
        </div>
      ) : (
        <p className="mypage-overview-message" role="status">
          {loading ? '활동 요약을 불러오는 중...' : '활동 요약을 표시할 수 없습니다.'}
        </p>
      )}
    </section>
  )
}
