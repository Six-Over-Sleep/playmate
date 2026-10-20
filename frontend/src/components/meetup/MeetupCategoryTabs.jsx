// 선택 상태는 부모의 value로 받고, 클릭한 카테고리 값은 onChange로 전달함.
export default function MeetupCategoryTabs({ categories, value, onChange }) {
  return (
    <div
      className="meetup-tabs"
      role="tablist"
      aria-label="모임 카테고리"
    >
      {categories.map((item) => (
        <button
          key={item.value}
          type="button"
          className={value === item.value ? 'active' : ''}
          onClick={() => onChange(item.value)}
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}
