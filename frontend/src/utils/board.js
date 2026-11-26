/** 날짜 표시 규칙을 통일하고 잘못된 날짜가 화면 전체를 중단하지 않게 한다. */
export function formatBoardDate(value, dateStyle = 'medium') {
  const date = new Date(value)
  if (!value || Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('ko-KR', { dateStyle, timeStyle: 'short' }).format(date)
}

/** 원본을 변경하지 않고 정렬한다. 날짜가 없으면 서버의 최신순을 기준으로 삼는다. */
export function sortBoardPosts(posts, sort) {
  if (!Array.isArray(posts)) return []
  const indexed = posts.map((post, index) => ({
    post,
    index,
    time: Date.parse(post.created_at ?? post.createdAt ?? ''),
  }))
  const hasDates = indexed.every(({ time }) => Number.isFinite(time))
  indexed.sort((left, right) => {
    const difference = hasDates ? right.time - left.time : left.index - right.index
    return (sort === 'latest' ? difference : -difference) || left.index - right.index
  })
  return indexed.map(({ post }) => post)
}
