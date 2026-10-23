
import { useEffect, useState } from 'react'
import { getMySkills } from '../../services/mypageApi'

// 스킬별 표시 이름 및 색상
const SKILL_INFO = {
  PYTHON: { name: 'Python', color: '#3676ab' },
  SQL: { name: 'SQL', color: '#d28a3c' },
  GIT: { name: 'Git / GitHub', color: '#df7352' },
  REACT: { name: 'React', color: '#409ec5' },
  LANGCHAIN: { name: 'LangChain', color: '#659a69' },
}

export default function SkillLevels() {
  const [skills, setSkills] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    getMySkills()
      .then((data) => {
        setSkills(Array.isArray(data) ? data : data.skills ?? [])
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return <p>스킬 정보를 불러오는 중...</p>
  }

  if (error) {
    return <p>스킬 레벨 조회 실패: {error}</p>
  }

  return (
    <div className="mypage-skills">
      <div className="mypage-skills-heading">
        <h2>스킬 레벨</h2>
        <span>5개 스킬</span>
      </div>

      {skills.length === 0 ? (
        <p>스킬 정보가 없습니다.</p>
      ) : (
        <div className="mypage-skills-grid">
          {skills.map((skill) => {
            const code = skill.skill_code?.toUpperCase()
            const info = SKILL_INFO[code] || {
              name: code || '기타 스킬',
              color: '#7958ce',
            }

            const progress = Math.min(
              100,
              Math.max(0, skill.progress_percent ?? 0)
            )

            const isMaxLevel = skill.next_level_xp == null

            return (
              <div className="mypage-skill-card" key={code}>
                <div className="mypage-skill-top">
                  <strong>{info.name}</strong>
                  <span>LV. {skill.level}</span>
                </div>

                <div className="mypage-skill-xp">
                  <span>스킬 경험치</span>
                  <span>
                    {skill.total_xp} XP
                    {!isMaxLevel && ` / ${skill.next_level_xp} XP`}
                  </span>
                </div>

                <div
                  className="mypage-skill-progress"
                  role="progressbar"
                  aria-label={`${info.name} 레벨 진행률`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={progress}
                >
                  <div
                    className="mypage-skill-progress-fill"
                    style={{
                      width: `${progress}%`,
                      backgroundColor: info.color,
                    }}
                  />
                </div>

                <p className="mypage-skill-remaining">
                  {isMaxLevel
                    ? '최고 레벨 달성'
                    : `다음 레벨까지 ${skill.remaining_xp} XP`}
                </p>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
