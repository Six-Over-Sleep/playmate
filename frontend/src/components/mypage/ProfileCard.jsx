
import { useEffect, useState } from 'react'
import {
  getMyProfile,
  updateMyNickname,
} from '../../services/mypageApi'

const COURSE_NAMES = {
  'family-ai': 'SK네트웍스 Family AI 캠프',
  'multi-agent': '멀티 에이전트 AI 오케스트레이션 캠프',
  'data-engineering': 'AI Ready 데이터 엔지니어링 캠프',
  'data-ml': '데이터 분석 & AI 머신러닝 캠프',
}

export default function ProfileCard({ avatarUrl, onWithdraw }) {
  const [profile, setProfile] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [editing, setEditing] = useState(false)
  const [nickname, setNickname] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    getMyProfile()
      .then((data) => {
        setProfile(data)
        setNickname(data.nickname || '')
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  const handleSave = async () => {
    const value = nickname.trim()

    if (!value) {
      setError('닉네임을 입력해주세요.')
      return
    }

    setSaving(true)
    setError('')

    try {
      const updated = await updateMyNickname(value)

      setProfile((prev) => ({
        ...prev,
        nickname: updated?.nickname ?? value,
      }))

      setEditing(false)
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const handleCancel = () => {
    setNickname(profile.nickname || '')
    setEditing(false)
    setError('')
  }

  if (loading) {
    return <p>프로필 불러오는 중...</p>
  }

  if (!profile) {
    return <p>프로필 조회 실패: {error}</p>
  }

  const imageUrl = avatarUrl || null

  return (
    <>
      <h2>내 프로필</h2>

      <div className="mypage-profile-info">
        <div className="mypage-profile-image">
          {imageUrl ? (
            <img
              src={imageUrl}
              alt="프로필 이미지"
              className="mypage-profile-avatar"
            />
          ) : (
            <div className="mypage-profile-placeholder">
              {profile.nickname?.charAt(0) || 'U'}
            </div>
          )}
        </div>

        <div className="mypage-profile-details">
          {editing ? (
            <form
              className="mypage-nickname-form"
              onSubmit={(event) => {
                event.preventDefault()
                handleSave()
              }}
            >
              <input
                type="text"
                value={nickname}
                onChange={(event) => setNickname(event.target.value)}
                aria-label="새 닉네임"
                disabled={saving}
              />

              <button type="submit" disabled={saving}>
                {saving ? '저장 중...' : '저장'}
              </button>

              <button
                type="button"
                onClick={handleCancel}
                disabled={saving}
              >
                취소
              </button>
            </form>
          ) : (
            <div className="mypage-nickname-row">
              <h3>{profile.nickname || '사용자'}</h3>

              <button
                type="button"
                onClick={() => {
                  setNickname(profile.nickname || '')
                  setError('')
                  setEditing(true)
                }}
              >
                닉네임 수정
              </button>
            </div>
          )}

          <p className="mypage-profile-course">
            {COURSE_NAMES[profile.course] || profile.course || '과정 미등록'}
            {' · '}
            {profile.cohort != null && Number(profile.cohort) > 0
              ? `${profile.cohort}기`
              : '기수 미등록'}
          </p>

          {error && (
            <p className="mypage-profile-error">
              {error}
            </p>
          )}
        </div>
      </div>

      <div className="mypage-profile-account-action">
        <button
          type="button"
          className="mypage-withdraw-link"
          onClick={() => onWithdraw?.()}
        >
          회원 탈퇴
        </button>
      </div>
    </>
  )
}
