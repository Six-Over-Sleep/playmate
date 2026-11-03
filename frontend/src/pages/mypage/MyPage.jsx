
import { useState } from 'react'
import ProfileCard from '../../components/mypage/ProfileCard'
import OverallLevel from '../../components/mypage/OverallLevel'
import MyPageLevelPreview from '../../components/mypage/MyPageLevelPreview'
import SkillLevels from '../../components/mypage/SkillLevels'
import MyPageXPLog from '../../components/mypage/MyPageXPLog'
import MyPageActivityOverview from '../../components/mypage/MyPageActivityOverview'
import MyActivity from '../../components/mypage/MyActivity'
import CareerSpecCard from '../../components/mypage/CareerSpecCard'

import '../../styles/mypage.css'
import '../../styles/mypageDashboard.css'
import '../../styles/mypageDashboardV3.css'

const MENU = [
  { id: 'level', icon: '🏆', label: '나의 레벨', description: '레벨·경험치 기록' },
  { id: 'activity', icon: '📊', label: '나의 활동', description: '활동 요약·내역' },
  { id: 'spec', icon: '💼', label: '나의 스펙', description: '취업 스펙 관리' },
]

const LEVEL_TABS = [
  { id: 'overall', label: '종합 레벨' },
  { id: 'skills', label: '스킬 레벨' },
  { id: 'history', label: 'XP 획득·회수 내역' },
]

export default function MyPage({ onOpenMeetup, onOpenPost, avatarUrl, onWithdraw }) {
  const [selectedMenu, setSelectedMenu] = useState('level')
  const [selectedLevelTab, setSelectedLevelTab] = useState('overall')
  const menu = MENU.find((item) => item.id === selectedMenu)

  return (
    <main className="mypage mypage-dashboard mypage-dashboard-v3">
      <header className="mypage-dashboard-title">
        <h1>마이페이지</h1>
        <p>프로필, 활동 기록, 나의 성장을 한곳에서 관리하세요.</p>
      </header>

      <div className="mypage-dashboard-hero">
        <section className="mypage-profile-shell" aria-label="내 프로필">
          <ProfileCard avatarUrl={avatarUrl} onWithdraw={onWithdraw} />
        </section>

        <section className="mypage-level-preview-shell" aria-label="현재 종합 레벨">
          <MyPageLevelPreview />
        </section>
      </div>

      <div className="mypage-dashboard-body">
        <nav className="mypage-dashboard-nav" aria-label="마이페이지 메뉴">
          {MENU.map((item) => (
            <button
              type="button"
              key={item.id}
              className={`mypage-nav-item ${selectedMenu === item.id ? 'active' : ''}`}
              aria-current={selectedMenu === item.id ? 'page' : undefined}
              onClick={() => setSelectedMenu(item.id)}
            >
              <span className="mypage-nav-icon" aria-hidden="true">{item.icon}</span>
              <span className="mypage-nav-copy">
                <strong>{item.label}</strong>
                <small>{item.description}</small>
              </span>
            </button>
          ))}
        </nav>

        <section className="mypage-dashboard-content" aria-labelledby="mypage-panel-title">
          <div className="mypage-dashboard-section-header">
            <h2 id="mypage-panel-title">{menu?.label}</h2>
            <p>{menu?.description}</p>
          </div>

          {selectedMenu === 'level' && (
            <>
              <div className="mypage-level-switcher" role="tablist" aria-label="레벨 정보 보기">
                {LEVEL_TABS.map((tab) => (
                  <button
                    key={tab.id}
                    type="button"
                    role="tab"
                    aria-selected={selectedLevelTab === tab.id}
                    className={selectedLevelTab === tab.id ? 'active' : ''}
                    onClick={() => setSelectedLevelTab(tab.id)}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              <div className="mypage-level-panel" role="tabpanel">
                {selectedLevelTab === 'overall' && <OverallLevel />}
                {selectedLevelTab === 'skills' && <SkillLevels />}
                {selectedLevelTab === 'history' && <MyPageXPLog />}
              </div>
            </>
          )}

          {selectedMenu === 'activity' && (
            <>
              <MyPageActivityOverview />

              <div className="mypage-dashboard-activity">
                <MyActivity
                  onOpenMeetup={onOpenMeetup}
                  onOpenPost={onOpenPost}
                />
              </div>
            </>
          )}

          {selectedMenu === 'spec' && <CareerSpecCard />}
        </section>
      </div>
    </main>
  )
}
