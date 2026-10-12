import { useState } from 'react'
import '../../styles/auth.css'
import logo from '../../assets/playmate-logo.png'

const MOCK_IS_DUPLICATE = false

export default function SignupPage({ onBack }) {
  const [form, setForm] = useState({
    discordId: '',
    nickname: '',
    course: '',
    cohort: '',
  })

  const [discordStatus, setDiscordStatus] = useState('idle')

  const handleChange = (event) => {
    const { name, value } = event.target

    setForm((prev) => ({
      ...prev,
      [name]: value,
    }))
  }

  const handleDiscordAuth = () => {
    // 실제 Discord OAuth 연결 전 화면 확인용 임시 동작
    setForm((prev) => ({
      ...prev,
      discordId: 'admin',
    }))

    setDiscordStatus(MOCK_IS_DUPLICATE ? 'duplicate' : 'verified')
  }

  const handleSubmit = (event) => {
    event.preventDefault()

    if (discordStatus === 'idle') {
      alert('Discord 인증을 먼저 진행해주세요.')
      return
    }

    if (discordStatus === 'duplicate') {
      alert('이미 가입된 Discord 계정입니다.')
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

    // 추후 실제 회원가입 API 연결
    console.log('회원가입 데이터:', form)
  }

  const isVerified = discordStatus === 'verified'
  const isDuplicate = discordStatus === 'duplicate'

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
              <h1>PlayMate 회원가입</h1>
              <p>커뮤니티에서 사용할 정보를 입력해주세요.</p>
            </div>
          </div>

          <form className="signup-form" onSubmit={handleSubmit}>
            <div className="signup-field">
              <span>
                Discord ID <b>*</b>
              </span>

              {discordStatus === 'idle' ? (
                <>
                  <button
                    type="button"
                    className="discord-auth-button"
                    onClick={handleDiscordAuth}
                  >
                    <span className="discord-auth-icon">◉</span>
                    <span>Discord 인증하기</span>
                  </button>

                  <small>
                    Discord 인증 후 계정 정보가 자동으로 입력됩니다.
                  </small>
                </>
              ) : (
                <>
                  <div
                    className={`signup-disabled-input ${
                      isDuplicate ? 'discord-duplicate' : 'discord-verified'
                    }`}
                  >
                    <input
                      type="text"
                      value={form.discordId}
                      readOnly
                    />

                    <span className="signup-status-icon">
                      {isDuplicate ? '!' : '✓'}
                    </span>
                  </div>

                  {isDuplicate ? (
                    <small className="discord-error">
                      이미 가입된 Discord 계정입니다.
                    </small>
                  ) : (
                    <small className="discord-success">
                      Discord 인증이 완료되었습니다.
                    </small>
                  )}
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
              disabled={!isVerified}
            >
              가입하기
            </button>
          </form>
        </section>
      </main>
    </div>
  )
}
