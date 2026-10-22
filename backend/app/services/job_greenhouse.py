"""STEP 5: Greenhouse 공개 API에서 실제 채용공고를 가져와 직무를 분류합니다.

DB 저장은 아직 하지 않습니다. 기존 job_classifier.py를 재사용합니다.
"""

import requests

from app.services.job_classifier import classify_job


# GitLab의 공개 채용 게시판으로 먼저 수집 테스트합니다.
BOARD_TOKEN = "gitlab"
API_URL = f"https://boards-api.greenhouse.io/v1/boards/{BOARD_TOKEN}/jobs"


def fetch_jobs() -> list[dict]:
    """채용공고를 조회하고 PLAYMATE 공통 필드로 변환합니다."""
    response = requests.get(API_URL, timeout=15)
    response.raise_for_status()  # 오류 응답이면 예외 발생
    data = response.json()

    results = []
    for item in data.get("jobs", []):
        title = item.get("title", "")
        job_id = item.get("id")
        if not title or job_id is None:
            continue

        category = classify_job(title)
        results.append({
            "source": "greenhouse",
            "source_job_id": str(job_id),
            "company": item.get("company_name") or "GitLab",
            "title": title,
            "location": (item.get("location") or {}).get("name", ""),
            "url": item.get("absolute_url", ""),
            "updated_at": item.get("updated_at", ""),
            "category_code": category["category_code"] if category else None,
            "subcategory_code": category["subcategory_code"] if category else None,
        })

    return results


if __name__ == "__main__":
    try:
        jobs = fetch_jobs()
        classified = [job for job in jobs if job["subcategory_code"]]
        print(f"전체 공고: {len(jobs)}건")
        print(f"자동 분류 성공: {len(classified)}건")
        print("\n예시 공고 (자동 분류된 공고 우선, 최대 10건):")

        for job in (classified or jobs)[:10]:
            print(f"- {job['title']}")
            print(f"  기업: {job['company']} / 지역: {job['location']}")
            print(f"  직무 코드: {job['subcategory_code'] or '미분류'}")
            print(f"  원문: {job['url']}\n")

    except (requests.RequestException, ValueError) as exc:
        print(f"API 조회 실패: {exc}")
