# Frontend

React 기반 커뮤니티 웹 화면을 개발하는 폴더임.

게시판, 모임, 정보공유, 분실물, 자격증, 취업 등의 사용자 화면을 구현함.

FastAPI 백엔드와의 API 통신도 해당 영역에서 처리함.

## 폴더 구조

| 세컨 폴더 | 써드 폴더 | 설명 |
|---|---|---|
| `public/` | - | 정적 파일 관리 영역임 |
| `src/` | `components/` | 재사용 가능한 UI 컴포넌트 관리 영역임 |
| `src/` | `pages/` | 실제 페이지 화면 관리 영역임 |
| `src/` | `services/` | Backend API 통신 코드 관리 영역임 |
| `src/` | `assets/` | 이미지, 아이콘 등 리소스 관리 영역임 |

```text
frontend/
├─ public/
├─ src/
│  ├─ components/
│  ├─ pages/
│  ├─ services/
│  └─ assets/
└─ README.md
```

## 폴더 설명

### `public/`

브라우저에서 그대로 제공되는 정적 파일을 저장함.

예시는 다음과 같음.

```text
favicon.ico
```

### `src/components/`

여러 페이지에서 반복해서 사용하는 UI 컴포넌트를 저장함.

예시는 다음과 같음.

```text
Header.jsx
Sidebar.jsx
PostCard.jsx
Comment.jsx
Modal.jsx
```

### `src/pages/`

사용자가 실제로 접근하는 페이지 단위 화면을 저장함.

커뮤니티의 주요 카테고리 화면이 해당됨.

예시는 다음과 같음.

```text
Home.jsx
Board.jsx
Group.jsx
Information.jsx
LostItem.jsx
Certificate.jsx
Employment.jsx
```

### `src/services/`

FastAPI Backend와 통신하는 API 코드를 저장함.

예시는 다음과 같음.

```text
api.js
authApi.js
postApi.js
commentApi.js
restaurantApi.js
```

### `src/assets/`

프론트엔드에서 사용하는 이미지, 로고, 아이콘 등의 리소스를 저장함.

예시는 다음과 같음.

```text
logo.png
banner.png
icons/
```

## 관리 규칙

API 요청 코드를 React Component 내부에 반복해서 작성하지 않고 `services/`에서 관리함.

여러 화면에서 반복해서 사용하는 UI는 `components/`로 분리함.

특정 페이지에서만 사용하는 작은 컴포넌트는 필요 이상으로 분리하지 않음.