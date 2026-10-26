
import { apiRequest } from './apiClient'

// 개발 환경에서만 테스트 회원 ID 사용
const devMemberId = import.meta.env.DEV
  ? import.meta.env.VITE_DEV_MEMBER_ID
  : null

// 내 프로필 조회
export function getMyProfile() {
  return apiRequest('/mypage/profile', {
    credentials: 'include',
    headers: devMemberId
      ? { 'X-Dev-Member-ID': devMemberId }
      : {},
  })
}


export function updateMyNickname(nickname) {
  return apiRequest('/mypage/profile', {
    method: 'PATCH',
    credentials: 'include',
    headers: devMemberId
      ? { 'X-Dev-Member-ID': devMemberId }
      : {},
    body: JSON.stringify({ nickname }),
  })
}


export function uploadMyProfileImage(file) {
  const formData = new FormData()
  formData.append('file', file)

  return apiRequest('/mypage/profile/image', {
    method: 'POST',
    credentials: 'include',
    headers: devMemberId
      ? { 'X-Dev-Member-ID': devMemberId }
      : {},
    body: formData,
  })
}


export function getMyLevel() {
  return apiRequest('/mypage/level', {
    credentials: 'include',
    headers: devMemberId
      ? { 'X-Dev-Member-ID': devMemberId }
      : {},
  })
}

export function getMySkills() {
  return apiRequest('/mypage/skills', {
    credentials: 'include',
    headers: devMemberId
      ? { 'X-Dev-Member-ID': devMemberId }
      : {},
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

  // 게시글과 댓글은 Backend 페이지네이션
  const usePagination = ['posts', 'comments'].includes(type)

  const path = usePagination
    ? `${basePath}?page=${page}&page_size=10`
    : basePath

  return apiRequest(path, {
    credentials: 'include',
    headers: devMemberId
      ? { 'X-Dev-Member-ID': devMemberId }
      : {},
  })
}

