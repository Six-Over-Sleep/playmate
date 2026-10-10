export default function Header() {
  return (
    <header className="app-header">
      <a className="brand" href="/" aria-label="PlayMate 홈"><span>🧩</span>PlayMate</a>
      <nav aria-label="주 메뉴">
        <a className="active" href="/">게시판</a>
        <span>모임</span><span>자격증</span><span>마이페이지</span>
      </nav>
    </header>
  )
}

