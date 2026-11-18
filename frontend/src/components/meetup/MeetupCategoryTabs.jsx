// 카테고리 선택 값은 부모가 관리하며, 화면 크기에 따라 아이콘 표시만 조정합니다.
// 기존 CATEGORY_OPTIONS 값은 그대로 사용하므로 필터 및 모임 생성 동작에 영향이 없습니다.
const CATEGORY_PRESENTATION = {
  all: { label: '전체 모임', icon: null },
  study: { label: '스터디', icon: '📖' },
  project: { label: '프로젝트', icon: '💻' },
  sports: { label: '운동', icon: '🏃' },
  game: { label: '게임', icon: '🎮' },
  group_buy: { label: '공동구매', icon: '🛒' },
}

export default function MeetupCategoryTabs({ categories, value, onChange }) {
  return (
    <div className="meetup-tabs" role="tablist" aria-label="모임 카테고리">
      {categories.map((item) => {
        const presentation = CATEGORY_PRESENTATION[item.value]
        return (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={value === item.value}
            className={`${value === item.value ? 'active' : ''} ${item.value === 'all' ? 'meetup-tab-all' : ''}`.trim()}
            onClick={() => onChange(item.value)}
          >
            {presentation?.icon && (
              <span className="meetup-tab-icon" aria-hidden="true">{presentation.icon}</span>
            )}
            <span className="meetup-tab-label">{presentation?.label ?? item.label}</span>
          </button>
        )
      })}
    </div>
  )
}
