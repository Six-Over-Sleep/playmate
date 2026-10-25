import { useState } from 'react'
import '../../styles/header.css'
import logo from '../../assets/playmate-logo.png'

export default function Header({ activeSection, onNavigate, nickname, avatarUrl, onLogout }) {
  const [profileOpen, setProfileOpen] = useState(false)
  const go = (section) => {
    setProfileOpen(false)
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


        <button
          type="button"
          className={activeSection === 'mypage' ? 'active' : ''}
          onClick={() => go('mypage')}
        >
          마이페이지
        </button>

      </nav>

      <div className="profile-container">
        <button
          type="button"
          className="profile-avatar"
          aria-label="프로필 메뉴"
          aria-expanded={profileOpen}
          aria-haspopup="menu"
          onClick={() => setProfileOpen((open) => !open)}
        >
          {avatarUrl ? (
            <img src={avatarUrl} alt="" className="profile-avatar-image" />
          ) : (
            nickname?.charAt(0) || 'U'
          )}
        </button>

        {profileOpen && (
          <div className="profile-dropdown">
            <div className="profile-user-info">
              {avatarUrl ? (
                <img src={avatarUrl} alt="Discord 프로필 사진" className="profile-user-avatar" />
              ) : (
                <div className="profile-user-avatar profile-user-fallback">
                  {nickname?.charAt(0) || 'U'}
                </div>
              )}
              <span className="profile-nickname">{nickname || '사용자'}</span>
            </div>
            <hr />
            
            <hr />

            <button
              type="button"
              onClick={() => go('mypage')}
            >
              마이페이지
            </button>

            <button
              type="button"
              onClick={() => {
                setProfileOpen(false)
                onLogout?.()
              }}
            >
              로그아웃
            </button>

            <button
              type="button"
              onClick={() => {
                setProfileOpen(false)
                onLogout?.()
              }}
            >
              로그아웃
            </button>
            {/* 탈퇴 정책 협의 전: 기능이 없는 버튼은 비활성화 */}
            <button type="button" className="withdraw-button" disabled title="회원 탈퇴 정책 협의 중">
              회원 탈퇴 (준비 중)
            </button>
          </div>
        )}
      </div>
    </header>
  )
}
