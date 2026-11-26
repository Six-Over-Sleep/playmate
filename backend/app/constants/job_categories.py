"""PLAYMATE 취업 공고 분류에 사용하는 내부 직무 코드.

외부 채용 API의 직무 코드와 구분해서 사용합니다.
"""

JOB_CATEGORIES = {
    "DEV": {
        "name": "소프트웨어 개발",
        "subcategories": {
            "DEV_FE": "프론트엔드 개발",
            "DEV_BE": "백엔드 개발",
            "DEV_FULLSTACK": "풀스택 개발",
            "DEV_MOBILE": "모바일 앱 개발",
            "DEV_GAME": "게임 개발",
            "DEV_EMBEDDED": "임베디드 개발",
        },
    },
    "DATA_AI": {
        "name": "데이터·AI",
        "subcategories": {
            "DATA_ANALYST": "데이터 분석가",
            "DATA_SCIENTIST": "데이터 사이언티스트",
            "DATA_ENGINEER": "데이터 엔지니어",
            "ML_ENGINEER": "머신러닝 엔지니어",
            "AI_ENGINEER": "AI 엔지니어",
            "MLOPS": "MLOps 엔지니어",
        },
    },
    "INFRA": {
        "name": "인프라·클라우드",
        "subcategories": {
            "CLOUD": "클라우드 엔지니어",
            "DEVOPS": "DevOps 엔지니어",
            "SYSTEM_ENGINEER": "시스템 엔지니어",
            "NETWORK_ENGINEER": "네트워크 엔지니어",
            "DBA": "데이터베이스 관리자(DBA)",
        },
    },
    "SECURITY": {
        "name": "정보보안",
        "subcategories": {
            "SEC_ENGINEER": "보안 엔지니어",
            "SEC_MONITORING": "보안 관제",
            "PENTEST": "모의해킹",
            "SEC_CONSULTANT": "정보보호 컨설턴트",
        },
    },
    "IT_PLAN": {
        "name": "IT 기획·관리",
        "subcategories": {
            "SERVICE_PLANNER": "서비스 기획자",
            "PM": "프로젝트 매니저(PM)",
            "PO": "프로덕트 오너(PO)",
            "IT_CONSULTANT": "IT 컨설턴트",
            "PI_ERP": "PI·ERP",
            "IT_OPERATIONS": "IT 운영",
        },
    },
    "QA": {
        "name": "QA·테스트",
        "subcategories": {
            "QA_ENGINEER": "QA 엔지니어",
            "SW_TESTER": "소프트웨어 테스터",
            "TEST_AUTOMATION": "테스트 자동화 엔지니어",
        },
    },
    "DESIGN": {
        "name": "디자인·UX",
        "subcategories": {
            "UI_UX": "UI/UX 디자이너",
            "PRODUCT_DESIGN": "프로덕트 디자이너",
            "WEB_DESIGN": "웹 디자이너",
        },
    },
    "IT_ETC": {
        "name": "기타 IT 직무",
        "subcategories": {
            "TECH_SUPPORT": "기술지원",
            "SOLUTION_ENGINEER": "솔루션 엔지니어",
            "TECH_SALES": "기술영업",
            "IT_OTHER": "기타",
        },
    },
}


if __name__ == "__main__":
    for code, category in JOB_CATEGORIES.items():
        print(f"{category['name']} ({code})")
        for sub_code, sub_name in category["subcategories"].items():
            print(f"  - {sub_name}: {sub_code}")
