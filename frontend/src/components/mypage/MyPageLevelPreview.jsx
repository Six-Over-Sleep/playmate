import { useEffect, useState } from 'react'
import { getMyLevel } from '../../services/mypageApi'

// 상단 프로필 오른쪽의 간결한 종합 레벨 미리보기.
// 전체 상세는 좌측 메뉴의 '나의 레벨'에서 확인합니다.
export default function MyPageLevelPreview() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    getMyLevel()
      .then((result) => { if (active) setData(result) })
      .catch((cause) => { if (active) setError(cause.message || '레벨 조회 실패') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  if (loading) return <div className="mypage-level-preview"><h2>🏆 종합 레벨</h2><p>레벨 정보를 불러오는 중...</p></div>
  if (error || !data) return <div className="mypage-level-preview"><h2>🏆 종합 레벨</h2><p role="alert">{error || '레벨 정보가 없습니다.'}</p></div>

  const progress = Math.min(100, Math.max(0, Number(data.progress_percent) || 0))
  const isMaxLevel = data.next_level_xp == null

  return (
    <div className="mypage-level-preview">
      <div className="mypage-level-preview-heading">
        <h2>🏆 종합 레벨</h2>
        <span>LEVEL {data.level}</span>
      </div>
      <div className="mypage-level-preview-amount">
        <strong>{Number(data.total_xp || 0).toLocaleString('ko-KR')} <small>XP</small></strong>
        <p>{isMaxLevel ? '최고 레벨 달성' : `다음 레벨까지 ${Number(data.remaining_xp || 0).toLocaleString('ko-KR')} XP`}</p>
      </div>
      <div
        className="mypage-progress-track"
        role="progressbar"
        aria-label="종합 레벨 진행률"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress}
      >
        <div className="mypage-progress-fill" style={{ width: `${progress}%` }} />
      </div>
      <p className="mypage-level-preview-tip">스킬 레벨과 XP 이력은 아래 '나의 레벨' 메뉴에서 확인하세요.</p>
    </div>
  )
}
