# FastAPI 공통 설정 사용 가이드

## 이번에 적용한 범위

공통 설정과 요청 함수를 만들고 게시판에 먼저 적용했습니다. 모임·인증 담당자는 이 변경이 병합된 뒤 아래 예시에 맞춰 자기 기능에 적용합니다. 기존 모임·인증 호출 코드는 이번에 변경하지 않았습니다.

| 파일 | 역할 |
| --- | --- |
| `src/config/api.js` | 서버 origin, `/api`, `/auth`, `/uploads` 주소와 이미지 URL 생성 |
| `src/services/apiClient.js` | HTTP 요청, JSON·FormData, 오류·204 응답, 취소 처리 |
| `src/services/boardApi.js` | 게시판 endpoint·payload와 기존 개발용 회원 헤더 연결 |
| `vite.config.js` | 로컬 요청을 `.env`에 지정한 FastAPI로 전달 |

주소 상수를 import하지 않고 `getApiUrl()`, `getAuthUrl()`, `resolveMediaUrl()` 공통 함수를 사용합니다. 환경 설정 읽기와 주소 검증은 함수 안에서 수행하고, 호출한 곳에는 완성된 주소를 반환합니다. `.env` 이름은 그대로 유지합니다. 함수를 호출하더라도 Vite 설정은 빌드·시작 시 적용되므로 `.env` 변경 후에는 개발 서버 재시작 또는 재빌드가 필요합니다.

## 개인 PC 설정

환경 변수는 기존 `envDir` 규칙대로 `frontend/.env`가 아닌 저장소 루트 `.env`에 둡니다. 현재 PC에서는 `C:\dev\project\playmate\.env`입니다.

기존 DB·인증 설정을 지우지 말고 다음 두 항목을 추가합니다. 이미 있으면 같은 키를 중복 추가하지 않습니다.

```env
# 빈 값이면 현재 웹사이트로 요청하고 개발 프록시를 사용합니다.
VITE_BACKEND_ORIGIN=
# 내 PC에서 실행하는 FastAPI 주소입니다.
BACKEND_PROXY_TARGET=http://localhost:8000
```

`.env.example`에는 위 예시가 있습니다. 실제 `.env`는 Git에서 제외되며 계정·비밀번호가 있으므로 공유하지 않습니다. 환경 변수 변경 후에는 Vite를 재시작합니다.

## 로컬 요청 흐름

```text
boardApi.boards()
  → apiRequest('/boards')
  → getApiUrl('/boards')가 환경 설정을 읽어 주소 생성
  → 브라우저가 /api/boards 요청
  → Vite가 BACKEND_PROXY_TARGET으로 전달
  → FastAPI의 /api/boards
```

프록시는 `/api`, `/auth`, `/uploads`의 경로를 변경하지 않습니다. 서버 주소는 프록시 환경 변수 한 곳에서 관리합니다.

## 다른 기능 담당자의 적용 예시

### 모임 API

`src/services/meetupApi.js`에서 사용할 때의 예시입니다. 실제 기존 endpoint와 반환 형식은 유지하세요.

```javascript
import { apiRequest } from './apiClient'

// /api는 공통 설정에 포함돼 있으므로 /recruits만 전달합니다.
export function getMeetup(recruitId) {
  return apiRequest(`/recruits/${recruitId}`)
}
```

### 인증 API

인증의 기존 prefix는 `/api`가 아니라 `/auth`입니다. JSON 인증 확인 API는 다음처럼 주소를 만드는 함수 `getAuthUrl`을 전달합니다. `urlBuilder`는 “이 함수를 사용해 요청 주소를 만들어 주세요”라는 옵션입니다.

```javascript
import { getAuthUrl } from '../config/api'
import { apiRequest } from './apiClient'

export function getCurrentMember() {
  return apiRequest('/me', {
    urlBuilder: getAuthUrl,
    credentials: 'include',
  })
}
```

이 예시는 인증 담당자가 적용할 코드이며 현재 인증 코드가 변경됐다는 뜻은 아닙니다. OAuth 로그인 시작처럼 브라우저 이동이 필요한 요청은 `fetch`로 기계적으로 바꾸지 말고 기존 이동 흐름과 redirect URI를 확인하세요.

### 이미지

```javascript
import { resolveMediaUrl } from '../config/api'

resolveMediaUrl('/uploads/posts/photo.png')
resolveMediaUrl('posts/photo.png')
// 로컬: /uploads/posts/photo.png
// 별도 서버: https://api.example.com/uploads/posts/photo.png
```

모든 이미지 주소는 `resolveMediaUrl()` 공통 함수를 거칩니다. `/uploads/...` 같은 경로에는 설정된 백엔드 주소를 붙이고, `https://...`처럼 서버 주소까지 포함된 URL은 중복해서 붙이지 않고 반환합니다. 현재 게시판은 `/uploads/...` 경로를 사용합니다.

## 인증 전달 규칙

- 공용 client는 기존 fetch의 same-origin 인증 동작을 유지합니다.
- 다른 origin으로 세션 쿠키를 전달해야 하면 담당자가 계약을 확인하고 `credentials: 'include'`를 명시합니다. 서버 CORS·쿠키 설정도 함께 맞춰야 합니다.
- 게시판의 `VITE_DEV_MEMBER_ID`는 기존 개발용 헤더입니다. 게시판 어댑터만 이 헤더를 추가하며 다른 기능에 강제하지 않습니다.
- 공용 client를 연결했다고 실제 로그인 인증까지 완료되는 것은 아닙니다.

## 요청 함수 사용 규칙

- JSON은 `body: JSON.stringify(payload)`로 전달합니다.
- 파일은 `FormData`를 전달합니다. Content-Type은 직접 지정하지 않습니다.
- 삭제가 204를 반환하면 결과는 `null`입니다.
- 실패 시 Error를 던지고, 요청 취소 시 AbortError를 그대로 전달합니다.
- 조회 취소는 `{ signal: controller.signal }`로 연결합니다.
- API 경로에는 `/api` 또는 `/auth` prefix를 중복 작성하지 않습니다.

## 별도 서버 배포

```env
VITE_BACKEND_ORIGIN=https://api.example.com
```

위 주소는 예시입니다. 실제 백엔드 주소로 바꾸고 `/api`를 붙이지 않습니다. 다시 빌드하면 게시판 API와 이미지가 함께 해당 서버를 사용합니다. 현재 모임·인증은 아직 이 설정으로 전환하지 않았으므로 담당자의 적용이 필요합니다.

같은 도메인 배포에서는 origin을 빈 값으로 유지할 수 있지만 배포 서버가 `/api`, `/auth`, `/uploads`를 FastAPI로 전달해야 합니다. Vite 개발 프록시는 배포 후 자동으로 작동하지 않습니다. `VITE_` 값은 빌드에 포함되는 공개 설정이므로 비밀값을 넣지 않습니다.

기존 `VITE_API_BASE_URL`은 아직 모임 코드에서 사용하므로 제거하지 않았습니다. 해당 담당자의 전환 후 정리합니다.

## 검증

로컬 상대 경로와 별도 서버 origin에 대해 API·인증·이미지 주소, JSON·FormData, 개발 헤더 격리, 204, 검증 오류, 잘못된 서버 응답, 요청 취소를 검증했습니다. 모의 API 브라우저에서 게시판 목록·상세·이미지 연결도 확인했습니다. 실제 DB·로그인·별도 서버 CORS 및 OAuth 연동은 별도 확인이 필요합니다.

주소 제공을 함수 방식으로 변경한 뒤에도 빌드와 로컬·별도 서버 주소, 인증 경로 선택, 이미지 경로, 게시판 호출 연결, JSON·FormData, 개발 헤더 격리, 204, 검증 오류와 취소 처리를 다시 확인했습니다. 공통 주소 상수 export는 제거했으며 기존 인증 담당 코드의 상수는 이번 범위에서 변경하지 않았습니다.
