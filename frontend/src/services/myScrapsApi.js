import { apiRequest } from './apiClient'
import { getMyNewsScraps } from './careerApi'

// =========================================================
// 마이페이지 '스크랩' (Issue #74)
// 게시글 스크랩(GET /mypage/scraps, 서버 페이지네이션)과 뉴스 스크랩(GET /api/career/news/scraps)을
// 스크랩 시각 최신순으로 합쳐 10건씩 보여 준다.
// - 게시글 스크랩은 기존처럼 전체를 페이지로 볼 수 있다. (요청한 페이지까지 필요한 만큼 서버에서 받음)
// - 뉴스 스크랩은 최근 NEWS_SCRAP_LIMIT건까지만 합친다. 그보다 많으면 exact=false로 알린다.
// =========================================================

export const PAGE_SIZE = 10
export const NEWS_SCRAP_LIMIT = 50  // GET /api/career/news/scraps의 최대 limit
const POST_PAGE_SIZE = 50  // GET /mypage/scraps의 최대 page_size

export const NEWS_SCRAP_ERROR = '뉴스 스크랩을 불러오지 못했습니다. 게시글 스크랩만 표시합니다.'

// 개발 환경에서만 테스트 회원 ID 사용 (mypageApi와 같은 방식)
const devMemberId = import.meta.env.DEV
  ? import.meta.env.VITE_DEV_MEMBER_ID
  : null

// 두 API 모두 같은 DB 기본값(CURRENT_TIMESTAMP)을 시간대 없는 ISO 문자열로 보낸다.
// 마이크로초는 밀리초까지만 읽어 같은 기준으로 비교한다.
function scrapTime(value) {
  const time = Date.parse(String(value || '').replace(/(\.\d{3})\d+/, '$1'))
  return Number.isNaN(time) ? 0 : time
}

function getPostScrapPage(page) {
  return apiRequest(`/mypage/scraps?page=${page}&page_size=${POST_PAGE_SIZE}`, {
    credentials: 'include',
    headers: devMemberId
      ? { 'X-Dev-Member-ID': devMemberId }
      : {},
  })
}

// 합친 목록의 page번째 10건을 만들려면 게시글 스크랩도 최신 page*10건이 필요하다.
async function getRecentPostScraps(count) {
  const items = []
  let total = 0
  for (let page = 1; ; page += 1) {
    const data = await getPostScrapPage(page)
    if (!data || !Array.isArray(data.items)) {
      throw new Error('활동 조회 응답 형식이 올바르지 않습니다.')
    }
    items.push(...data.items)
    total = Number(data.total) || 0
    if (items.length >= count || items.length >= total || data.items.length === 0) {
      return { items, total }
    }
  }
}

/**
 * 게시글·뉴스 스크랩을 합친 목록의 page번째 페이지 → { items, total, exact, newsError }
 * - total: 게시글 스크랩 전체 수 + 불러온 뉴스 스크랩 수
 * - exact: total이 실제 전체 스크랩 수인지 (뉴스 조회 실패이거나 뉴스가 NEWS_SCRAP_LIMIT건 이상이면 false)
 * - 게시글 스크랩 조회가 실패하면 기존처럼 오류로 처리한다.
 * - 뉴스 스크랩만 실패하면 게시글 스크랩은 그대로 보여 주고 newsError로 안내한다. (정상 0건이면 빈 문자열)
 * - scrap_key(post-ID / news-ID)로 게시글 ID와 뉴스 ID가 같아도 구분한다.
 */
export async function getMyScraps(page = 1) {
  const [posts, news] = await Promise.allSettled([
    getRecentPostScraps(page * PAGE_SIZE),
    getMyNewsScraps(NEWS_SCRAP_LIMIT),
  ])

  if (posts.status === 'rejected') {
    throw posts.reason
  }

  const newsItems = news.status === 'fulfilled' && Array.isArray(news.value?.items)
    ? news.value.items
    : null

  const merged = [
    ...posts.value.items.map((item) => ({ ...item, scrap_key: `post-${item.post_id}` })),
    ...(newsItems || []).map((item) => ({ ...item, scrap_key: `news-${item.news_id}` })),
  ]

  // 같은 시각이면 기존 순서(게시글 → 뉴스, 각 API의 정렬)를 유지한다 (Array.sort는 안정 정렬).
  merged.sort((a, b) => scrapTime(b.scrapped_at) - scrapTime(a.scrapped_at))

  return {
    items: merged.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    total: posts.value.total + (newsItems ? newsItems.length : 0),
    exact: Boolean(newsItems) && newsItems.length < NEWS_SCRAP_LIMIT,
    newsError: newsItems ? '' : NEWS_SCRAP_ERROR,
  }
}
