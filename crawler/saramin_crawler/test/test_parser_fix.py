import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from parser import parse_listing

def test_nested_card_only_one_posting():
    html = '<div class="list_item"><div class="recruit_info"><h2 class="job_tit"><a href="/zf_user/jobs/relay/view?rec_idx=101">백엔드 개발자 모집</a></h2><div class="job_sector"><a>백엔드/서버개발</a><a>Python</a></div></div></div>'
    jobs=parse_listing(html)
    assert len(jobs)==1
    assert jobs[0]['source_id']=='101'
    assert '백엔드/서버개발' in jobs[0]['job_roles']
    assert 'Python' in jobs[0]['tech_stacks']

def test_title_only_it():
    html = '<li><a href="/zf_user/jobs/relay/view?rec_idx=102">데이터 엔지니어 채용</a></li>'
    jobs=parse_listing(html)
    assert len(jobs)==1
    assert jobs[0]['job_roles']==['데이터엔지니어']

def test_non_it_not_included():
    html = '<div class="item_recruit" value="103"><a href="/zf_user/jobs/relay/view?rec_idx=103">데이터엔지니어 채용</a><div class="job_sector"><a>관리회계</a><a>법인세신고</a></div></div>'
    assert parse_listing(html)==[]

def test_non_it_title():
    html = '<li><a href="/zf_user/jobs/relay/view?rec_idx=104">영업관리 사원 채용</a></li>'
    assert parse_listing(html)==[]
