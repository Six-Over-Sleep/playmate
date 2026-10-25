
import { useEffect, useRef, useState } from 'react'
import {
  getMyProfile,
  updateMyNickname,
  uploadMyProfileImage,
} from '../../services/mypageApi'
import { resolveMediaUrl } from '../../config/api'

export default function ProfileCard() {
  // 프로필 정보
  const [profile, setProfile] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // 닉네임 수정
  const [editing, setEditing] = useState(false)
  const [nickname, setNickname] = useState('')
  const [saving, setSaving] = useState(false)

  // 프로필 이미지 변경
  const [uploading, setUploading] = useState(false)
  const imageInputRef = useRef(null)

  // 프로필 조회
  useEffect(() => {
    getMyProfile()
      .then((data) => {
        setProfile(data)
        setNickname(data.nickname || '')
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  // 프로필 이미지 변경
  const handleImageChange = async (event) => {
    const input = event.currentTarget
    const file = input.files?.[0]

    if (!file) return

    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      setError('JPG, PNG, WEBP 이미지만 업로드할 수 있습니다.')
      input.value = ''
      return
    }

    if (file.size > 5 * 1024 * 1024) {
      setError('이미지는 5MB 이하여야 합니다.')
      input.value = ''
      return
    }

    setUploading(true)
    setError('')

    try {
      await uploadMyProfileImage(file)

      // 업로드 후 최신 프로필 조회
      const updatedProfile = await getMyProfile()
      setProfile(updatedProfile)
    } catch (err) {
      setError(err.message)
    } finally {
      setUploading(false)
      input.value = ''
    }
  }

  // 닉네임 저장
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

  // 닉네임 수정 취소
  const handleCancel = () => {
    setNickname(profile.nickname || '')
    setEditing(false)
    setError('')
  }

  // 로딩 및 오류 처리
  if (loading) {
    return <p>프로필 불러오는 중...</p>
  }

  if (!profile) {
    return <p>프로필 조회 실패: {error}</p>
  }

  const imageUrl = resolveMediaUrl(profile.profile_image_url)

  return (
    <>
      <h2>내 프로필</h2>

      <div className="mypage-profile-info">

        {/* 프로필 이미지 */}
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

          {/* 프로필 이미지 변경 */}
          <div className="mypage-image-actions">
            <input
              ref={imageInputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              onChange={handleImageChange}
              aria-label="프로필 이미지 선택"
              hidden
            />

            <button
              type="button"
              disabled={uploading}
              onClick={() => imageInputRef.current?.click()}
            >
              {uploading ? '업로드 중...' : '사진 변경'}
            </button>
          </div>
        </div>

        {/* 프로필 정보 */}
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

          <p>PLAYMATE 회원</p>

          {error && (
            <p className="mypage-profile-error">
              {error}
            </p>
          )}
        </div>
      </div>
    </>
  )
}
