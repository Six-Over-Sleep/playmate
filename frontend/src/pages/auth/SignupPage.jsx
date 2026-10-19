import { useEffect, useState } from 'react'
import '../../styles/auth.css'
import logo from '../../assets/playmate-logo.png'
import { getAuthUrl } from '../../config/api'
import { apiRequest } from '../../services/apiClient'

export default function SignupPage({ onBack, onComplete }) {
  const [form, setForm] = useState({
    discordId: '',
    nickname: '',
    course: '',
    cohort: '',
  })

  const [discordStatus, setDiscordStatus] = useState('checking')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    const checkDiscordSession = async () => {
      try {
        const data = await apiRequest('/me', {
          urlBuilder: getAuthUrl,
          credentials: 'include',
        })

        if (!data.signup_required) {
          onComplete?.()
          return
        }

        setForm((prev) => ({
          ...prev,
          discordId:
            data.discord_user?.username ||
            data.discord_user?.discord_id ||
            '',
        }))

        setDiscordStatus('verified')
      } catch (error) {
        if (error.status !== 401) {
          console.error(error)
        }
        setDiscordStatus('idle')
      }
    }

    checkDiscordSession()
  }, [onComplete])

  const handleChange = (event) => {
    const { name, value } = event.target

    setForm((prev) => ({
      ...prev,
      [name]: value,
    }))
  }

  const handleDiscordAuth = () => {
    window.location.href = getAuthUrl('/discord/login')
  }

  const handleSubmit = async (event) => {
    event.preventDefault()

    if (discordStatus !== 'verified') {
      alert('Discord 인증을 먼저 진행해주세요.')
      return
    }

    if (!form.nickname.trim()) {
      alert('닉네임을 입력해주세요.')
      return
    }

    if (!form.course) {
      alert('교육 과정을 선택해주세요.')
      return
    }

    if (!form.cohort) {
      alert('기수를 입력해주세요.')
      return
    }

    setSubmitting(true)

    try {
      await apiRequest('/signup', {
        urlBuilder: getAuthUrl,
        method: 'POST',
        credentials: 'include',
        body: JSON.stringify({
          nickname: form.nickname.trim(),
          cohort: Number(form.cohort),
          track: form.course,
        }),
      })

      alert('회원가입이 완료되었습니다.')
      onComplete?.()
    } catch (error) {
      if (error.status === 409) {
        alert(error.data?.detail || '이미 가입된 회원입니다.')
        onComplete?.()
        return
      }

      console.error(error)
      alert(error.message || '서버와 통신할 수 없습니다.')
    } finally {
      setSubmitting(false)
    }
  }

  const isVerified = discordStatus === 'verified'
  const isChecking = discordStatus === 'checking'

  return (
    <div className="auth-page">
      <main className="signup-main">
        <section className="signup-card">
          <button
            type="button"
            className="signup-back-button"
            onClick={onBack}
          >
            ← 이전으로
          </button>

          <div className="signup-logo">
            <img src={logo} alt="" aria-hidden="true" />
          </div>

          <div className="signup-heading">
            <div>
              <h1>회원가입</h1>
              <p>커뮤니티에서 사용할 정보를 입력해주세요.</p>
            </div>
          </div>

          <form className="signup-form" onSubmit={handleSubmit}>
            <div className="signup-field">
              <span>
                Discord ID <b>*</b>
              </span>

              {!isVerified ? (
                <>
                  <button
                    type="button"
                    className="discord-auth-button"
                    onClick={handleDiscordAuth}
                    disabled={isChecking}
                  >
                    <span className="discord-auth-icon">◉</span>
                    <span>
                      {isChecking
                        ? 'Discord 인증 확인 중...'
                        : 'Discord 인증하기'}
                    </span>
                  </button>

                  <small>
                    Discord 인증 후 계정 정보가 자동으로 입력됩니다.
                  </small>
                </>
              ) : (
                <>
                  <div className="signup-disabled-input discord-verified">
                    <input
                      type="text"
                      value={form.discordId}
                      readOnly
                    />

                    <span className="signup-status-icon">✓</span>
                  </div>

                  <small className="discord-success">
                    Discord 인증이 완료되었습니다.
                  </small>
                </>
              )}
            </div>

            <label className="signup-field">
              <span>
                닉네임 <b>*</b>
              </span>

              <input
                type="text"
                name="nickname"
                value={form.nickname}
                onChange={handleChange}
                placeholder="커뮤니티에서 사용할 닉네임"
                maxLength={20}
              />
            </label>

            <label className="signup-field">
              <span>
                교육 과정 <b>*</b>
              </span>

              <select
                name="course"
                value={form.course}
                onChange={handleChange}
              >
                <option value="">
                  교육 과정을 선택해주세요
                </option>
                <option value="family-ai">
                  SKN Family AI 캠프
                </option>
              </select>
            </label>

            <label className="signup-field">
              <span>
                기수 <b>*</b>
              </span>

              <div className="signup-cohort-input">
                <input
                  type="number"
                  name="cohort"
                  value={form.cohort}
                  onChange={handleChange}
                  placeholder="예) 36"
                  min="1"
                />
                <span>기</span>
              </div>
            </label>

            <button
              type="submit"
              className="signup-submit-button"
              disabled={!isVerified || submitting}
            >
              {submitting ? '가입 중...' : '가입하기'}
            </button>
          </form>
        </section>
      </main>
    </div>
  )
}
