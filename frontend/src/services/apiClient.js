import { getApiUrl } from '../config/api'

/** FastAPI 오류 문자열과 Pydantic 검증 오류 목록을 사용자 메시지로 변환한다. */
function errorMessage(data, status) {
  if (typeof data?.detail === 'string') return data.detail

  if (Array.isArray(data?.detail)) {
    return data.detail
      .map((item) => item.msg || '입력값을 확인해주세요.')
      .join(' / ')
  }

  return `API 요청 실패 (${status})`
}

/**
 * 기능과 무관한 HTTP 요청·응답 처리를 공통화한다.
 * JSON body는 호출자가 직렬화하고 FormData boundary는 브라우저가 설정한다.
 * 기본 인증 전달은 기존 fetch의 same-origin을 유지한다. 세션의 cross-origin 전달은
 * 인증 담당자가 계약을 확인한 뒤 credentials: 'include'를 명시한다.
 * signal·headers 등 fetch 옵션을 그대로 전달하며 개발용 회원 헤더는 여기서 만들지 않는다.
 * 인증 요청은 urlBuilder: getAuthUrl을 전달해 같은 요청 처리와 별도 경로를 사용한다.
 */
export async function apiRequest(
  path,
  { urlBuilder = getApiUrl, ...options } = {},
) {
  const headers = new Headers(options.headers)

  if (
    options.body != null &&
    !(options.body instanceof FormData) &&
    !headers.has('Content-Type')
  ) {
    headers.set('Content-Type', 'application/json')
  }

  // 설정 검증 오류는 네트워크 실패로 바꾸지 않고 호출자에게 그대로 전달한다.
  const url = urlBuilder(path)

  let response

  try {
    response = await fetch(url, {
      ...options,
      headers,
    })
  } catch (error) {
    if (error.name === 'AbortError') throw error

    throw new Error(
      '백엔드에 연결할 수 없습니다. FastAPI 서버와 API 주소를 확인해주세요.',
    )
  }

  if (response.status === 204) return null

  const text = await response.text()

  let data = null

  try {
    data = text ? JSON.parse(text) : null
  } catch {
    // 프록시의 HTML 오류 페이지를 그대로 표시하지 않는다.
    throw new Error(`서버 응답을 읽을 수 없습니다. (${response.status})`)
  }

  if (!response.ok) {
    const error = new Error(errorMessage(data, response.status))

    error.status = response.status
    error.data = data

    throw error
  }

  return data
}
