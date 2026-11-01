"""1회 RSS 수집 후 종료. 작업 스케줄러/cron에서 주기적으로 실행하세요."""

import argparse

from config import CATEGORIES, DEFAULT_DAYS
from src.database import init_db, replace_categories
from src.rss_collector import collect_google_news


def collect_news(days: int = DEFAULT_DAYS) -> dict[str, int]:
    results: dict[str, list[dict]] = {}
    for category, config in CATEGORIES.items():
        collected = []
        successful_queries = 0
        for query in config["queries"]:
            print(f"[{category}] {query} 수집 중")
            try:
                articles = collect_google_news(query, config["title_keywords"], days=days)
            except Exception as error:
                print(f"  RSS 수집 실패: {error}")
                continue
            successful_queries += 1
            collected.extend({"category": category, **article} for article in articles)

        if successful_queries and collected:
            results[category] = collected
        else:
            print(f"  [{category}] 저장 결과 없음 → 기존 뉴스 보존")

    if not results:
        print("수집된 기사가 없어 DB를 변경하지 않았습니다.")
        return {}
    counts = replace_categories(results)
    print(f"갱신 완료: {sum(counts.values())}건 / {len(counts)}개 분야")
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="취업 분야별 Google News RSS 수집")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="최근 며칠치 뉴스를 수집할지")
    args = parser.parse_args()
    if args.days < 1 or args.days > 365:
        parser.error("--days는 1~365 사이 숫자여야 합니다")
    init_db()
    collect_news(days=args.days)
