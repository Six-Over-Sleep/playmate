"""크롤러가 저장한 뉴스 SQLite를 PostgreSQL career_news로 가져온다 (Issue #74, database/sql/017_career_news.sql).

    python database/scripts/import_career_news.py --sqlite <career_news.db>           # 확인만 (DB 연결 없음)
    python database/scripts/import_career_news.py --sqlite <career_news.db> --apply   # .env의 DB_*에 저장

- 크롤러 원본 코드는 바꾸지 않고, 결과 SQLite(news 테이블)만 읽기 전용으로 연다.
- 크롤러 SQLite의 news_id는 재수집 때마다 바뀌므로 쓰지 않는다. 링크를 정규화한 SHA-256(link_key)으로
  같은 뉴스를 찾아 UPSERT하므로 career_news.news_id가 유지된다.
- 링크가 바뀌어도 언론사 + 제목이 같고 발행일이 3일 이내면 같은 뉴스로 본다 (기존 news_id·링크·발행일 유지).
  발행일이 어느 한쪽이라도 없으면 제목만으로 합치지 않는다 (정기 연재처럼 제목이 같은 다른 기사를 보호).
- 같은 뉴스가 여러 분야에 있으면 career_news_fields에 분야만 추가한다.
- 행을 지우지 않는다. 이번 수집에 없는 뉴스·분야·스크랩·숨김(hidden_at)은 그대로 둔다.
- Google News RSS 링크는 GOOGLE_NEWS_RSS로 저장한다. 언론사 원문 주소로 검증하지 않았으므로 원문 URL로 표시하지 않는다.
"""

import argparse
import hashlib
import sqlite3
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[2]

# career_news_crawler config.CATEGORIES의 분야 이름 → 직무 분야 코드 (job_trends_catalog.FIELDS와 동일)
FIELD_CODES = {
    "데이터·AI": "data_ai",
    "백엔드·서버": "backend",
    "프론트엔드·웹": "frontend",
    "모바일 개발": "mobile",
    "클라우드·인프라": "cloud_infra",
    "정보보안": "security",
    "QA·테스트": "qa_test",
    "IT기획·디자인": "it_product",
}
FIELD_CODE_VALUES = frozenset(FIELD_CODES.values())

GOOGLE_NEWS_HOST = "news.google.com"
GOOGLE_NEWS_ARTICLE_PATH = "/rss/articles/"
# 기사와 무관한 추적용 쿼리: Google News의 oc, 일반 utm_*
GOOGLE_NEWS_DROP_QUERY = frozenset({"oc"})

TITLE_LIMIT = 500
SOURCE_LIMIT = 200
# 동시에 두 가져오기가 실행되지 않도록 잡는 advisory lock 키
IMPORT_LOCK_KEY = 740_014_001
# 링크가 다른 같은 기사(언론사 + 제목)로 볼 발행일 차이 한도
TITLE_MATCH_WINDOW = timedelta(days=3)


@dataclass
class NewsArticle:
    link_key: str
    link_url: str
    link_type: str
    title: str
    source_name: str
    published_at: datetime | None
    field_codes: set[str] = field(default_factory=set)


@dataclass
class ImportReport:
    inserted: int = 0
    updated: int = 0
    matched_by_title: int = 0
    field_links_added: int = 0


def clean_text(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def normalize_link(value) -> str | None:
    """http(s) 링크만 받는다. scheme·host 소문자, fragment와 추적용 쿼리를 지운다. 쓸 수 없으면 None."""
    raw = str(value or "").strip()
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in ("http", "https") or not host:
        return None
    netloc = host if parts.port is None else f"{host}:{parts.port}"
    query = [
        (key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and not (host == GOOGLE_NEWS_HOST and key in GOOGLE_NEWS_DROP_QUERY)
    ]
    return urlunsplit((scheme, netloc, parts.path or "/", urlencode(query), ""))


def link_type_of(normalized: str) -> str:
    parts = urlsplit(normalized)
    if parts.hostname == GOOGLE_NEWS_HOST and parts.path.startswith(GOOGLE_NEWS_ARTICLE_PATH):
        return "GOOGLE_NEWS_RSS"
    return "UNVERIFIED"


def link_key_of(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def parse_published(value) -> datetime | None:
    """ISO8601(career_news_crawler)과 RFC822(it_news_crawler) 발행일을 UTC 기준 시각(시간대 없음)으로 바꾼다."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            return None
    if parsed.tzinfo is None:
        return parsed  # 시간대 표시가 없으면 크롤러 기준(UTC)으로 본다
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def field_code_of(category) -> str | None:
    name = str(category or "").strip()
    if name in FIELD_CODE_VALUES:
        return name
    return FIELD_CODES.get(name)


def read_sqlite(path: Path) -> tuple[list[NewsArticle], Counter]:
    """크롤러 SQLite의 news 테이블을 읽기 전용으로 읽어 링크 기준으로 합친 뉴스 목록과 건너뛴 사유를 돌려준다."""
    if not path.is_file():
        raise FileNotFoundError(f"SQLite 파일이 없습니다: {path}")
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(news)")}
        required = {"category", "title", "source", "link", "published"}
        if not required <= columns:
            raise ValueError(f"news 테이블에 필요한 컬럼이 없습니다: {sorted(required - columns)}")
        rows = connection.execute("SELECT category, title, source, link, published FROM news").fetchall()
    finally:
        connection.close()
    return build_articles(rows)


def build_articles(rows) -> tuple[list[NewsArticle], Counter]:
    """(분야, 제목, 언론사, 링크, 발행일) 행들을 링크 기준으로 합친 뉴스 목록과 건너뛴 사유로 바꾼다."""
    skipped = Counter()
    articles: dict[str, NewsArticle] = {}
    for category, title, source, link, published in rows:
        code = field_code_of(category)
        if code is None:
            skipped["unknown_category"] += 1
            continue
        normalized = normalize_link(link)
        if normalized is None:
            skipped["invalid_link"] += 1
            continue
        title = clean_text(title, TITLE_LIMIT)
        if not title:
            skipped["empty_title"] += 1
            continue
        key = link_key_of(normalized)
        article = articles.get(key)
        if article is None:
            article = articles[key] = NewsArticle(
                link_key=key,
                link_url=normalized,
                link_type=link_type_of(normalized),
                title=title,
                source_name=clean_text(source, SOURCE_LIMIT),
                published_at=parse_published(published),
            )
        article.field_codes.add(code)
    return list(articles.values()), skipped


def import_articles(cursor, articles: list[NewsArticle], seen_at: datetime) -> ImportReport:
    """뉴스를 UPSERT하고 분야를 추가한다. 커밋은 호출 측(db_cursor)이 한다. 어떤 행도 지우지 않는다."""
    report = ImportReport()
    cursor.execute("SELECT pg_advisory_xact_lock(%s)", (IMPORT_LOCK_KEY,))

    for article in articles:
        news_id = None

        # 1. 링크가 다르게 들어온 같은 기사: 언론사 + 제목이 같고 발행일이 TITLE_MATCH_WINDOW 이내면
        #    기존 news_id·링크·발행일을 유지한다. 발행일이 없으면 제목만으로 합치지 않고 새 기사로 저장한다.
        cursor.execute("SELECT 1 FROM career_news WHERE link_key = %s", (article.link_key,))
        if cursor.fetchone() is None and article.source_name and article.published_at is not None:
            cursor.execute(
                """
                SELECT news_id
                FROM career_news
                WHERE source_name = %s
                  AND title = %s
                  AND published_at BETWEEN %s AND %s
                ORDER BY ABS(EXTRACT(EPOCH FROM published_at - %s)), news_id
                LIMIT 1
                """,
                (
                    article.source_name,
                    article.title,
                    article.published_at - TITLE_MATCH_WINDOW,
                    article.published_at + TITLE_MATCH_WINDOW,
                    article.published_at,
                ),
            )
            row = cursor.fetchone()
            if row is not None:
                news_id = row["news_id"]
                # 기존 링크와 맞는 발행일을 지키기 위해 published_at은 바꾸지 않는다.
                cursor.execute(
                    """
                    UPDATE career_news
                    SET last_seen_at = %s
                    WHERE news_id = %s
                    """,
                    (seen_at, news_id),
                )
                report.matched_by_title += 1

        # 2. 링크 기준 UPSERT: 새 뉴스는 INSERT, 같은 링크는 제목·언론사·발행일만 갱신 (news_id 유지)
        if news_id is None:
            cursor.execute(
                """
                INSERT INTO career_news (
                    link_key, link_url, link_type, title, source_name,
                    published_at, first_seen_at, last_seen_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (link_key) DO UPDATE
                SET
                    title = EXCLUDED.title,
                    source_name = EXCLUDED.source_name,
                    published_at = COALESCE(EXCLUDED.published_at, career_news.published_at),
                    last_seen_at = EXCLUDED.last_seen_at
                RETURNING news_id, (xmax = 0) AS inserted
                """,
                (
                    article.link_key,
                    article.link_url,
                    article.link_type,
                    article.title,
                    article.source_name,
                    article.published_at,
                    seen_at,
                    seen_at,
                ),
            )
            row = cursor.fetchone()
            news_id = row["news_id"]
            if row["inserted"]:
                report.inserted += 1
            else:
                report.updated += 1

        # 3. 분야 추가 (이미 있는 분야는 그대로)
        for code in sorted(article.field_codes):
            cursor.execute(
                """
                INSERT INTO career_news_fields (news_id, field_code)
                VALUES (%s, %s)
                ON CONFLICT (news_id, field_code) DO NOTHING
                """,
                (news_id, code),
            )
            report.field_links_added += cursor.rowcount

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="크롤러 뉴스 SQLite → PostgreSQL career_news 가져오기")
    parser.add_argument("--sqlite", required=True, type=Path, help="크롤러가 만든 SQLite 파일 (news 테이블)")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="DB에 저장한다. 없으면 SQLite만 읽고 결과를 보여 준다 (DB 연결 없음)",
    )
    args = parser.parse_args()

    articles, skipped = read_sqlite(args.sqlite)
    multi_field = sum(1 for article in articles if len(article.field_codes) > 1)
    google = sum(1 for article in articles if article.link_type == "GOOGLE_NEWS_RSS")
    print(f"읽은 뉴스 {len(articles)}건 (여러 분야 {multi_field}건, Google News RSS 링크 {google}건)")
    if skipped:
        print("건너뜀: " + ", ".join(f"{reason} {count}건" for reason, count in sorted(skipped.items())))
    if not args.apply:
        print("확인 모드: DB에 저장하지 않았습니다. 저장하려면 --apply를 붙이세요.")
        return

    sys.path.insert(0, str(ROOT / "backend"))
    from app.core.db_connect import db_cursor  # noqa: E402

    seen_at = datetime.now(timezone.utc).replace(tzinfo=None)
    with db_cursor(commit=True) as cursor:
        report = import_articles(cursor, articles, seen_at)
    print(
        f"저장 완료: 신규 {report.inserted}건, 갱신 {report.updated}건, "
        f"제목으로 찾은 기존 뉴스 {report.matched_by_title}건, 분야 추가 {report.field_links_added}건"
    )


if __name__ == "__main__":
    main()
