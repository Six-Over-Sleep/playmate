// PLAYMATE_ACTIVITY_V2

import { apiRequest } from './apiClient'


// 내 프로필 조회
export function getMyProfile() {
  return apiRequest('/mypage/profile', {
    credentials: 'include',
  })
}


export function updateMyNickname(nickname) {
  return apiRequest('/mypage/profile', {
    method: 'PATCH',
    credentials: 'include',
    body: JSON.stringify({ nickname }),
  })
}


export function uploadMyProfileImage(file) {
  const formData = new FormData()
  formData.append('file', file)

  return apiRequest('/mypage/profile/image', {
    method: 'POST',
    credentials: 'include',
    body: formData,
  })
}


export function getMyLevel() {
  return apiRequest('/mypage/level', {
    credentials: 'include',
  })
}

export function getMySkills() {
  return apiRequest('/mypage/skills', {
    credentials: 'include',
  })
}

// 내 활동 대시보드 통계 (로그인한 회원의 정보만 조회)
export function getMyActivitySummary() {
  return apiRequest('/mypage/summary', {
    credentials: 'include',
  })
}

const ACTIVITY_PATHS = {
  posts: '/mypage/posts',
  comments: '/mypage/comments',
  scraps: '/mypage/scraps',
  likes: '/mypage/likes', 
  meetups: '/mypage/meetups',
}



export function getMyActivities(type, page = 1) {
  const basePath = ACTIVITY_PATHS[type]

  if (!basePath) {
    throw new Error('지원하지 않는 활동 유형입니다.')
  }

  // 네 종류 모두 서버가 10개씩 반환합니다.
  const path = `${basePath}?page=${page}&page_size=10`

  return apiRequest(path, {
    credentials: 'include',
  })
}

// =========================================================
// 취업 스펙 API
// =========================================================

// 1. 내 취업 스펙 조회
export function getMyCareerSpecs() {
  return apiRequest('/mypage/career-specs', {
    credentials: 'include',
  })
}


// 2. 취업 스펙 등록 및 수정
export function saveMyCareerSpecs(data) {
  return apiRequest('/mypage/career-specs', {
    method: 'PUT',
    credentials: 'include',
    body: JSON.stringify(data),
  })
}


// 3. 취업 스펙 공개·비공개 설정
export function updateCareerSpecVisibility(isPublic) {
  return apiRequest('/mypage/career-specs/visibility', {
    method: 'PATCH',
    credentials: 'include',
    body: JSON.stringify({
      is_public: isPublic,
    }),
  })
}

// 내 XP 지급·회수 최근 30건 조회 (백엔드 기존 API 사용)
export function getMyXPHistory() {
  return apiRequest('/mypage/xp-history', {
    credentials: 'include',
  })
}

// 내가 좋아요를 누른 게시글 (10개씩)
export function getMyLikes(page = 1) {
  return apiRequest(`/mypage/likes?page=${page}&page_size=10`, {    credentials: 'include',
  })
}

// XP 획득 및 회수 이력을 전체 범위에서 페이지 단위로 조회 (기본 10개)
export function getMyXPHistoryPage(page = 1, pageSize = 10) {
  return apiRequest(`/mypage/xp-history/paged?page=${page}&page_size=${pageSize}`, {
    credentials: 'include',
  })
}
