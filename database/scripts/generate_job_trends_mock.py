"""공식 응답 모양의 가상 시연 데이터. 실제 채용 통계가 아니다."""

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random


QUARTERS = {"2025-Q1": 51, "2025-Q2": 57, "2025-Q3": 63, "2025-Q4": 64,
            "2026-Q1": 71, "2026-Q2": 77, "2026-Q3": 84}
# 공식 직무 코드표에서 확인한 코드만 사용한다.
TEMPLATES = [
    ("데이터 분석가", "82", "데이터분석가", "Python"),
    ("데이터 사이언티스트", "2248", "데이터 사이언티스트", "Python"),
    ("백엔드 개발자 / Java 개발자", "84,235", "백엔드/서버개발,Java", "Java"),
    ("프론트엔드 개발자", "92", "프론트엔드", "React"),
    ("LLM 엔지니어 / AI 에이전트 개발자", "181", "AI(인공지능)", "Python"),
    ("Android 개발자", "195", "Android", "Kotlin"),
    ("클라우드 엔지니어", "136", "클라우드", "AWS"),
    ("보안관제 분석가", "2239", "보안관제", "정보보안"),
    ("QA 엔지니어", "99", "QA/테스터", "테스트"),
    ("데이터 엔지니어", "83", "데이터엔지니어", "Python"),
]


def generate(seed=31, sample=False):
    rng = random.Random(seed)
    jobs = []
    kst = timezone(timedelta(hours=9))
    for quarter, count in QUARTERS.items():
        year, q = quarter.split('-Q')
        start = datetime(int(year), (int(q) - 1) * 3 + 1, 1, tzinfo=kst)
        for index in range(count):
            sequence = len(jobs)
            title, code, name, keyword = TEMPLATES[sequence % len(TEMPLATES)]
            posted = start + timedelta(days=rng.randrange(80), hours=rng.randrange(24))
            stamp = str(int(posted.timestamp()))
            job_id = str(90000000 + sequence)
            job = {
                "id": job_id,
                "url": f"https://www.saramin.co.kr/zf_user/jobs/relay/view?rec_idx={job_id}",
                "active": 0,
                "posting-timestamp": stamp, "modification-timestamp": stamp,
                "opening-timestamp": stamp,
                "expiration-timestamp": str(int((posted + timedelta(days=30)).timestamp())),
                "close-type": {"code": "1", "name": "접수마감일"},
                "company": {"detail": {"name": f"가상 플레이메이트 소프트웨어 {sequence % 17 + 1}"}},
                "position": {
                    "title": f"[가상 시연] {title} 채용",
                    "location": {"code": "101070", "name": "서울 > 구로구"},
                    "industry": {"code": "301", "name": "솔루션·SI·ERP·CRM"},
                    "job-mid-code": {"code": "2", "name": "IT개발·데이터"},
                    "job-code": {"code": code, "name": name},
                    "job-type": {"code": "1", "name": "정규직"},
                    "experience-level": {"code": 0, "min": 0, "max": 0, "name": "경력무관"},
                    "required-education-level": {"code": "0", "name": "학력무관"},
                },
                "keyword": keyword,
                "salary": {"code": "6", "name": "1,800~2,000만원"},
            }
            if sequence % 7 == 0:
                job.pop('salary')
            if sequence % 11 == 1:
                job.pop('keyword')
            if sequence % 13 == 3:
                job.pop('company')
            jobs.append(job)
            if sample and len(jobs) == 5:
                return {"jobs": {"count": 5, "start": 0, "total": "5", "job": jobs}}
    return {"jobs": {"count": len(jobs), "start": 0, "total": str(len(jobs)), "job": jobs}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sample', action='store_true')
    parser.add_argument('--seed', type=int, default=31)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(generate(args.seed, args.sample), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
