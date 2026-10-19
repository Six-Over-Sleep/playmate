/**
 * 브라우저가 사용하는 FastAPI origin. 로컬에서는 빈 값으로 Vite 프록시를 사용한다.
 * 별도 서버를 설정할 때는 https://api.example.com처럼 /api 없는 origin만 지정한다.
 * VITE_ 값은 공개되므로 토큰·비밀번호를 저장하지 않는다.
 */
function getBackendOrigin() {
  const origin = (import.meta.env.VITE_BACKEND_ORIGIN || '')
    .trim()
    .replace(/\/+$/, '')
  if (origin) {
    const parsed = new URL(origin)
    if (
      !['http:', 'https:'].includes(parsed.protocol) ||
      parsed.origin !== origin
    ) {
      throw new Error(
        'VITE_BACKEND_ORIGIN에는 경로·인증정보 없는 http(s) 서버 주소만 설정해주세요.',
      )
    }
  }
  return origin
}

/** 게시판·모임 경로를 연결한다. 호출자는 /api 없이 /boards 등의 경로만 전달한다. */
export function getApiUrl(path) {
  return `${getBackendOrigin()}/api/${path.replace(/^\/+/, '')}`
}

/** 인증은 /api가 아닌 /auth를 사용한다. OAuth 이동 주소 생성에도 사용할 수 있다. */
export function getAuthUrl(path) {
  return `${getBackendOrigin()}/auth/${path.replace(/^\/+/, '')}`
}

/** 절대 URL, /uploads/posts/... 응답, posts/... 저장 경로를 구분해 uploads 중복을 막는다. */
export function resolveMediaUrl(path) {
  if (!path || /^https?:\/\//i.test(path)) return path
  const origin = getBackendOrigin()
  const relative = path.replace(/^\/+/, '')
  if (relative.startsWith('uploads/')) return `${origin}/${relative}`
  return `${origin}/uploads/${relative}`
}
