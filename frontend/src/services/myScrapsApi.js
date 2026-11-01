import { getMyActivities } from './mypageApi'
import { getMyNewsScraps } from './careerApi'

// =========================================================
// 마이페이지 '내 스크랩' (Issue #74)
// 게시글 스크랩(GET /mypage/scraps, 최근 20건)과 뉴스 스크랩(GET /api/career/news/scraps, 최근 20건)을
// 스크랩 시각 최신순으로 합친다. 전체 스크랩이 아니라 각각 최근 20건을 합친 제한 목록이다.
// =========================================================

export const NEWS_SCRAP_ERROR = '뉴스 스크랩을 불러오지 못했습니다. 게시글 스크랩만 표시합니다.'

// 두 API 모두 같은 DB 기본값(CURRENT_TIMESTAMP)을 시간대 없는 ISO 문자열로 보낸다.
// 마이크로초는 밀리초까지만 읽어 같은 기준으로 비교한다.
function scrapTime(value) {
  const time = Date.parse(String(value || '').replace(/(\.\d{3})\d+/, '$1'))
  return Number.isNaN(time) ? 0 : time
}

/**
 * 게시글·뉴스 스크랩을 합친 목록을 돌려준다.
 * - 게시글 스크랩 조회가 실패하면 기존처럼 오류로 처리한다.
 * - 뉴스 스크랩만 실패하면 게시글 스크랩은 그대로 보여 주고 newsError로 안내한다. (정상 0건이면 newsError는 빈 문자열)
 * - scrap_key(post-ID / news-ID)로 게시글 ID와 뉴스 ID가 같아도 구분한다.
 */
export async function getMyScraps() {
  const [posts, news] = await Promise.allSettled([
    getMyActivities('scraps'),
    getMyNewsScraps(),
  ])

  if (posts.status === 'rejected') {
    throw posts.reason
  }
  if (!Array.isArray(posts.value)) {
    throw new Error('활동 조회 응답 형식이 올바르지 않습니다.')
  }

  const newsItems = news.status === 'fulfilled' && Array.isArray(news.value?.items)
    ? news.value.items
    : null

  const items = [
    ...posts.value.map((item) => ({ ...item, scrap_key: `post-${item.post_id}` })),
    ...(newsItems || []).map((item) => ({ ...item, scrap_key: `news-${item.news_id}` })),
  ]

  // 같은 시각이면 기존 순서(게시글 → 뉴스, 각 API의 정렬)를 유지한다 (Array.sort는 안정 정렬).
  items.sort((a, b) => scrapTime(b.scrapped_at) - scrapTime(a.scrapped_at))

  return {
    items,
    newsError: newsItems ? '' : NEWS_SCRAP_ERROR,
  }
}
