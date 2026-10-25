
import ProfileCard from '../../components/mypage/ProfileCard'
import '../../styles/mypage.css'
import OverallLevel from '../../components/mypage/OverallLevel'
import SkillLevels from '../../components/mypage/SkillLevels'
import MyActivity from '../../components/mypage/MyActivity'

export default function MyPage() {
  return (
    <main className="mypage">
      <h1>마이페이지</h1>
      <p>내 프로필과 활동 기록을 확인할 수 있습니다.</p>

      <section>
        <ProfileCard />
      </section>

      <section>
        <OverallLevel />
      </section>

      <section>
        <SkillLevels />
      </section>

      <section className="mypage-activity-section">
        <MyActivity />
      </section>
    </main>
  )
}
