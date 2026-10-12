import logo from '../../assets/playmate-logo.png'

export default function Header({ onMeetupHome }) {
  return (
    <header className="app-header">
      <a className="brand" href="/" aria-label="PlayMate 홈">
        <img
          src={logo}
          alt="PlayMate"
          className="brand-logo"
        />

        <span className="brand-text">PlayMate</span>
      </a>

      <nav className="app-nav" aria-label="주 메뉴">
        <span>게시판</span>

        <button
          type="button"
          className="active"
          onClick={onMeetupHome}
        >
          모임
        </button>

        <span>마이페이지</span>
      </nav>
    </header>
  )
}