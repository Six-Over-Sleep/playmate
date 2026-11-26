import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import database


class DatabaseTests(unittest.TestCase):
    def test_dedup_preserve_categories(self):
        with tempfile.TemporaryDirectory() as d, patch.object(database, 'DB_PATH', Path(d) / 'news.db'):
            database.init_db()
            row = {"title": "AI 시장 확대", "source": "예시신문", "link": "https://example.com/1", "published": "2026-10-29T00:00:00+00:00"}
            database.replace_categories({"데이터·AI": [row, row], "정보보안": [dict(row, title="보안 투자 확대")]})
            self.assertEqual(len(database.get_news()), 2)
            database.replace_categories({"데이터·AI": []})
            self.assertEqual(len(database.get_news("데이터·AI")), 1)
            database.replace_categories({"데이터·AI": [dict(row, title="생성형 AI 업데이트")]})
            self.assertEqual(len(database.get_news("데이터·AI")), 1)
            self.assertEqual(len(database.get_news("정보보안")), 1)


if __name__ == '__main__':
    unittest.main()
