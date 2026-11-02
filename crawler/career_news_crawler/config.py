"""취업 뉴스 카테고리: 기존 job_trends_catalog.py의 FIELDS 8개와 일치."""

# code는 기존 취업 대시보드 표준 분야 코드(FIELDS)와 동일하게 지정했습니다.
# queries: Google News RSS 검색식 (그대로 전달). 큰따옴표로 감싸면 정확한 문구 검색이고,
#          OR·-제외어 같은 Google 검색 연산자를 쓸 수 있음. 결과가 충분한 분야는 기존 정확한 문구 검색을 유지.
# title_keywords: 제목 관련성 검사 (완벽한 분류기는 아님)
CATEGORIES = {
    "데이터·AI": {
        "code": "data_ai",
        "queries": ['"인공지능 산업"', '"생성형 AI 기술"', '"데이터 분석 산업"'],
        "title_keywords": ["인공지능", "생성형", "AI", "LLM", "데이터 분석", "빅데이터", "머신러닝", "딥러닝"],
    },
    "백엔드·서버": {
        "code": "backend",
        # 정확한 문구 검색은 결과 0건 → 문구 없이 검색. '백엔드 수율'(반도체 후공정) 기사는 검색에서 제외
        "queries": ["백엔드 개발 -수율 -반도체", "백엔드 개발자", "서버 개발자", "Node.js OR 스프링부트 OR Django OR FastAPI"],
        "title_keywords": ["백엔드", "서버 개발", "서버 기술", "Spring", "스프링부트", "Django", "FastAPI", "Node.js", "Java 개발자"],
    },
    "프론트엔드·웹": {
        "code": "frontend",
        "queries": ["프론트엔드", "웹 개발자", "Next.js OR React 개발 OR 리액트 개발", "자바스크립트 OR 타입스크립트 OR TypeScript"],
        # '리액트'·'React' 단독은 봉사단 이름·영어 동사(react)와 겹쳐 'React 개발'·'리액트 개발'로 좁힘
        "title_keywords": [
            "프론트엔드", "웹 개발", "React 개발", "리액트 개발", "Next.js", "웹 프레임워크", "JavaScript", "자바스크립트",
            "TypeScript", "타입스크립트", "웹 퍼블리싱", "웹 접근성", "웹 표준",
        ],
    },
    "모바일 개발": {
        "code": "mobile",
        "queries": ["안드로이드 앱 개발", "iOS 앱 개발", "모바일 앱 개발"],
        "title_keywords": ["안드로이드", "Android", "iOS", "앱 개발", "Flutter", "플러터", "리액트 네이티브", "모바일 개발", "Swift", "Kotlin"],
    },
    "클라우드·인프라": {
        "code": "cloud_infra",
        "queries": ['"클라우드 산업"', '"데이터센터 인프라"', '"AWS 클라우드"'],
        "title_keywords": ["클라우드", "데이터센터", "인프라", "AWS", "Azure", "쿠버네티스", "Kubernetes", "DevOps", "데브옵스"],
    },
    "정보보안": {
        "code": "security",
        "queries": ['"정보보안 산업"', '"사이버보안 기술"', '"랜섬웨어 보안"'],
        "title_keywords": ["보안", "정보보호", "사이버", "해킹", "랜섬웨어", "침해사고", "제로트러스트"],
    },
    "QA·테스트": {
        "code": "qa_test",
        "queries": ["소프트웨어 테스트", "테스트 자동화", "QA 엔지니어 OR 테스트 엔지니어", "소프트웨어 품질"],
        # '품질보증' 단독은 제조업 보증 비용 기사와 겹쳐 소프트웨어 품질 표현으로 좁힘
        "title_keywords": [
            "QA", "테스트 자동화", "소프트웨어 품질보증", "SW 품질", "소프트웨어 품질", "소프트웨어 테스트",
            "테스트 엔지니어", "SDET", "자동화 테스트", "테스트 관리", "테스트 설계", "소프트웨어 검증", "GS인증",
        ],
    },
    "IT기획·디자인": {
        "code": "it_product",
        "queries": ["서비스 기획자", "UX 디자인", "프로덕트 매니저 OR 프로덕트 오너", "프로덕트 디자이너"],
        "title_keywords": [
            "IT 기획", "서비스 기획", "프로덕트 매니저", "프로덕트 오너", "프로덕트 디자이너", "UX", "UI", "사용자 경험",
            "디자인 시스템",
        ],
    },
}

# '채용' 전체를 제외하지 않음: 업계 채용 트렌드도 유효한 뉴스일 수 있기 때문.
EXCLUDE_KEYWORDS = [
    "교육생 모집", "수강생 모집", "수강 신청", "취업 특강",
    "국비지원 교육", "무료 강좌", "공모전 접수", "채용공고 바로가기",
    # 교육과정 광고, 도박 광고성 글, 주식 투자 기사
    "과정 모집", "룰렛", "슬롯", "카지노", "심벌", "목표주가", "주가 전망", "특징주", "관련주",
    "Flutter Entertainment",  # 영국 베팅 기업 (모바일 'Flutter' 키워드와 겹침)
]

# 제목과 무관하게 제외할 출처: 도박 광고성 글을 올리는 사이트, 기계 번역 재게시 사이트
EXCLUDE_SOURCES = [
    "Calgary Roughnecks", "www.icaremn.com", "آي-فون إسلام", "Vietnam.vn", "Samsung Magazine",
]

DEFAULT_DAYS = 14
MAX_ARTICLES_PER_QUERY = 30
