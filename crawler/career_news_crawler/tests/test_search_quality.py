"""검색식·출처 제외·분야 키워드 변경(PlayMate Issue #74)을 네트워크 없이 확인한다."""
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from urllib.parse import parse_qs, urlsplit

from config import CATEGORIES, EXCLUDE_SOURCES
from src.rss_collector import collect_google_news, is_relevant


def rss(items):
    published = format_datetime(datetime.now(timezone.utc) - timedelta(days=1))
    body = "".join(
        f"<item><title>{title} - {source}</title><link>https://news.google.com/rss/articles/{index}?oc=5</link>"
        f"<pubDate>{published}</pubDate><source url='https://example.com'>{source}</source></item>"
        for index, (title, source) in enumerate(items)
    )
    return f"<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel>{body}</channel></rss>".encode()


class FakeSession:
    def __init__(self, content):
        self.content = content
        self.urls = []

    def get(self, url, timeout=None, headers=None):
        self.urls.append(url)
        return self

    def raise_for_status(self):
        pass


def search_query(url):
    return parse_qs(urlsplit(url).query)["q"][0]


class SearchExpressionTests(unittest.TestCase):
    def test_query_is_sent_as_written(self):
        session = FakeSession(rss([]))
        collect_google_news('"클라우드 산업"', ["클라우드"], days=14, session=session)
        collect_google_news("백엔드 개발 -수율 -반도체", ["백엔드"], days=7, session=session)
        self.assertEqual(search_query(session.urls[0]), '"클라우드 산업" when:14d')
        self.assertEqual(search_query(session.urls[1]), "백엔드 개발 -수율 -반도체 when:7d")

    def test_fields_with_enough_results_keep_exact_phrase_search(self):
        for name in ("데이터·AI", "클라우드·인프라", "정보보안"):
            for query in CATEGORIES[name]["queries"]:
                self.assertTrue(query.startswith('"') and query.endswith('"'), query)

    def test_excluded_source_is_skipped(self):
        session = FakeSession(rss([("자바스크립트 룰렛 화면 구성", EXCLUDE_SOURCES[0]),
                                   ("자바스크립트 디버깅 가이드", "요즘IT")]))
        articles = collect_google_news("자바스크립트", ["자바스크립트"], days=14, session=session)
        self.assertEqual([(a["title"], a["source"]) for a in articles], [("자바스크립트 디버깅 가이드", "요즘IT")])


class FieldKeywordTests(unittest.TestCase):
    def keywords(self, name):
        return CATEGORIES[name]["title_keywords"]

    def test_frontend_react_needs_development_context(self):
        self.assertFalse(is_relevant("안산 리액트봉사단 공식 출범", self.keywords("프론트엔드·웹")))
        self.assertFalse(is_relevant("Barcelona must analyse and react", self.keywords("프론트엔드·웹")))
        self.assertTrue(is_relevant("Next.js 모바일 웹을 앱으로 바꾼 방법", self.keywords("프론트엔드·웹")))
        self.assertTrue(is_relevant("타입스크립트 7 정식 출시", self.keywords("프론트엔드·웹")))

    def test_qa_quality_means_software_quality(self):
        self.assertFalse(is_relevant("부품사, 품질보증 비용 2000만 달러 추가", self.keywords("QA·테스트")))
        self.assertTrue(is_relevant("플래티어, AI 테스트 관리 솔루션 출시", self.keywords("QA·테스트")))
        self.assertTrue(is_relevant("에이전트 플랫폼 GS인증 1등급 획득", self.keywords("QA·테스트")))

    def test_global_exclusions(self):
        self.assertFalse(is_relevant("정보보안 관련주 옥석 가리기", self.keywords("정보보안")))
        self.assertFalse(is_relevant("CRWV 주가 전망: 클라우드 산업 경고", self.keywords("클라우드·인프라")))
        self.assertFalse(is_relevant("Flutter Entertainment 목표주가 하향", self.keywords("모바일 개발")))
        self.assertFalse(is_relevant("UI/UX 웹퍼블리셔 양성과정 모집", self.keywords("프론트엔드·웹")))
        self.assertTrue(is_relevant("KISA, 선박 사이버 침해사고 시험장 공개", self.keywords("정보보안")))


if __name__ == "__main__":
    unittest.main()
