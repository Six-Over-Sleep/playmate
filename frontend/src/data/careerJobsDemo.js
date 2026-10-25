/**
 * 채용 인사이트 화면 검증용 가상 데이터.
 * 실제 기업·공고·채용 상태와 무관하며 외부 서비스에서 수집한 정보가 아닙니다.
 * API 연동 시 이 모듈만 실데이터 호출로 교체할 수 있도록 분리합니다.
 */
export const JOB_CATEGORIES = [
    '소프트웨어 개발',
    '데이터·AI',
    '인프라·클라우드',
    '정보보안',
    'IT 기획·관리',
    'QA·테스트',
    '디자인·UX',
    '기타 IT 직무',
]

const FAMILIES = [
    { category: JOB_CATEGORIES[0], titles: ['프론트엔드 개발자', '백엔드 개발자', '풀스택 개발자'], skills: ['JavaScript', 'React', 'TypeScript', 'Java', 'Spring', 'Git'] },
    { category: JOB_CATEGORIES[1], titles: ['데이터 분석가', '머신러닝 엔지니어', '데이터 엔지니어'], skills: ['Python', 'SQL', 'Pandas', 'PyTorch', 'Airflow', 'AWS'] },
    { category: JOB_CATEGORIES[2], titles: ['클라우드 엔지니어', 'DevOps 엔지니어', '인프라 엔지니어'], skills: ['AWS', 'Docker', 'Kubernetes', 'Linux', 'Terraform', 'Python'] },
    { category: JOB_CATEGORIES[3], titles: ['보안 엔지니어', '보안 분석가', '취약점 진단 담당자'], skills: ['Linux', 'Python', 'SIEM', '네트워크', 'AWS', 'SQL'] },
    { category: JOB_CATEGORIES[4], titles: ['IT 서비스 기획자', '프로덕트 매니저', 'IT 프로젝트 매니저'], skills: ['SQL', 'Jira', 'Figma', 'Excel', 'Python', 'Notion'] },
    { category: JOB_CATEGORIES[5], titles: ['QA 엔지니어', '자동화 테스트 엔지니어', 'SW 테스트 엔지니어'], skills: ['Python', 'Selenium', 'Cypress', 'Jira', 'SQL', 'Git'] },
    { category: JOB_CATEGORIES[6], titles: ['UX 디자이너', '프로덕트 디자이너', 'UI 디자이너'], skills: ['Figma', 'Photoshop', 'UX 리서치', '프로토타이핑', 'HTML', 'CSS'] },
    { category: JOB_CATEGORIES[7], titles: ['IT 기술 지원', '솔루션 컨설턴트', '기술 문서 담당자'], skills: ['SQL', 'Linux', 'Excel', 'Python', 'Git', '문서화'] },
]

const COMPANIES = ['샘플기업 A', '샘플기업 B', '샘플기업 C', '샘플기업 D', '샘플기업 E', '샘플기업 F', '샘플기업 G', '샘플기업 H']
const LOCATIONS = ['서울', '경기', '인천', '부산', '대전']
const EMPLOYMENT_TYPES = ['정규직', '계약직', '인턴']
const EXPERIENCE_LEVELS = ['신입', '경력', '무관']

// 각 분야 6개씩, 총 48개의 화면 테스트 공고를 구성합니다.
export const CAREER_JOBS_DEMO = FAMILIES.flatMap((family, familyIndex) => (
    Array.from({ length: 6 }, (_, index) => {
        const selectedSkills = [
            family.skills[index % family.skills.length],
            family.skills[(index + 1) % family.skills.length],
            family.skills[(index + 3) % family.skills.length],
        ]

        return {
            id: `DEMO-${familyIndex + 1}-${index + 1}`,
            company_name: COMPANIES[(familyIndex * 2 + index) % COMPANIES.length],
            title: `${family.titles[index % family.titles.length]} (예시)`,
            job_category: family.category,
            experience_level: EXPERIENCE_LEVELS[(familyIndex + index) % EXPERIENCE_LEVELS.length],
            location: LOCATIONS[(familyIndex + index) % LOCATIONS.length],
            employment_type: EMPLOYMENT_TYPES[(index + familyIndex) % EMPLOYMENT_TYPES.length],
            skills: [...new Set(selectedSkills)],
            week: 1 + ((index * 3 + familyIndex * 2 + Number(index > 2)) % 6),
            original_url: null,
            source: '화면 테스트용 가상 데이터',
        }
    })
))

export const DEMO_WEEKS = ['1주차', '2주차', '3주차', '4주차', '5주차', '6주차']
