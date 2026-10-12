import '../../styles/header.css'
import logo from '../../assets/playmate-logo.png'

export default function Header({ activeSection, onNavigate }) {
  const go = (section) => {
    onNavigate?.(section)
  }

  return (
    <header className="app-header">
      <a
        className="brand"
        href="/"
        aria-label="PlayMate 홈"
        onClick={(event) => {
          event.preventDefault()
          go('board')
        }}
      >
        <img
          src={logo}
          alt=""
          className="brand-logo"
          aria-hidden="true"
        />

        <span className="brand-text">PlayMate</span>
      </a>

      <nav className="app-nav" aria-label="주 메뉴">
        <button
          type="button"
          className={activeSection === 'board' ? 'active' : ''}
          onClick={() => go('board')}
        >
          게시판
        </button>

        <button
          type="button"
          className={activeSection === 'meetup' ? 'active' : ''}
          onClick={() => go('meetup')}
        >
          모임
        </button>

        <span>마이페이지</span>
      </nav>
    </header>
  )
}
