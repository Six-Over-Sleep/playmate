/**
 * STEP 9: 분기별 채용 인사이트 데모 데이터 + 키워드 정규화 로직.
 * 모든 기업·공고·급여는 화면 테스트를 위해 생성한 가상 데이터입니다.
 * 실제 데이터 수집 이후엔 외부 모듈의 구조와 API 응답을 일치시키세요.
 */
export const FIELD_DICTIONARY = [
    { name: '소프트웨어 개발', aliases: ['SW 개발', '소프트웨어', '개발'], roles: ['프론트엔드 개발자', '백엔드 개발자', '풀스택 개발자'] },
    { name: '데이터·AI', aliases: ['데이터', '인공지능', 'AI'], roles: ['데이터 분석가', '데이터 엔지니어', 'ML 엔지니어'] },
    { name: '인프라·클라우드', aliases: ['클라우드', '인프라', 'DevOps'], roles: ['클라우드 엔지니어', 'DevOps 엔지니어', '인프라 엔지니어'] },
    { name: '정보보안', aliases: ['보안', '사이버보안'], roles: ['보안 엔지니어', '보안 분석가', '취약점 진단 담당자'] },
    { name: 'IT 기획·관리', aliases: ['IT 기획', '프로젝트 관리'], roles: ['서비스 기획자', '프로덕트 매니저', 'IT 프로젝트 매니저'] },
    { name: 'QA·테스트', aliases: ['QA', '테스트'], roles: ['QA 엔지니어', '테스트 자동화 엔지니어', 'SW 테스트 엔지니어'] },
    { name: '디자인·UX', aliases: ['UX', 'UI', '디자인'], roles: ['UX 디자이너', '프로덕트 디자이너', 'UI 디자이너'] },
    { name: '기타 IT 직무', aliases: ['IT 지원', '기타 IT'], roles: ['IT 기술 지원', '솔루션 컨설턴트', '기술 문서 담당자'] },
]


// 분야와 별도로 직무도 표준 코드/동의어로 정규화합니다.
// 실제 서비스에서는 DB 사전 테이블과 동기화할 수 있습니다.
const ROLE_ALIASES = {
    '프론트엔드 개발자': ['frontend', 'front-end', '프론트엔드'],
    '백엔드 개발자': ['backend', 'back-end', '서버 개발자'],
    '풀스택 개발자': ['fullstack', 'full-stack', '풀스택'],
    '데이터 분석가': ['data analyst', '데이터 분석'],
    '데이터 엔지니어': ['data engineer', '데이터 파이프라인 엔지니어'],
    'ML 엔지니어': ['ml engineer', 'machine learning engineer', '머신러닝 엔지니어'],
    '클라우드 엔지니어': ['cloud engineer', '클라우드 개발자'],
    'DevOps 엔지니어': ['devops engineer', '데브옵스 엔지니어'],
    '인프라 엔지니어': ['infra engineer', '인프라 운영'],
    '보안 엔지니어': ['security engineer', '보안 개발자'],
    '보안 분석가': ['security analyst', '보안 관제 분석가'],
    '취약점 진단 담당자': ['모의해킹', '취약점 분석'],
    '서비스 기획자': ['서비스 기획', 'it service planner'],
    '프로덕트 매니저': ['product manager', 'pm'],
    'IT 프로젝트 매니저': ['project manager', 'it pm'],
    'QA 엔지니어': ['qa engineer', '품질 보증'],
    '테스트 자동화 엔지니어': ['test automation engineer', '자동화 테스트'],
    'SW 테스트 엔지니어': ['software test engineer', 'sw 테스트'],
    'UX 디자이너': ['ux designer', 'ux 디자인'],
    '프로덕트 디자이너': ['product designer', '프로덕트 디자인'],
    'UI 디자이너': ['ui designer', 'ui 디자인'],
    'IT 기술 지원': ['technical support', 'it support'],
    '솔루션 컨설턴트': ['solution consultant', '솔루션 컨설팅'],
    '기술 문서 담당자': ['technical writer', '테크니컬 라이터'],
}

export const ROLE_DICTIONARY = FIELD_DICTIONARY.flatMap((field) => (
    field.roles.map((name) => ({
        field: field.name,
        name,
        aliases: ROLE_ALIASES[name] || [],
    }))
))

function normalizeLabel(raw, dictionary) {
    if (!raw) return null
    const value = raw.trim().toLocaleLowerCase('en-US')
    return dictionary.find((item) => (
        [item.name, ...item.aliases].some((alias) => alias.toLocaleLowerCase('en-US') === value)
    ))?.name || null
}

// 원문 표현을 표준 키워드로 통합합니다. 사전은 예시이며 실제 수집 전 보완이 필요합니다.
export const KEYWORD_DICTIONARY = {
    skill: [
        { name: 'Python', aliases: ['python', '파이썬'] },
        { name: 'SQL', aliases: ['sql', '관계형 쿼리'] },
        { name: 'Java', aliases: ['java', '자바'] },
        { name: 'JavaScript', aliases: ['javascript', '자바스크립트', 'JS'] },
        { name: 'React', aliases: ['react', '리액트'] },
        { name: 'TypeScript', aliases: ['typescript', '타입스크립트'] },
        { name: 'Spring Boot', aliases: ['spring boot', 'springboot', '스프링부트'] },
        { name: 'AWS', aliases: ['aws', 'amazon web services', '아마존웹서비스'] },
        { name: 'Docker', aliases: ['docker', '도커'] },
        { name: 'Kubernetes', aliases: ['kubernetes', 'k8s', '쿠버네티스'] },
        { name: 'Linux', aliases: ['linux', '리눅스'] },
        { name: 'Pandas', aliases: ['pandas', '판다스'] },
        { name: 'PyTorch', aliases: ['pytorch', '파이토치'] },
        { name: 'Airflow', aliases: ['airflow', '에어플로우'] },
        { name: 'Tableau', aliases: ['tableau', '태블로'] },
        { name: 'Figma', aliases: ['figma', '피그마'] },
        { name: 'Jira', aliases: ['jira', '지라'] },
        { name: 'Selenium', aliases: ['selenium', '셀레니움'] },
        { name: 'Git', aliases: ['git', '깃'] },
        { name: '네트워크', aliases: ['네트워크', 'networking'] },
        { name: '데이터 시각화', aliases: ['데이터 시각화', '시각화'] },
        { name: '통계 분석', aliases: ['통계 분석', '통계학'] },
    ],
    certification: [
        { name: '정보처리기사', aliases: ['정보처리기사', '정처기'] },
        { name: 'SQLD', aliases: ['sqld', 'sql 개발자', 'sql개발자'] },
        { name: 'ADsP', aliases: ['adsp', '데이터분석준전문가'] },
        { name: '빅데이터분석기사', aliases: ['빅데이터분석기사'] },
        { name: 'AWS SAA', aliases: ['aws saa', 'solutions architect associate'] },
        { name: '리눅스마스터', aliases: ['리눅스마스터'] },
        { name: '정보보안기사', aliases: ['정보보안기사'] },
        { name: 'ISTQB', aliases: ['istqb'] },
        { name: 'PMP', aliases: ['pmp'] },
    ],
    preference: [
        { name: '협업 경험', aliases: ['협업 경험', '협업 프로젝트'] },
        { name: '프로젝트 경험', aliases: ['프로젝트 경험', '실무 프로젝트'] },
        { name: '인턴 경험', aliases: ['인턴 경험', '인턴십 경험'] },
        { name: '오픈소스 기여', aliases: ['오픈소스 기여', '오픈소스 활동'] },
        { name: '문서화 능력', aliases: ['문서화 능력', '문서 작성 역량'] },
        { name: '커뮤니케이션', aliases: ['커뮤니케이션 역량', '의사소통 능력'] },
        { name: '문제 해결 능력', aliases: ['문제 해결 능력', '문제 해결 경험'] },
        { name: '영어 활용', aliases: ['영어 활용', '비즈니스 영어'] },
        { name: '클라우드 운영 경험', aliases: ['클라우드 운영 경험', '클라우드 운영'] },
        { name: '고객 대응 경험', aliases: ['고객 대응 경험', '고객 기술 지원'] },
    ],
}

// 역할별 예시 채용 키워드. 실채용 요구사항이 아니라 데모 데이터 생성 규칙입니다.
const ROLE_SEEDS = [
    { skills: ['JavaScript', 'React', 'TypeScript', 'Git'], certs: ['정보처리기사'], prefs: ['협업 경험', '프로젝트 경험', '오픈소스 기여'] },
    { skills: ['Java', 'Spring Boot', 'SQL', 'AWS'], certs: ['정보처리기사', 'SQLD'], prefs: ['협업 경험', '프로젝트 경험', '문제 해결 능력'] },
    { skills: ['React', 'Java', 'SQL', 'Docker'], certs: ['정보처리기사'], prefs: ['프로젝트 경험', '오픈소스 기여', '커뮤니케이션'] },
    { skills: ['Python', 'SQL', 'Pandas', 'Tableau', '통계 분석'], certs: ['ADsP', 'SQLD', '빅데이터분석기사'], prefs: ['프로젝트 경험', '문제 해결 능력', '문서화 능력'] },
    { skills: ['Python', 'SQL', 'AWS', 'Airflow', 'Docker'], certs: ['SQLD', '빅데이터분석기사'], prefs: ['클라우드 운영 경험', '프로젝트 경험', '협업 경험'] },
    { skills: ['Python', 'PyTorch', 'Docker', 'AWS'], certs: ['빅데이터분석기사', 'ADsP'], prefs: ['프로젝트 경험', '오픈소스 기여', '문제 해결 능력'] },
    { skills: ['AWS', 'Linux', 'Docker', 'Kubernetes'], certs: ['AWS SAA', '리눅스마스터'], prefs: ['클라우드 운영 경험', '문제 해결 능력', '영어 활용'] },
    { skills: ['Docker', 'Kubernetes', 'Linux', 'Git'], certs: ['AWS SAA', '리눅스마스터'], prefs: ['협업 경험', '클라우드 운영 경험', '문서화 능력'] },
    { skills: ['Linux', '네트워크', 'AWS', 'Python'], certs: ['리눅스마스터', '정보처리기사'], prefs: ['문제 해결 능력', '클라우드 운영 경험', '프로젝트 경험'] },
    { skills: ['Linux', '네트워크', 'Python'], certs: ['정보보안기사', '리눅스마스터'], prefs: ['문제 해결 능력', '프로젝트 경험', '문서화 능력'] },
    { skills: ['네트워크', 'SQL', 'Python'], certs: ['정보보안기사', 'SQLD'], prefs: ['문서화 능력', '협업 경험', '문제 해결 능력'] },
    { skills: ['네트워크', 'Linux', 'Python'], certs: ['정보보안기사'], prefs: ['프로젝트 경험', '문제 해결 능력', '커뮤니케이션'] },
    { skills: ['SQL', 'Jira', 'Figma'], certs: ['정보처리기사', 'SQLD'], prefs: ['커뮤니케이션', '문서화 능력', '협업 경험'] },
    { skills: ['SQL', 'Jira', '데이터 시각화'], certs: ['PMP', 'SQLD'], prefs: ['커뮤니케이션', '문제 해결 능력', '프로젝트 경험'] },
    { skills: ['Jira', 'SQL', 'Git'], certs: ['PMP', '정보처리기사'], prefs: ['프로젝트 경험', '문서화 능력', '협업 경험'] },
    { skills: ['Selenium', 'Python', 'SQL'], certs: ['ISTQB', '정보처리기사'], prefs: ['문제 해결 능력', '프로젝트 경험', '문서화 능력'] },
    { skills: ['Selenium', 'Python', 'Git'], certs: ['ISTQB'], prefs: ['프로젝트 경험', '협업 경험', '문서화 능력'] },
    { skills: ['Selenium', 'SQL', 'Jira'], certs: ['ISTQB', '정보처리기사'], prefs: ['문제 해결 능력', '협업 경험', '프로젝트 경험'] },
    { skills: ['Figma', '데이터 시각화'], certs: [], prefs: ['프로젝트 경험', '커뮤니케이션', '협업 경험'] },
    { skills: ['Figma', 'Git'], certs: [], prefs: ['프로젝트 경험', '문서화 능력', '협업 경험'] },
    { skills: ['Figma', 'React'], certs: [], prefs: ['커뮤니케이션', '프로젝트 경험', '문제 해결 능력'] },
    { skills: ['SQL', 'Linux', '네트워크'], certs: ['정보처리기사'], prefs: ['고객 대응 경험', '문서화 능력', '문제 해결 능력'] },
    { skills: ['SQL', 'AWS', '커뮤니케이션'], certs: ['AWS SAA'], prefs: ['고객 대응 경험', '커뮤니케이션', '영어 활용'] },
    { skills: ['Git', 'Linux', 'SQL'], certs: ['정보처리기사'], prefs: ['문서화 능력', '고객 대응 경험', '프로젝트 경험'] },
]

const QUARTERS = [
    { id: '2025-Q1', label: '2025년 1분기', year: 2025, quarter: 1, counts: [8, 9, 6, 7, 7, 6, 5, 4] },
    { id: '2025-Q2', label: '2025년 2분기', year: 2025, quarter: 2, counts: [10, 11, 8, 7, 7, 6, 5, 5] },
    { id: '2025-Q3', label: '2025년 3분기', year: 2025, quarter: 3, counts: [11, 13, 8, 8, 8, 7, 6, 5] },
    { id: '2025-Q4', label: '2025년 4분기', year: 2025, quarter: 4, counts: [9, 12, 9, 9, 8, 7, 7, 5] },
    { id: '2026-Q1', label: '2026년 1분기', year: 2026, quarter: 1, counts: [13, 14, 10, 9, 8, 8, 6, 5] },
    { id: '2026-Q2', label: '2026년 2분기', year: 2026, quarter: 2, counts: [12, 17, 11, 10, 9, 9, 6, 6] },
    { id: '2026-Q3', label: '2026년 3분기', year: 2026, quarter: 3, counts: [11, 21, 12, 10, 9, 11, 7, 6] },
]
export const CAREER_QUARTERS = QUARTERS.map(({ id, label, year, quarter }) => ({ id, label, year, quarter }))

function displayAlias(group, name, seed) {
    const keyword = KEYWORD_DICTIONARY[group].find((item) => item.name === name)
    if (!keyword) return name
    return keyword.aliases[seed % keyword.aliases.length]
}

const allRoles = ROLE_DICTIONARY.map((item) => item.name)

function createDemoPosting(yearQuarter, fieldIndex, index, serial) {
    const field = FIELD_DICTIONARY[fieldIndex]
    const roleIndex = fieldIndex * 3 + ((index + Math.floor(serial / 17)) % 3)
    const role = allRoles[roleIndex]
    const seed = ROLE_SEEDS[roleIndex]
    const chosenSkills = [seed.skills[index % seed.skills.length], seed.skills[(index + 1) % seed.skills.length]]
    const chosenCerts = seed.certs.length && index % 5 !== 0 ? [seed.certs[index % seed.certs.length]] : []
    const chosenPrefs = [seed.prefs[index % seed.prefs.length], seed.prefs[(index + 1) % seed.prefs.length]]
    const quarterStart = (yearQuarter.quarter - 1) * 3 + 1
    const month = quarterStart + (index % 3)
    const day = 1 + ((index * 7 + fieldIndex * 3) % 27)
    const salaryAvailable = index % 4 !== 0
    const salaryMin = salaryAvailable ? (3100 + fieldIndex * 170 + (index % 7) * 270) * 10000 : null
    const salaryMax = salaryAvailable ? salaryMin + (500 + (index % 4) * 160) * 10000 : null
    return {
        source: '가상 데이터',
        source_posting_id: `DEMO-${String(serial).padStart(4, '0')}`,
        company_name: `가상기업 ${String.fromCharCode(65 + fieldIndex)}`,
        title: `${role} (화면 테스트용)`,
        field_raw: field.name,
        role_raw: role,
        posted_at: serial % 29 === 0 ? null : `${yearQuarter.year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`,
        collected_at: `${yearQuarter.year}-${String(month).padStart(2, '0')}-${String(Math.min(day + 1, 28)).padStart(2, '0')}T09:00:00`,
        qualifications_raw: index % 11 === 0 ? null : chosenSkills.map((name, position) => displayAlias('skill', name, serial + position)).join(', '),
        preferences_raw: index % 13 === 0 ? null : chosenPrefs.map((name, position) => displayAlias('preference', name, serial + position)).join(', '),
        certifications_raw: chosenCerts.length ? displayAlias('certification', chosenCerts[0], serial) : null,
        salary_min_krw: salaryMin,
        salary_max_krw: salaryMax,
        salary_period: salaryAvailable ? 'YEAR' : null,
        original_url: null,
    }
}

const generated = []
let serial = 0
for (const quarter of QUARTERS) {
    quarter.counts.forEach((count, fieldIndex) => {
        for (let index = 0; index < count; index += 1) {
            serial += 1
            generated.push(createDemoPosting(quarter, fieldIndex, index, serial))
        }
    })
}

// 화면에 표시할 때는 raw + normalized를 함께 유지합니다.
// 동일 공고의 다중 출처 중복 제거 등은 API 연결 시 추가해야 합니다.
function containsAlias(source, alias) {
    const text = (source || '').toLocaleLowerCase('en-US')
    const term = alias.toLocaleLowerCase('en-US')
    let index = text.indexOf(term)
    while (index !== -1) {
        const first = term[0]
        const last = term[term.length - 1]
        const before = index > 0 ? text[index - 1] : ''
        const after = text[index + term.length] || ''
        const asciiWord = (char) => /[a-z0-9]/i.test(char)
        const startOk = !asciiWord(first) || !asciiWord(before)
        const endOk = !asciiWord(last) || !asciiWord(after)
        if (startOk && endOk) return true
        index = text.indexOf(term, index + 1)
    }
    return false
}

export function extractKeywords(text, group) {
    if (!text) return []
    return KEYWORD_DICTIONARY[group]
        .filter((word) => word.aliases.some((alias) => containsAlias(text, alias)))
        .map((word) => word.name)
}

export const CAREER_POSTINGS_DEMO = generated.map((raw) => ({
    ...raw,
    field: normalizeLabel(raw.field_raw, FIELD_DICTIONARY),
    role: normalizeLabel(raw.role_raw, ROLE_DICTIONARY),
    quarter: raw.posted_at ? `${raw.posted_at.slice(0, 4)}-Q${Math.floor((Number(raw.posted_at.slice(5, 7)) - 1) / 3) + 1}` : null,
    skills: extractKeywords(raw.qualifications_raw, 'skill'),
    preferences: extractKeywords(raw.preferences_raw, 'preference'),
    certifications: extractKeywords(raw.certifications_raw, 'certification'),
}))
