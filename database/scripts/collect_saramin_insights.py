"""2개 데이터 직무 × 최대 15건, 기존 웹 크롤러 재사용. 루트에서 실행.
명시적 허가/약관 확인 후 사용. robots.txt/접근 제한 우회 없음.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'crawler' / 'saramin_crawler'))
from crawler import SaraminWebCrawler

TARGETS = ('데이터분석가','데이터엔지니어')
CERTS = {
    '정보처리기사': r'정보\s*처리\s*기사',
    '빅데이터분석기사': r'빅데이터\s*분석\s*기사',
    'SQLD': r'(?<![A-Za-z])SQLD(?![A-Za-z])|SQL\s*개발자',
    'SQLP': r'(?<![A-Za-z])SQLP(?![A-Za-z])',
    'ADsP': r'(?<![A-Za-z])ADsP(?![A-Za-z])|데이터\s*분석\s*준전문가',
    'ADP': r'(?<![A-Za-z])ADP(?![A-Za-z])|데이터\s*분석\s*전문가',
    'AWS 자격증': r'AWS\s*(?:certified|자격증)',
}

def certs(job):
    text=' '.join([job.get('title') or '',*job.get('raw_tags',[]),*job.get('preferences',[])])
    return [name for name,pattern in CERTS.items() if re.search(pattern,text,re.I)]

def pick(rows, each=15):
    selected, ids, counts=[],set(),{x:0 for x in TARGETS}
    for row in rows:
        rid=str(row['source_id'])
        if rid in ids: continue
        roles=set(row.get('job_roles') or [])
        eligible=[r for r in TARGETS if r in roles and counts[r]<each]
        if not eligible:continue
        chosen=min(eligible,key=lambda x:counts[x])
        # 직무 전체 태그는 보존. 선택한 핵심 직무도 따로 명시하지 않고 필터에는 배열 그대로 사용.
        counts[chosen]+=1
        ids.add(rid)
        row['certifications']=certs(row)
        selected.append(row)
        if all(counts[x]>=each for x in TARGETS):break
    return selected,counts

def get_conn():
    import psycopg
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    url=os.getenv('DATABASE_URL') or os.getenv('POSTGRES_DSN')
    if url: return psycopg.connect(url)
    required=('DB_HOST','DB_NAME','DB_USER','DB_PASSWORD')
    if not all(os.getenv(k) for k in required):
        raise RuntimeError('DATABASE_URL 또는 DB_HOST, DB_NAME, DB_USER, DB_PASSWORD를 .env에 설정하세요.')
    return psycopg.connect(host=os.getenv('DB_HOST'), dbname=os.getenv('DB_NAME'), user=os.getenv('DB_USER'), password=os.getenv('DB_PASSWORD'),port=os.getenv('DB_PORT','5432'))

def save(rows):
    """Legacy preview script: writes are intentionally disabled.

    The job_postings ingestion is owned by the separate data-collection teammate.
    This prevents accidentally recreating or writing to saramin_insight_jobs.
    """
    raise RuntimeError(
        '이 스크립트의 --apply 적재는 비활성화되었습니다. '
        'job_postings 적재는 담당자의 별도 파이프라인을 사용하세요.'
    )

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--max-pages',type=int,default=10)
    p.add_argument('--per-role',type=int,default=15)
    p.add_argument('--details',action='store_true',help='허가된 상세페이지에서 추가 정보 추출을 시도')
    p.add_argument('--apply',action='store_true',help='DB 적재; 미지정시 JSON 미리보기만')
    p.add_argument('--output',default='saramin_insights_preview.json')
    args=p.parse_args()
    if args.max_pages<1 or args.per_role<1:p.error('max-pages와 per-role은 1 이상이어야 합니다')
    crawler=SaraminWebCrawler()
    rows=crawler.crawl(max_pages=args.max_pages,details=args.details)
    selected,counts=pick(rows,args.per_role)
    target=ROOT/args.output
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(selected,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print('선별 건수:',counts,'| 전체:',len(selected),'| 미리보기:',target)
    if any(v<args.per_role for v in counts.values()):
        print('주의: 조건 충족 공고 부족. 존재하지 않는 데이터를 채우지 않습니다. 페이지 수 또는 수집 조건 점검 필요.')
    if args.apply and selected:
        save(selected)
        print('PostgreSQL UPSERT 완료:',len(selected),'건')
    elif not args.apply:print('DB 저장 없음. --apply로 적재하세요.')

if __name__=='__main__':main()
