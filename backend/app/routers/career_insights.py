"""실제 DB 기반 인사이트. main.py에서 router를 include_router 하세요."""
from __future__ import annotations
import os
from collections import Counter
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row
import psycopg

router = APIRouter(prefix='/api/career/insights',tags=['career-insights'])

def connect():
    url=os.getenv('DATABASE_URL') or os.getenv('POSTGRES_DSN')
    if url:return psycopg.connect(url,row_factory=dict_row)
    args={'host':os.getenv('DB_HOST'),'dbname':os.getenv('DB_NAME'),
          'user':os.getenv('DB_USER'),'password':os.getenv('DB_PASSWORD'),
          'port':os.getenv('DB_PORT','5432')}
    if not all(args.values()):raise RuntimeError('DATABASE_URL 또는 DB_* 환경변수 필요')
    return psycopg.connect(**args,row_factory=dict_row)

def quarters():
    now=datetime.now()
    serial=now.year*4+(now.month-1)//3
    return [{'year':(serial-i)//4,'quarter':(serial-i)%4+1,'id':f'{(serial-i)//4}-Q{(serial-i)%4+1}'} for i in (3,2,1,0)]

def ranked(rows,key,limit=5):
    c=Counter()
    for row in rows:
        c.update(set(v for v in (row.get(key) or []) if v))
    return [{'name':k,'count':v} for k,v in sorted(c.items(),key=lambda item:(-item[1],item[0]))[:limit]]

def load_rows():
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT source_id,job_roles,specialties,tech_stacks,certifications,preferences,collection_year,collection_quarter FROM saramin_insight_jobs')
            return cur.fetchall()

@router.get('/filters')
def filters():
    try: rows=load_rows()
    except (psycopg.Error,RuntimeError) as e:
        raise HTTPException(503,'DB 조회 실패: 인사이트 마이그레이션과 연결 설정을 확인하세요') from e
    return {'quarters':quarters(),
            'fields':sorted({x for r in rows for x in (r['specialties'] or [])}),
            'skills':sorted({x for r in rows for x in (r['tech_stacks'] or [])}),
            'total':len(rows)}

@router.get('/summary')
def summary(quarter:str|None=Query(default=None,pattern=r'^\d{4}-Q[1-4]$'),
            field:str|None=None, skill:str|None=None):
    try:rows=load_rows()
    except (psycopg.Error,RuntimeError) as e:
        raise HTTPException(503,'DB 조회 실패: 인사이트 마이그레이션과 연결 설정을 확인하세요') from e
    # 복수 조건 모두 AND. 분기 미지정 시 전체 수집 데이터 사용.
    selected=[r for r in rows if
              (not quarter or f"{r['collection_year']}-Q{r['collection_quarter']}"==quarter)
              and (not field or field in (r['specialties'] or []))
              and (not skill or skill in (r['tech_stacks'] or []))]
    # 차트는 분기 필터와 관계없이 분야/기술 조건을 적용하여 4분기 비교
    trend_basis=[r for r in rows if (not field or field in (r['specialties'] or [])) and (not skill or skill in (r['tech_stacks'] or []))]
    qs=quarters()
    trend=[{**q,'count':sum(r['collection_year']==q['year'] and r['collection_quarter']==q['quarter'] for r in trend_basis)} for q in qs]
    return {'count':len(selected),'total':len(rows), 'filters':{'quarter':quarter,'field':field,'skill':skill},
            'fields':ranked(selected,'specialties'),'skills':ranked(selected,'tech_stacks'),
            'certifications':ranked(selected,'certifications'),'preferences':ranked(selected,'preferences'),
            'roles':ranked(selected,'job_roles'), 'trend':trend,
            'note':'분기는 첫 수집일 기준이며, 미수집 분기의 0은 채용 수요 0을 뜻하지 않습니다.',
            'coverage':{'field':sum(bool(r.get('specialties')) for r in selected),
                        'skill':sum(bool(r.get('tech_stacks')) for r in selected),
                        'certification':sum(bool(r.get('certifications')) for r in selected),
                        'preference':sum(bool(r.get('preferences')) for r in selected)}}
