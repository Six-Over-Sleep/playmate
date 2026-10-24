"""PlayMate 내부 분류. 사람인 원본 코드와 별도로 관리한다."""

FIELDS = [
    ("data_ai", "데이터·AI"), ("backend", "백엔드·서버"),
    ("frontend", "프론트엔드·웹"), ("mobile", "모바일 개발"),
    ("cloud_infra", "클라우드·인프라"), ("security", "정보보안"),
    ("qa_test", "QA·테스트"), ("it_product", "IT기획·디자인"),
]
ROLE_GROUPS = [
    [("data_analyst", "데이터 분석가"), ("data_scientist", "데이터 사이언티스트"),
     ("data_engineer", "데이터 엔지니어"), ("ml_engineer", "머신러닝 엔지니어"),
     ("deep_learning_engineer", "딥러닝 엔지니어"), ("llm_engineer", "LLM 엔지니어"),
     ("ai_agent_developer", "AI 에이전트 개발자"), ("mlops_engineer", "MLOps 엔지니어"),
     ("ai_researcher", "AI 연구원")],
    [("backend_engineer", "백엔드 개발자"), ("java_engineer", "Java 개발자"), ("python_engineer", "Python 개발자")],
    [("frontend_engineer", "프론트엔드 개발자"), ("web_publisher", "웹 퍼블리셔"), ("fullstack_engineer", "풀스택 개발자")],
    [("android_engineer", "Android 개발자"), ("ios_engineer", "iOS 개발자"), ("cross_platform_engineer", "크로스플랫폼 개발자")],
    [("cloud_engineer", "클라우드 엔지니어"), ("devops_engineer", "DevOps 엔지니어"), ("system_engineer", "시스템 엔지니어")],
    [("security_engineer", "보안 엔지니어"), ("soc_analyst", "보안관제 분석가"), ("penetration_tester", "모의해킹 전문가")],
    [("qa_engineer", "QA 엔지니어"), ("test_automation_engineer", "테스트 자동화 엔지니어"), ("software_quality_manager", "SW 품질 관리자")],
    [("service_planner", "서비스 기획자"), ("product_manager", "PM/PO"), ("ux_ui_designer", "UX/UI 디자이너")],
]
ROLES = [(field[0], code, name) for field, group in zip(FIELDS, ROLE_GROUPS) for code, name in group]

# 최소 연결 예제이며 전체 기술·자격증 사전은 후속 분석 담당자가 제공한다.
KEYWORDS = [("python", "Python", "skill"), ("java", "Java", "skill")]
