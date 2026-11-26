from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend.app.services.career_insight_stats import load_preview, options, summarize, validate_rows
from backend.app.routers.career_insights import get_rows


class CareerInsightPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_preview()
        cls.choices = options(cls.rows)

    def test_actual_data_and_coverage(self):
        result = summarize(self.rows)
        self.assertEqual((result['total'], result['count']), (30, 30))
        self.assertEqual(result['coverage']['field'], 16)
        self.assertEqual(result['coverage']['skill'], 6)
        self.assertEqual(result['coverage']['certification'], 0)
        self.assertEqual(result['coverage']['preference'], 0)
        self.assertEqual(result['trend'], [{'id': '2026-Q4', 'count': 30}])
        self.assertEqual({x['name']: x['count'] for x in result['skills']}, {'C++': 6, 'C#': 6})

    def test_and_filters_and_reset(self):
        field = self.choices['fields'][0]
        skill = self.choices['skills'][0]
        for filters in ({'field': field}, {'skill': skill},
                        {'field': field, 'skill': skill},
                        {'quarter': '2026-Q4', 'field': field, 'skill': skill}):
            expected = sum((not filters.get('field') or filters['field'] in r['specialties'])
                           and (not filters.get('skill') or filters['skill'] in r['tech_stacks'])
                           and (not filters.get('quarter') or filters['quarter'] == f"{r['collection_year']}-Q{r['collection_quarter']}")
                           for r in self.rows)
            self.assertEqual(summarize(self.rows, **filters)['count'], expected)
        self.assertEqual(summarize(self.rows, field='없는 분야', skill='C++')['count'], 0)
        self.assertEqual(summarize(self.rows)['count'], 30)

    def test_missing_file_zero_coverage_and_deduplication(self):
        with self.assertRaises(FileNotFoundError):
            load_preview(Path(tempfile.gettempdir()) / 'missing-insights-preview.json')
        first = {**self.rows[0], 'tech_stacks': []}
        self.assertEqual(summarize(validate_rows([first, first]))['coverage']['skill'], 0)
        self.assertEqual(summarize(validate_rows([]))['coverage']['skill'], 0)
        with self.assertRaises(ValueError):
            validate_rows({'bad': 'shape'})

    def test_preview_loader_failure(self):
        self.assertEqual(len(get_rows('preview')), 30)
        with patch('backend.app.routers.career_insights.load_preview', side_effect=FileNotFoundError):
            with self.assertRaises(HTTPException) as caught:
                get_rows('preview')
            self.assertEqual(caught.exception.status_code, 503)


if __name__ == '__main__':
    unittest.main()
