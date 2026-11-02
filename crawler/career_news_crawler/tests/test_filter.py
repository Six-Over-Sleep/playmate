import sys
import types
import unittest
from unittest.mock import patch

# 테스트 환경에 feedparser/requests가 없는 경우에도 제목 필터를 검증하기 위한 가짜 모듈
# (실제 실행 시에는 pyproject.toml의 라이브러리를 설치하세요.)
if 'feedparser' not in sys.modules:
    try:
        import feedparser
    except ImportError:
        sys.modules['feedparser'] = types.SimpleNamespace(parse=lambda _: {})
from src.rss_collector import contains_keyword, is_relevant


class FilterTests(unittest.TestCase):
    def test_keyword_boundary(self):
        self.assertTrue(contains_keyword('AI 산업 전망', 'AI'))
        self.assertFalse(contains_keyword('PAID 서비스', 'AI'))

    def test_include_exclude(self):
        self.assertTrue(is_relevant('생성형 AI 산업에 투자 확대', ['AI']))
        self.assertFalse(is_relevant('AI 수강생 모집 안내', ['AI']))
        self.assertFalse(is_relevant('반도체 가격 상승', ['AI']))


if __name__ == '__main__':
    unittest.main()
