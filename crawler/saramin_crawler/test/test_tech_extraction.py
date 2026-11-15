"""Offline smoke tests: python -m unittest crawler/saramin_crawler/test/test_tech_extraction.py"""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from parser import inspect_detail, parse_listing

class TestTech(unittest.TestCase):
    def test_detail_skills(self):
        html = '<html><body><main><h2>지원 자격</h2><p>Python, SQL, Docker 활용</p></main></body></html>'
        result = inspect_detail(html)
        self.assertIn('Python', result['tech_stacks'])
        self.assertIn('SQL', result['tech_stacks'])
        self.assertIn('Docker', result['tech_stacks'])
    def test_iframe_diagnostic(self):
        result = inspect_detail('<html><body><iframe src="/somepage"></iframe></body></html>')
        self.assertTrue(result['has_iframe'])
        self.assertEqual(result['tech_stacks'], [])
    def test_listing_skill_tags(self):
        html = '''<div class="item_recruit" value="123456"><div class="area_job"><h2 class="job_tit"><a href="/zf_user/jobs/relay/view?rec_idx=123456">데이터 엔지니어 채용</a></h2></div><div class="job_skill"><span>Python</span></div></div>'''
        rows = parse_listing(html)
        self.assertEqual(len(rows),1)
        self.assertIn('Python', rows[0]['tech_stacks'])

if __name__=='__main__':unittest.main()
