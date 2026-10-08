# Backend

커뮤니티 서비스의 FastAPI 백엔드 서버를 개발하는 폴더임.

회원 인증, 게시글, 댓글, 좋아요, 모임, 정보공유, 분실물, 자격증, 취업정보 등의 API와 서비스 로직을 담당함.

## 폴더 구조

| 세컨 폴더 | 써드 폴더 | 설명 |
|---|---|---|
| `app/` | `routers/` | API URL 및 엔드포인트 관리 영역임 |
| `app/` | `models/` | 데이터베이스 ORM 모델 관리 영역임 |
| `app/` | `schemas/` | Request / Response 데이터 구조 정의 영역임 |
| `app/` | `services/` | 실제 서비스 기능 및 비즈니스 로직 처리 영역임 |
| `app/` | `core/` | DB 연결, 환경설정, 인증 등 공통 설정 영역임 |

```text
backend/
├─ app/
│  ├─ routers/
│  ├─ models/
│  ├─ schemas/
│  ├─ services/
│  └─ core/
└─ README.md
```

## 폴더 설명

### `app/routers/`

FastAPI API 엔드포인트를 작성함.

예시는 다음과 같음.

```text
auth.py
posts.py
comments.py
restaurants.py
lost_items.py
certificates.py
```

### `app/models/`

데이터베이스 테이블과 연결되는 ORM 모델을 작성함.

예시는 다음과 같음.

```text
member.py
post.py
comment.py
category.py
restaurant.py
```

### `app/schemas/`

Pydantic을 이용하여 API의 Request / Response 데이터 구조를 정의함.

예시는 다음과 같음.

```text
PostCreate
PostResponse
CommentCreate
MemberResponse
```

### `app/services/`

실제 서비스 기능을 처리함.

주요 작업은 다음과 같음.

- 게시글 등록
- 게시글 수정
- 좋아요 처리
- 댓글 작성
- 분실물 등록
- 사용자 권한 처리

### `app/core/`

프로젝트 전체에서 사용하는 공통 설정을 관리함.

예시는 다음과 같음.

```text
database.py
config.py
security.py
```

DB 연결, 환경변수, Discord OAuth 등의 설정을 관리함.

## 관리 규칙

API 경로 정의와 실제 처리 로직을 하나의 파일에 모두 작성하지 않음.

비밀번호, API Key, OAuth Secret 등의 민감정보는 `.env` 파일로 관리함.

`.env` 파일은 GitHub에 업로드하지 않음.