"""채용공고 제목을 PLAYMATE 내부 직무 코드로 분류합니다 (1차 버전)."""

from app.constants.job_categories import JOB_CATEGORIES

# 시작 단계에서는 제목으로 구분하기 쉬운 직무부터 분류합니다.
# 나머지 직무 키워드는 실제 채용공고를 확인하면서 확장합니다.
JOB_KEYWORDS = {
    "DEV_FE": ["프론트엔드", "frontend", "front-end"],
    "DEV_BE": ["백엔드", "backend", "back-end"],
    "DATA_ANALYST": ["데이터 분석가", "데이터 분석", "data analyst"],
    "DATA_ENGINEER": ["데이터 엔지니어", "data engineer"],
    "DEVOPS": ["devops", "데브옵스"],
    "SEC_ENGINEER": ["보안 엔지니어", "security engineer"],
    "PI_ERP": ["erp 개발", "erp 운영", "erp 컨설턴트", "pi 컨설턴트"],
    "QA_ENGINEER": ["qa 엔지니어", "qa engineer"],
    "UI_UX": ["ui/ux", "ux/ui", "ux 디자이너"],
    "TECH_SUPPORT": ["기술지원", "technical support"],
}


def classify_job(title: str) -> dict | None:
    """제목에서 직무를 1개만 찾으면 분류 결과를 반환합니다.

    결과가 없거나 직무가 2개 이상 감지되면 None (검토 필요)을 반환합니다.
    """
    normalized_title = title.casefold()
    matches = []

    for sub_code, keywords in JOB_KEYWORDS.items():
        if any(keyword.casefold() in normalized_title for keyword in keywords):
            matches.append(sub_code)

    if len(matches) != 1:
        return None

    sub_code = matches[0]
    for category_code, category in JOB_CATEGORIES.items():
        if sub_code in category["subcategories"]:
            return {
                "category_code": category_code,
                "category_name": category["name"],
                "subcategory_code": sub_code,
                "subcategory_name": category["subcategories"][sub_code],
            }
    return None


if __name__ == "__main__":
    titles = [
        "[신입] Python 데이터 분석가 채용",
        "Java 백엔드 개발자 모집",
        "클라우드 DevOps 엔지니어 채용",
        "프론트엔드 / 백엔드 개발자 채용",  # 복수 직무: 자동 분류하지 않음
        "IT 인재 모집",  # 식별 불가: 자동 분류하지 않음
    ]
    for title in titles:
        result = classify_job(title)
        label = result["subcategory_name"] if result else "미분류(검토 필요)"
        print(f"{title} → {label}")
