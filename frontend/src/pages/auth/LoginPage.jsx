import '../../styles/auth.css'
import logo from '../../assets/playmate-logo.png'

export default function LoginPage({ onSignup, onDevEnter }) {
  const handleDiscordLogin = () => {
    window.location.href =
      'http://localhost:8000/auth/discord/login'
  }

  return (
    <div className="auth-page">

      {/* 개발용 임시 버튼 */}
      <button
        type="button"
        className="dev-admin-button"
        onClick={onDevEnter}
      >
        관리자 페이지
      </button>

      <main className="login-main login-main-centered">
        <section className="login-container login-container-centered">
          <div className="login-card">

            <div className="login-card-logo">
              <img
                src={logo}
                alt=""
                aria-hidden="true"
              />
            </div>

            <p className="login-card-description">
              Discord 계정으로 안전하고 간편하게 로그인하세요.
            </p>

            <button
              type="button"
              className="discord-login-button"
              onClick={handleDiscordLogin}
            >
              <span className="discord-icon">◉</span>
              <span>Discord로 간편 로그인</span>
              <span className="login-arrow">→</span>
            </button>

            <button
              type="button"
              className="signup-text-button"
              onClick={onSignup}
            >
              회원가입
            </button>

          </div>
        </section>
      </main>
    </div>
  )
}