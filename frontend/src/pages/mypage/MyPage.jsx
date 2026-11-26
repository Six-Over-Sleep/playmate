import { useState } from 'react'
import ProfileCard from '../../components/mypage/ProfileCard'
import OverallLevel from '../../components/mypage/OverallLevel'
import MyPageLevelPreview from '../../components/mypage/MyPageLevelPreview'
import SkillLevels from '../../components/mypage/SkillLevels'
import MyPageXPLog from '../../components/mypage/MyPageXPLog'
import MyPageActivityOverview from '../../components/mypage/MyPageActivityOverview'
import MyActivity from '../../components/mypage/MyActivity'
import CareerSpecCard from '../../components/mypage/CareerSpecCard'

const MENU = [
  { id: 'activity', label: '내 활동', description: '게시글과 활동 기록' },
  { id: 'level', label: '레벨·XP', description: '스킬과 경험치 내역' },
  { id: 'spec', label: '내 취업 스펙', description: '이력서와 스펙 관리' },
]
export default function MyPage({ onOpenMeetup, onOpenPost, avatarUrl, onWithdraw }) {
  const [selectedMenu, setSelectedMenu] = useState('activity')

  return (
    <main className="mypage mypage-dashboard mypage-dashboard-v3 pm-mypage pm-mypage--refined">
      <header className="mypage-dashboard-title">
        <h1>마이페이지</h1>
        <p>내 활동과 성장 기록을 한눈에 확인하고 관리해 보세요.</p>
      </header>

      <div className="pm-mypage-layout">
        <aside className="pm-mypage-aside" aria-label="내 프로필과 마이페이지 메뉴">
          <div className="pm-mypage-aside-card">
            <section className="mypage-profile-shell pm-mypage-profile" aria-label="내 프로필">
              <ProfileCard avatarUrl={avatarUrl} onWithdraw={onWithdraw} showWithdraw={false} />
            </section>
            <section className="mypage-level-preview-shell pm-mypage-level-card" aria-label="현재 종합 레벨">
              <MyPageLevelPreview />
            </section>
            <nav className="mypage-dashboard-nav" aria-label="마이페이지 메뉴">
              {MENU.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`mypage-nav-item ${selectedMenu === item.id ? 'active' : ''}`}
                  aria-current={selectedMenu === item.id ? 'page' : undefined}
                  onClick={() => setSelectedMenu(item.id)}
                >
                  <span className="mypage-nav-copy"><strong>{item.label}</strong><small>{item.description}</small></span>
                  <span className="pm-mypage-nav-arrow" aria-hidden="true">›</span>
                </button>
              ))}
            </nav>
            <div className="pm-mypage-account-footer">
              <button type="button" className="pm-mypage-withdraw-button" onClick={() => onWithdraw?.()}>
                회원 탈퇴
              </button>
            </div>
          </div>
        </aside>

        <div className="pm-mypage-main">
          {selectedMenu === 'activity' && (
            <>
              <section className="pm-mypage-content-card pm-mypage-overview-card" aria-label="나의 활동 통계">
                <MyPageActivityOverview compact />
              </section>
              <section className="pm-mypage-content-card pm-mypage-activities" aria-label="내 활동 기록">
                <MyActivity onOpenMeetup={onOpenMeetup} onOpenPost={onOpenPost} />
              </section>
            </>
          )}

          {selectedMenu === 'level' && (
            <section className="pm-mypage-content-card pm-mypage-level-hub" aria-label="레벨·XP">
              <div className="pm-mypage-card-heading">
                <h2>레벨·XP</h2>
                <span>활동으로 쌓은 성장 기록을 한눈에 확인하세요.</span>
              </div>
              <div className="pm-mypage-level-sections">
                <section className="pm-mypage-level-section pm-mypage-level-overall" aria-label="종합 레벨과 출석">
                  <OverallLevel />
                </section>
                <section className="pm-mypage-level-section pm-mypage-level-skills" aria-label="스킬별 레벨">
                  <SkillLevels />
                </section>
                <section className="pm-mypage-level-section pm-mypage-level-history" aria-label="XP 획득 및 회수 내역">
                  <MyPageXPLog />
                </section>
              </div>
            </section>
          )}

          {selectedMenu === 'spec' && (
            <section className="pm-mypage-content-card pm-mypage-career">
              <CareerSpecCard />
            </section>
          )}
        </div>
      </div>
    </main>
  )
}
