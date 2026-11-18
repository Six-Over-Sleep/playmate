/**
 * 취업 커뮤니티의 화면 표시용 통합 메뉴.
 * 저장된 게시글의 subcategory_code는 변경하지 않으며, 한 화면 메뉴가
 * 여러 기존 코드를 가리키도록 서버 목록 필터에서 OR 조회합니다.
 */
export const CAREER_MENU_GROUPS = {
    reviews: [
        { label: '서류 후기', codes: ['DOCUMENT'] },
        { label: '코테·과제 후기', codes: ['CODING_ASSIGNMENT'] },
        { label: '면접 후기', codes: ['INTERVIEW'] },
        { label: '최종 결과·합격 후기', codes: ['FINAL', 'SUCCESS'] },
    ],
    talk: [
        { label: '취업·진로 고민', codes: ['JOB_SEARCH', 'CAREER_PATH'] },
        { label: '이직·연봉 고민', codes: ['JOB_CHANGE', 'SALARY'] },
        { label: '일상·근황', codes: ['DAILY', 'UPDATE'] },
    ],
    lounge: [
        { label: '현직 생활', codes: ['DAILY_WORK', 'COMPANY_LIFE', 'JUNIOR_TIPS'] },
        { label: '실무·직무 Q&A', codes: ['WORK_SKILLS', 'JOB_QNA'] },
        { label: '선배 인터뷰', codes: ['ALUMNI_INTERVIEW'] },
    ],
    lab: [
        { label: '서류·포트폴리오 피드백', codes: ['PORTFOLIO_FEEDBACK', 'RESUME'] },
        { label: '면접·기술 준비', codes: ['TECH_INTERVIEW'] },
        { label: '취업 전략·스펙', codes: ['JOB_STRATEGY', 'CERTIFICATION', 'JOB_COMPARISON'] },
    ],
}

export function getCareerMenuLabels(category) {
    return (CAREER_MENU_GROUPS[category] || []).map(({ label }) => label)
}

export function getCareerMenuCodes(category, label) {
    return (CAREER_MENU_GROUPS[category] || []).find((item) => item.label === label)?.codes || []
}

export function getCareerMenuCode(category, label) {
    return getCareerMenuCodes(category, label)[0] || null
}

export function getCareerMenuLabel(category, code) {
    return (CAREER_MENU_GROUPS[category] || []).find(({ codes }) => codes.includes(code))?.label || null
}

/** 기존 게시글과 신규 작성/수정 모두 정확한 통합 메뉴에서 검색됩니다. */
export function getCareerMenuQuery(category, label) {
    const codes = getCareerMenuCodes(category, label)
    if (codes.length === 1) return { subcategory_code: codes[0] }
    if (codes.length > 1) return { subcategory_codes: codes.join(',') }
    return {}
}
