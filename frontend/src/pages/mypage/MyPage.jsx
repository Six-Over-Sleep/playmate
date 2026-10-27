import ProfileCard from '../../components/mypage/ProfileCard'
import OverallLevel from '../../components/mypage/OverallLevel'
import SkillLevels from '../../components/mypage/SkillLevels'
import MyActivity from '../../components/mypage/MyActivity'
import CareerSpecCard from '../../components/mypage/CareerSpecCard'

import '../../styles/mypage.css'

export default function MyPage({ onOpenMeetup }) {
    return (
    <main className="mypage">
      <h1>마이페이지</h1>
      <p>내 프로필과 활동 기록을 확인할 수 있습니다.</p>

      {/* 프로필 */}
      <section>
        <ProfileCard />
      </section>

      {/* 종합 레벨 */}
      <section>
        <OverallLevel />
      </section>

      {/* 스킬 레벨 */}
      <section>
        <SkillLevels />
      </section>

      {/* 취업 스펙 */}
      <CareerSpecCard />

      {/* 내 활동 기록 */}
      <section className="mypage-activity-section">
        <MyActivity onOpenMeetup={onOpenMeetup} />
      </section>
    </main>
  )
}