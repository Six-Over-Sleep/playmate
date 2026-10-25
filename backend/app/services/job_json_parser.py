"""사람인 API 형태의 JSON을 PLAYMATE 채용공고 데이터로 변환합니다.

실제 API 요청은 하지 않습니다. 로컬 샘플로 파싱·분류만 확인합니다.
"""

from app.services.job_classifier import classify_job


def parse_jobs(response: dict) -> list[dict]:
    """사람인 응답의 jobs.job 목록을 공통 형식으로 정리합니다."""
    jobs = response.get("jobs", {}).get("job", [])
    if isinstance(jobs, dict):  # 공고가 1건인 응답도 허용
        jobs = [jobs]

    results = []
    for job in jobs:
        position = job.get("position", {})
        title = position.get("title", "")
        job_id = job.get("id")

        # 기본 식별 정보가 없으면 저장 대상으로 사용하지 않습니다.
        if not title or not job_id:
            continue

        company = job.get("company", {}).get("detail", {})
        category = classify_job(title)

        results.append({
            "source": "saramin",
            "source_job_id": str(job_id),
            "title": title,
            "company": company.get("name", ""),
            "location": position.get("location", {}).get("name", ""),
            "employment_type": position.get("job-type", {}).get("name", ""),
            "experience": position.get("experience-level", {}).get("name", ""),
            "url": job.get("url", ""),
            "category_code": category["category_code"] if category else None,
            "subcategory_code": category["subcategory_code"] if category else None,
        })

    return results


if __name__ == "__main__":
    # 사람인 공식 JSON 필드 구조를 따른 가상 테스트 데이터 (실제 공고 아님)
    sample_response = {
        "jobs": {
            "count": 3,
            "job": [
                {
                    "id": "TEST001",
                    "url": "https://example.com/jobs/1",
                    "company": {"detail": {"name": "예시테크"}},
                    "position": {
                        "title": "[신입] Python 데이터 분석가 채용",
                        "location": {"name": "서울 > 강남구"},
                        "job-type": {"name": "정규직"},
                        "experience-level": {"name": "신입"},
                    },
                },
                {
                    "id": "TEST002",
                    "url": "https://example.com/jobs/2",
                    "company": {"detail": {"name": "샘플소프트"}},
                    "position": {
                        "title": "Java 백엔드 개발자 모집",
                        "location": {"name": "경기 > 성남시"},
                        "job-type": {"name": "계약직"},
                        "experience-level": {"name": "경력"},
                    },
                },
                {
                    "id": "TEST003",
                    "url": "https://example.com/jobs/3",
                    "company": {"detail": {"name": "테스트랩"}},
                    "position": {
                        "title": "프론트엔드 / 백엔드 개발자 채용",
                        "location": {"name": "서울"},
                        "job-type": {"name": "정규직"},
                        "experience-level": {"name": "경력무관"},
                    },
                },
            ],
        }
    }

    for job in parse_jobs(sample_response):
        code = job["subcategory_code"] or "미분류(검토 필요)"
        print(f"{job['company']} | {job['title']} | {code}")
