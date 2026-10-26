// 프로젝트 참여 신청 폼의 순수 검증과 API payload 변환만 담당함.
// 확정/대기 여부는 서버가 결정하므로 프론트에서 계산하지 않음.

export const EMPTY_APPLICATION_FORM = {
  selectedSkillIds: [],
  leaderVolunteer: false,
  directInput: {
    skills: '',
    education: '',
    certificates: '',
    experience: '',
    awards: '',
    portfolio_url: '',
  },
}

export function splitSkillText(value) {
  return String(value ?? '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

export function nullableText(value) {
  const text = String(value ?? '').trim()
  return text || null
}

export function isValidHttpUrl(value) {
  const text = String(value ?? '').trim()

  if (!text) {
    return true
  }

  try {
    const url = new URL(text)
    return url.protocol === 'http:' || url.protocol === 'https:'
  } catch {
    return false
  }
}

export function validateApplicationStep(step, form) {
  // 최종 제출 시에도 필수 기술이 남아 있는지 다시 검증함.
  if (form.selectedSkillIds.length === 0) {
    return '담당할 필수 기술을 1개 이상 선택해주세요.'
  }

  if (
    step >= 2 &&
    !isValidHttpUrl(form.directInput.portfolio_url)
  ) {
    return '포트폴리오 링크는 http:// 또는 https:// 주소로 입력해주세요.'
  }

  return ''
}

export function buildApplicationPayload(form) {
  return {
    skill_ids: form.selectedSkillIds,
    career_item_ids: [],
    leader_volunteer: Boolean(form.leaderVolunteer),
    direct_input: {
      skills: splitSkillText(form.directInput.skills),
      education: nullableText(form.directInput.education),
      certificates: nullableText(form.directInput.certificates),
      experience: nullableText(form.directInput.experience),
      awards: nullableText(form.directInput.awards),
      portfolio_url: nullableText(form.directInput.portfolio_url),
    },
  }
}

export function getApplicationResultLabel(status) {
  switch (String(status ?? '').toUpperCase()) {
    case 'ACCEPTED':
      return '참여 확정'
    case 'WAITING':
      return '대기 접수'
    default:
      return ''
  }
}
