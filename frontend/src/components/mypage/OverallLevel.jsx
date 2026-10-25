
import { useEffect, useState } from 'react'
import { getMyLevel } from '../../services/mypageApi'

export default function OverallLevel() {
  const [levelData, setLevelData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    getMyLevel()
      .then(setLevelData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return <p>레벨 정보를 불러오는 중...</p>
  }

  if (error) {
    return <p>레벨 조회 실패: {error}</p>
  }

  if (!levelData) {
    return <p>레벨 정보가 없습니다.</p>
  }

  const {
    level,
    total_xp,
    next_level_xp,
    remaining_xp,
    progress_percent,
  } = levelData

  const progress = Math.min(
    100,
    Math.max(0, progress_percent ?? 0)
  )

  const isMaxLevel = next_level_xp == null

  return (
    <div className="mypage-overall">
      <div className="mypage-level-heading">
        <h2>🏆 종합 레벨</h2>
        <span className="mypage-level-badge">
          LEVEL {level}
        </span>
      </div>

      <div className="mypage-level-info">
        <div>
          <strong>LV. {level}</strong>
          <p>
            {isMaxLevel
              ? '최고 레벨에 도달했어요!'
              : `다음 레벨까지 ${remaining_xp} XP`}
          </p>
        </div>

        <span className="mypage-xp-text">
          {total_xp} XP
          {!isMaxLevel && ` / ${next_level_xp} XP`}
        </span>
      </div>

      <div
        className="mypage-progress-track"
        role="progressbar"
        aria-label="종합 레벨 진행률"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress}
      >
        <div
          className="mypage-progress-fill"
          style={{ width: `${progress}%` }}
        />
      </div>

      <p className="mypage-level-guide">
        게시글 작성, 댓글, 출석 활동으로 경험치를 획득할 수 있어요.
      </p>
    </div>
  )
}
