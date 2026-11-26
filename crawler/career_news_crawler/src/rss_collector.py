"""Google News RSS 기반 분야별 뉴스 수집·제목 필터링."""

import calendar
from datetime import datetime, timedelta, timezone
import re
from urllib.parse import quote, urlsplit

import feedparser
import requests

from config import EXCLUDE_KEYWORDS, EXCLUDE_SOURCES, MAX_ARTICLES_PER_QUERY


def contains_keyword(text: str, keyword: str) -> bool:
    """영문 단축어(AI, QA 등)는 단어 단위로, 한글 표현은 부분 일치로 찾습니다."""
    keyword = keyword.strip()
    if not keyword:
        return False
    if re.fullmatch(r"[A-Za-z0-9]+", keyword):
        pattern = rf"(?<![A-Za-z0-9]){re.escape(keyword)}(?![A-Za-z0-9])"
        return re.search(pattern, text, flags=re.IGNORECASE) is not None
    return keyword.casefold() in text.casefold()


def is_relevant(title: str, title_keywords: list[str]) -> bool:
    """제목 기반 간단한 관련성 판별 (정밀 분류기가 아님)."""
    if any(contains_keyword(title, word) for word in EXCLUDE_KEYWORDS):
        return False
    return any(contains_keyword(title, word) for word in title_keywords)


def normalize_published(entry) -> str | None:
    """RSS 날짜를 SQLite 정렬 가능한 UTC ISO8601로 통일."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc).isoformat(timespec="seconds")
    return None


def collect_google_news(
    query: str,
    title_keywords: list[str],
    days: int = 14,
    limit: int = MAX_ARTICLES_PER_QUERY,
    session: requests.Session | None = None,
) -> list[dict]:
    """검색어 하나에 대한 RSS 수집. 네트워크 실패는 호출 측에서 처리하도록 예외 발생."""
    if days < 1:
        raise ValueError("days는 1 이상이어야 합니다")
    # 검색식은 config 그대로 사용 (정확한 문구 검색이 필요하면 config에서 큰따옴표로 감쌈)
    search_expression = f"{query} when:{days}d"
    rss_url = (
        "https://news.google.com/rss/search"
        f"?q={quote(search_expression)}&hl=ko&gl=KR&ceid=KR:ko"
    )
    client = session or requests
    response = client.get(
        rss_url,
        timeout=15,
        headers={"User-Agent": "CareerNewsCrawler/1.0 (RSS metadata collector)"},
    )
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    if feed.get("bozo") and not feed.entries:
        raise ValueError(f"RSS 형식 오류: {query}")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    articles = []
    for entry in feed.entries:
        raw_title = str(entry.get("title", "")).strip()
        link = str(entry.get("link", "")).strip()
        if not raw_title or not link:
            continue
        parts = urlsplit(link)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            continue

        source = entry.get("source", {})
        source_name = str(source.get("title") or "").strip() if hasattr(source, "get") else ""
        title = raw_title
        if not source_name and " - " in raw_title:
            title, source_name = raw_title.rsplit(" - ", 1)
        elif source_name and title.endswith(f" - {source_name}"):
            title = title[: -(len(source_name) + 3)]
        title = title.strip()

        if source_name in EXCLUDE_SOURCES:
            continue
        if not is_relevant(title, title_keywords):
            continue
        published = normalize_published(entry)
        if published and datetime.fromisoformat(published) < cutoff:
            continue
        articles.append(
            {
                "title": title,
                "source": source_name,
                "link": link,
                "published": published,
            }
        )
        if len(articles) >= limit:
            break
    return articles
