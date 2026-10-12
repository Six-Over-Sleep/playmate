import logo from '../../assets/playmate-logo.png'

export default function Header({ activeSection = 'board', onNavigate = () => {} }) {
  return (
    <header className="app-header">
      <a className="brand" href="/" aria-label="PlayMate 홈" onClick={(event) => { event.preventDefault(); onNavigate('board') }}>
        <img src={logo} alt="PlayMate" className="brand-logo" />
        <span className="brand-text">PlayMate</span>
      </a>

      <nav className="app-nav" aria-label="주 메뉴">
        <button type="button" className={activeSection === 'board' ? 'active' : ''} onClick={() => onNavigate('board')}>게시판</button>
        <button type="button" className={activeSection === 'meetup' ? 'active' : ''} onClick={() => onNavigate('meetup')}>모임</button>
        <span>자격증</span>
        <span>마이페이지</span>
      </nav>
    </header>
  )
}
