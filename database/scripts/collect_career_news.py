"""career_news_crawler의 Google News RSS 수집 결과를 PostgreSQL career_news에 바로 저장한다 (Issue #74).

    python database/scripts/collect_career_news.py --crawler-dir <career_news_crawler>           # 수집 결과 확인만 (DB 연결 없음)
    python database/scripts/collect_career_news.py --crawler-dir <career_news_crawler> --apply   # .env의 DB_*에 저장

- 크롤러 원본 코드는 바꾸지 않는다. config.CATEGORIES와 src/rss_collector.collect_google_news만 불러 쓰고,
  크롤러의 main.py·src/database.py(자체 SQLite 저장, 분야별 삭제 후 교체)는 쓰지 않는다.
- 저장은 import_career_news.import_articles(링크 기준 UPSERT, 삭제 없음)를 그대로 쓴다.
  수집에 실패한 분야는 저장 대상에서 빠질 뿐이므로 그 분야의 기존 뉴스·분야·스크랩·숨김은 그대로 남는다.
- 1회 수집 후 종료한다. 주기 실행은 OS 작업 스케줄러(cron, Windows 작업 스케줄러)가 맡는다.
- 종료 코드: 0 모든 분야 수집 성공, 1 일부 분야 실패(성공한 분야는 저장), 2 저장할 뉴스 없음(DB 변경 없음)
"""

import argparse
import importlib
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from import_career_news import (  # noqa: E402
    FIELD_CODES,
    ROOT,
    build_articles,
    import_articles,
)

DEFAULT_CRAWLER_DIR = ROOT / "crawler" / "career_news_crawler"
DEFAULT_DAYS = 14
# Google News RSS에 연속 요청을 몰아 보내지 않도록 검색어 사이에 쉬는 시간(초)
DEFAULT_PAUSE = 1.0

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_NOTHING_SAVED = 2


@dataclass
class FieldResult:
    name: str
    code: str
    succeeded_queries: int = 0
    failed_queries: int = 0
    articles: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        """검색어가 하나도 성공하지 못한 분야. 크롤러 main.py와 같은 기준이다."""
        return self.succeeded_queries == 0


def load_crawler(crawler_dir: Path):
    """크롤러 폴더의 config.CATEGORIES와 collect_google_news를 불러온다. 다른 폴더의 같은 이름 모듈은 거부한다."""
    crawler_dir = crawler_dir.resolve()
    for relative in ("config.py", "src/rss_collector.py"):
        if not (crawler_dir / relative).is_file():
            raise FileNotFoundError(f"크롤러 파일이 없습니다: {crawler_dir / relative}")

    sys.path.insert(0, str(crawler_dir))
    config = importlib.import_module("config")
    rss_collector = importlib.import_module("src.rss_collector")
    for module in (config, rss_collector):
        if not Path(module.__file__).resolve().is_relative_to(crawler_dir):
            raise ImportError(f"{module.__name__} 모듈이 크롤러 폴더 밖에서 불러와졌습니다: {module.__file__}")

    check_categories(config.CATEGORIES)
    return config.CATEGORIES, rss_collector.collect_google_news


def check_categories(categories: dict) -> None:
    """크롤러 분야 이름·코드가 PlayMate 8개 직무 분야와 다르면 저장 전에 멈춘다."""
    crawler_codes = {name: (spec or {}).get("code") for name, spec in categories.items()}
    if crawler_codes != FIELD_CODES:
        raise ValueError(f"크롤러 분야가 PlayMate 직무 분야와 다릅니다: {crawler_codes}")


def collect_all(categories: dict, collect, days: int, pause: float = 0.0, session=None, log=print):
    """분야·검색어별로 수집한다. 실패한 검색어는 건너뛰고, 분야별 결과와 저장할 행을 돌려준다."""
    rows = []
    results = []
    attempts = 0
    for name, spec in categories.items():
        result = FieldResult(name=name, code=spec["code"])
        for query in spec["queries"]:
            if pause and attempts:
                time.sleep(pause)
            attempts += 1
            try:
                articles = collect(query, spec["title_keywords"], days=days, session=session)
            except Exception as error:  # 네트워크·RSS 형식 오류는 그 검색어만 실패로 본다
                result.failed_queries += 1
                result.errors.append(f"{query}: {type(error).__name__}: {str(error)[:200]}")
                continue
            result.succeeded_queries += 1
            result.articles += len(articles)
            rows.extend(
                (result.code, article.get("title"), article.get("source"), article.get("link"), article.get("published"))
                for article in articles
            )
        results.append(result)
        status = "실패 → 기존 뉴스 유지" if result.failed else f"기사 {result.articles}건"
        log(f"[{name}] 검색어 {result.succeeded_queries}/{len(spec['queries'])} 성공, {status}")
        for message in result.errors:
            log(f"  - {message}")
    return rows, results


def describe(articles, samples: int, log=print) -> None:
    """저장 전 확인용 요약: 링크 종류, 발행일 범위, 분야별 예시 제목."""
    link_types = Counter(article.link_type for article in articles)
    published = sorted(article.published_at for article in articles if article.published_at)
    log("링크 종류: " + (", ".join(f"{kind} {count}건" for kind, count in sorted(link_types.items())) or "없음"))
    if published:
        log(f"발행일(UTC): {published[0]:%Y-%m-%d %H:%M} ~ {published[-1]:%Y-%m-%d %H:%M}, 발행일 없음 "
            f"{len(articles) - len(published)}건")
    if samples:
        for code in FIELD_CODES.values():
            titles = [article.title for article in articles if code in article.field_codes][:samples]
            for title in titles:
                log(f"  {code}: {title}")


def field_freshness(cursor) -> list[dict]:
    """분야별 마지막 수집 시각. 오래 갱신되지 않은 분야를 찾는 데 쓴다."""
    cursor.execute(
        """
        SELECT f.field_code, MAX(n.last_seen_at) AS last_seen_at, COUNT(*) AS news_count
        FROM career_news_fields f
        JOIN career_news n ON n.news_id = f.news_id
        GROUP BY f.field_code
        ORDER BY f.field_code
        """
    )
    return cursor.fetchall()


def main(argv=None, *, collector=None, cursor_factory=None, log=print) -> int:
    parser = argparse.ArgumentParser(description="커리어 브리핑 뉴스 RSS 수집 → PostgreSQL career_news 저장")
    parser.add_argument("--crawler-dir", type=Path, default=DEFAULT_CRAWLER_DIR, help="career_news_crawler 폴더")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="최근 며칠치 뉴스를 수집할지 (1~30)")
    parser.add_argument("--pause", type=float, default=DEFAULT_PAUSE, help="검색어 사이 대기 시간(초)")
    parser.add_argument("--samples", type=int, default=3, help="확인용으로 보여 줄 분야별 예시 제목 수")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="DB에 저장한다. 없으면 수집 결과만 보여 준다 (DB 연결 없음)",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.days <= 30:
        parser.error("--days는 1~30 사이 숫자여야 합니다")
    if args.pause < 0 or args.samples < 0:
        parser.error("--pause, --samples는 0 이상이어야 합니다")

    if collector is None:
        import requests

        categories, collect = load_crawler(args.crawler_dir)
        session = requests.Session()
    else:
        categories, collect = collector
        check_categories(categories)
        session = None

    rows, results = collect_all(categories, collect, args.days, args.pause, session, log)
    articles, skipped = build_articles(rows)
    failed = [result.name for result in results if result.failed]
    log(f"수집 {len(rows)}건 → 중복 합친 뉴스 {len(articles)}건 (실패 분야 {len(failed)}개)")
    if skipped:
        log("건너뜀: " + ", ".join(f"{reason} {count}건" for reason, count in sorted(skipped.items())))
    describe(articles, args.samples, log)

    if not articles:
        log("저장할 뉴스가 없어 DB를 변경하지 않았습니다.")
        return EXIT_NOTHING_SAVED
    if not args.apply:
        log("확인 모드: DB에 저장하지 않았습니다. 저장하려면 --apply를 붙이세요.")
        return EXIT_PARTIAL if failed else EXIT_OK

    if cursor_factory is None:
        sys.path.insert(0, str(ROOT / "backend"))
        from app.core.db_connect import db_cursor  # noqa: E402

        cursor_factory = lambda: db_cursor(commit=True)  # noqa: E731

    seen_at = datetime.now(timezone.utc).replace(tzinfo=None)
    with cursor_factory() as cursor:
        report = import_articles(cursor, articles, seen_at)
        freshness = field_freshness(cursor)
    log(
        f"저장 완료: 신규 {report.inserted}건, 갱신 {report.updated}건, "
        f"제목으로 찾은 기존 뉴스 {report.matched_by_title}건, 분야 추가 {report.field_links_added}건"
    )
    for row in freshness:
        log(f"  {row['field_code']}: 뉴스 {row['news_count']}건, 마지막 수집 {row['last_seen_at']:%Y-%m-%d %H:%M} UTC")
    if failed:
        log("수집 실패 분야(기존 뉴스 유지): " + ", ".join(failed))
        return EXIT_PARTIAL
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
