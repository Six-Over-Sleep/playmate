# PlayMate Backend

PlayMate 커뮤니티 서비스의 **FastAPI 기반 백엔드 서버**입니다.

회원 인증, 회원가입, 게시판, 댓글, 모임 등 서비스의 API와 비즈니스 로직을 담당합니다.

현재 로그인 기능은 **Discord OAuth2 기반 간편 로그인 및 회원가입** 방식으로 구현되어 있습니다.

---

## 1. 기술 스택

| 구분 | 기술 |
|---|---|
| Language | Python 3.13 이상 |
| Backend | FastAPI |
| Package Manager | uv |
| Database | Aiven PostgreSQL |
| Database Driver | psycopg |
| ORM | SQLAlchemy |
| HTTP Client | httpx |
| Data Validation | Pydantic |
| Authentication | Discord OAuth2 |
| Session | Starlette SessionMiddleware |
| API Documentation | Swagger UI |

---

## 2. 백엔드 구조

```text
backend/
├── app/
│   ├── __init__.py
│   ├── main.py
│   │
│   ├── core/
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── db_connect.py
│   │   └── uploads.py
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── board.py
│   │   └── recruit.py
│   │
│   ├── services/
│   │   ├── auth_service.py
│   │   ├── member_service.py
│   │   ├── board_service.py
│   │   └── recruit.py
│   │
│   ├── repositories/
│   │   ├── __init__.py
│   │   └── board_repository.py
│   │
│   ├── schemas/
│   │   └── member.py
│   │
│   └── models/
│       └── member.py
│
├── tests/
│   └── test_auth_flow.py
│
└── README.md
```

### 주요 파일 역할

| 파일 | 역할 |
|---|---|
| `main.py` | FastAPI 애플리케이션 생성, 미들웨어 설정 및 라우터 등록 |
| `core/config.py` | `.env` 환경변수 로드 |
| `core/database.py` | psycopg 직접 연결 및 SQLAlchemy 세션 생성 |
| `core/db_connect.py` | DB 상태 확인 등 공통 DB 연결 기능 |
| `core/uploads.py` | 업로드 파일 경로 관리 |
| `routers/auth.py` | Discord 로그인, 콜백, 회원가입, 회원 조회, 로그아웃 API |
| `routers/board.py` | 게시판 관련 API |
| `routers/recruit.py` | 모임 관련 API |
| `services/auth_service.py` | Discord 토큰 교환 및 사용자 정보 조회 |
| `repositories/board_repository.py` | 게시판 SQL 실행과 결과 매핑, 이미지 일괄 조회 (커밋하지 않음) |
| `services/board_service.py` | 게시판 업무 순서, 작성자 권한, 트랜잭션 경계 관리 |
| `services/member_service.py` | PostgreSQL 회원 조회 및 신규 회원 등록 |
| `services/recruit.py` | 모임 관련 비즈니스 로직 |
| `schemas/member.py` | 회원가입 요청 데이터 검증 |
| `tests/test_auth_flow.py` | Discord 인증 이후 신규·기존 회원 분기 테스트 |

### 폴더별 역할

- `routers/`: API 엔드포인트 정의
- `services/`: 비즈니스 로직, 트랜잭션 관리 및 외부 서비스 통신
- `repositories/`: 게시판 SQL 실행 및 결과 매핑
- `schemas/`: Pydantic 요청·응답 데이터 구조 및 검증
- `models/`: 데이터베이스 ORM 모델 정의
- `core/`: DB 연결, 환경변수, 업로드 등 공통 설정
- `tests/`: 백엔드 기능 테스트

---

## 3. 개발 환경 설정

Windows / VS Code / PowerShell 기준입니다.

### 3.1 프로젝트 Clone

```powershell
git clone git@github.com:Six-Over-Sleep/playmate.git
cd playmate
```

필요한 브랜치로 이동합니다.

```powershell
git switch 브랜치명
```

이미 Clone한 경우에는 다시 Clone할 필요가 없습니다.

---

### 3.2 uv 환경 설정

프로젝트 최상위 `playmate/` 폴더에서 실행합니다.

```powershell
uv sync
```

`pyproject.toml`에 정의된 의존성을 기반으로 `.venv` 환경을 구성합니다.

현재 주요 라이브러리는 다음과 같습니다.

```text
fastapi
uvicorn
httpx
python-dotenv
itsdangerous
pydantic
psycopg[binary]
sqlalchemy
```

필요한 라이브러리를 추가할 때는 다음 명령어를 사용합니다.

```powershell
uv add 패키지명
```

---

### 3.3 환경변수 설정

프로젝트 최상위에 `.env` 파일을 생성합니다.

```text
playmate/
├── .env
├── pyproject.toml
├── backend/
├── frontend/
└── database/
```

`.env` 파일 구성 예시:

```dotenv
# Discord OAuth2
DISCORD_CLIENT_ID=your_client_id
DISCORD_CLIENT_SECRET=your_client_secret
DISCORD_REDIRECT_URI=http://localhost:8000/auth/discord/callback

# Session
SESSION_SECRET_KEY=your_random_session_secret

# PostgreSQL
DB_HOST=your_database_host
DB_PORT=your_database_port
DB_USER=your_database_user
DB_PASSWORD=your_database_password
DB_NAME=your_database_name
DB_SSLMODE=require

# Frontend
FRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

Discord 관련 설정값은 Discord Developer Portal에서 확인할 수 있습니다.

- OAuth2 Scope: `identify`
- Redirect URI: `http://localhost:8000/auth/discord/callback`

`SESSION_SECRET_KEY`는 다음 명령어로 생성할 수 있습니다.

```powershell
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 보안 주의사항

- `.env` 파일을 GitHub에 업로드하지 않습니다.
- Client Secret, DB 비밀번호, Session Secret은 외부에 노출하지 않습니다.
- `.gitignore`에 `.env`, `.venv/`, `__pycache__/`를 등록합니다.
- 실제 배포 환경에서는 HTTPS와 보안 쿠키 설정을 적용해야 합니다.

---

## 4. FastAPI 서버 실행

프로젝트 최상위 폴더에서 다음 명령어를 실행합니다.

```powershell
uv run --directory backend uvicorn app.main:app --reload --port 8000
```

정상 실행 시 다음과 같은 메시지가 출력됩니다.

```text
Uvicorn running on http://127.0.0.1:8000
Application startup complete.
```

### 접속 주소

| 주소 | 기능 |
|---|---|
| `http://localhost:8000/` | 서버 실행 상태 확인 |
| `http://localhost:8000/health` | API 상태 확인 |
| `http://localhost:8000/health/db` | DB 연결 상태 확인 |
| `http://localhost:8000/docs` | Swagger API 문서 |
| `http://localhost:8000/auth/discord/login` | Discord 로그인 시작 |
| `http://localhost:8000/auth/me` | 현재 로그인 상태 확인 |

서버 종료는 터미널에서 `Ctrl + C`를 사용합니다.

---

## 5. Discord 로그인 및 회원가입 로직

PlayMate는 Discord OAuth2를 이용해 사용자를 인증합니다.

Discord 인증과 PlayMate 회원가입은 서로 다른 과정입니다.

### 5.1 Discord 인증

```text
사용자가 Discord 로그인 요청
        ↓
GET /auth/discord/login
        ↓
Discord OAuth2 인증 페이지 이동
        ↓
Discord 계정 인증 및 권한 승인
        ↓
GET /auth/discord/callback
        ↓
Authorization Code 수신
        ↓
Access Token 교환
        ↓
Discord 사용자 정보 조회
        ↓
discord_id 획득
```

Discord OAuth2의 `identify` 권한을 사용하여 Discord 사용자 ID, 사용자명 등의 기본 정보를 조회합니다.

OAuth2 요청 시 `state` 값을 생성하고 콜백에서 검증하여 CSRF 공격을 방지합니다.

---

### 5.2 기존 회원과 신규 회원 구분

Discord 인증 후 PostgreSQL `members` 테이블에서 `discord_id`로 기존 회원을 조회합니다.

```text
Discord 인증 성공
        ↓
PostgreSQL members 조회
        ↓
기존 회원 여부 확인
        │
        ├── 기존 회원
        │     └── member_id 세션 저장
        │           └── 로그인 완료
        │
        └── 신규 회원
              └── 추가 회원정보 입력 필요
                    ├── 닉네임
                    ├── 기수
                    └── 수강 트랙
```

신규 회원은 `signup_required: true`, 기존 회원은 `signup_required: false` 응답을 받도록 구현되어 있습니다.

---

### 5.3 추가 회원가입

신규 회원은 다음 정보를 입력합니다.

| 항목 | 입력 방식 |
|---|---|
| Discord ID | OAuth2 인증으로 자동 획득 |
| 닉네임 | 사용자 직접 입력 |
| 기수 | 사용자 직접 입력 |
| 수강 트랙 | 사용자 직접 입력 |

Discord ID는 클라이언트에서 직접 입력받지 않고 인증된 세션에서 가져옵니다.

회원가입 요청 예시:

```json
{
  "nickname": "테스트",
  "cohort": 36,
  "track": "AI"
}
```

현재 프론트엔드 및 스키마에서는 `track`이라는 필드명을 사용하고, 실제 DB에서는 `course` 컬럼에 저장하도록 매핑합니다.

---

## 6. 인증 API

모든 인증 관련 API는 `/auth` 접두사를 사용합니다.

| Method | Endpoint | 기능 |
|---|---|---|
| GET | `/auth/discord/login` | Discord OAuth2 인증 시작 |
| GET | `/auth/discord/callback` | Discord 인증 코드 처리 및 회원 조회 |
| GET | `/auth/me` | 현재 사용자 인증·가입 상태 확인 |
| POST | `/auth/logout` | 로그인 세션 초기화 |
| POST | `/auth/signup` | 신규 회원 추가정보 등록 |

### 6.1 Discord 로그인

```text
GET /auth/discord/login
```

Discord 인증 페이지로 리디렉션합니다.

인증 과정에서 OAuth2 `state`를 생성하고 세션에 저장합니다.

---

### 6.2 Discord Callback

```text
GET /auth/discord/callback
```

Discord 인증 후 전달된 코드를 액세스 토큰으로 교환하고 사용자 정보를 조회합니다.

기존 회원 응답 예시:

```json
{
  "message": "로그인 성공!",
  "signup_required": false,
  "member": {
    "member_id": 1,
    "discord_id": "123456789012345678",
    "nickname": "테스트",
    "course": "AI",
    "cohort": 36,
    "role_code": "USER"
  }
}
```

신규 회원 응답 예시:

```json
{
  "message": "추가 회원가입이 필요합니다.",
  "signup_required": true,
  "discord_user": {
    "discord_id": "123456789012345678",
    "username": "test_user",
    "avatar": null
  }
}
```

---

### 6.3 회원가입

```text
POST /auth/signup
```

Discord 인증 세션이 존재하는 사용자만 회원가입할 수 있습니다.

요청 Body:

```json
{
  "nickname": "테스트",
  "cohort": 36,
  "track": "AI"
}
```

성공 시 HTTP `201 Created`와 회원정보를 반환합니다.

이미 가입된 Discord 계정이거나 DB 고유 제약조건을 위반하면 `409 Conflict`를 반환합니다.

---

### 6.4 현재 사용자 조회

```text
GET /auth/me
```

Discord 인증 세션과 PlayMate 회원가입 완료 여부를 구분합니다.

- 인증 정보가 없으면 `401 Unauthorized`
- Discord 인증만 완료했다면 `signup_required: true`
- 회원가입까지 완료했다면 `signup_required: false`

---

### 6.5 로그아웃

```text
POST /auth/logout
```

현재 로그인 세션을 초기화합니다.

---

## 7. PostgreSQL 연결 및 회원 테이블

### 7.1 DB 연결

`core/database.py`에서는 로그인·회원가입 기능을 위한 psycopg 직접 연결과 SQLAlchemy 기반 ORM 연결을 함께 제공합니다.

psycopg 직접 연결:

```python
get_db_connection()
```

SQLAlchemy 세션:

```python
get_db()
```

환경변수로부터 Host, Port, User, Password, Database, SSL 설정값을 가져옵니다.

연결 확인 예시:

```powershell
uv run --directory backend python -c "from app.core.database import get_db_connection; conn = get_db_connection(); print('PostgreSQL 연결 성공!'); conn.close()"
```

---

### 7.2 members 테이블 구조

현재 PostgreSQL `public.members` 테이블은 다음과 같은 회원 정보를 사용합니다.

| 컬럼 | 자료형 | 용도 |
|---|---|---|
| `member_id` | bigint | 회원 고유 ID (PK) |
| `role_code` | varchar(20) | 회원 권한 구분 |
| `created_at` | timestamp | 가입 시각 |
| `updated_at` | timestamp | 정보 수정 시각 |
| `external_dm_opt_in` | boolean | 외부 DM 동의 여부 |
| `discord_id` | varchar(30) | Discord 고유 사용자 ID |
| `nickname` | varchar(50) | 닉네임 |
| `course` | varchar(100) | 수강 과정 또는 트랙 |
| `cohort` | integer | 기수 |

확인된 DB 설정:

- `member_id`: 자동 생성
- `discord_id`: UNIQUE 인덱스 설정
- `created_at`, `updated_at`: `CURRENT_TIMESTAMP` 기본값
- `role_code`: 회원가입 시 `USER` 지정

공용 DB의 기존 스키마를 활용합니다.

회원의 중복 가입 여부는 `discord_id`를 기준으로 확인합니다.

---

## 8. 모임 API

모임 기능은 FastAPI와 SQLAlchemy를 이용해 PostgreSQL 데이터를 조회하고 저장합니다.

### 작업 흐름

```text
React
  ↓
routers/recruit.py
  ↓
services/recruit.py 또는 ORM 조회
  ↓
core/database.py
  ↓
PostgreSQL
```

### API 목록

| HTTP | URL | 역할 |
|---|---|---|
| GET | `/api/recruits` | 삭제되지 않은 모임 목록 |
| GET | `/api/recruits/{recruit_id}` | 모임 상세 + `detail` |
| POST | `/api/recruits` | 모임 생성 |
| PATCH | `/api/recruits/{recruit_id}` | 공통 정보 수정 |
| DELETE | `/api/recruits/{recruit_id}` | 논리 삭제 |
| POST | `/api/recruits/{recruit_id}/join` | 테스트 사용자 참여 |
| DELETE | `/api/recruits/{recruit_id}/join` | 참여 취소 |
| GET | `/api/recruits/{recruit_id}/members` | JOINED 참여자 목록 |
| GET | `/api/recruits/{recruit_id}/count` | 현재 인원 / 정원 / 잔여석 |

### 현재 제약사항

- 개발용 회원 ID `-1`을 사용 중이며 실제 로그인과 권한 검사는 아직 연동되지 않았습니다.
- 모임 생성에서는 카테고리 상세를 저장하지만 PATCH는 상세 항목 변경을 지원하지 않습니다.
- 동시 참여 시 정원 초과 방지용 잠금은 아직 구현되지 않았습니다.
- 일부 응답 스키마와 오류 규격은 추후 통일이 필요합니다.
- 공통 `members`, `posts` 테이블 변경 시 다른 기능과의 연동을 확인해야 합니다.

---

## 9. 현재 테스트 결과

### 9.1 완료된 테스트

| 테스트 | 결과 |
|---|---|
| Discord OAuth2 로그인 및 권한 승인 | 성공 |
| Discord 사용자 정보 조회 | 성공 |
| 로그인 세션 유지 (`/auth/me`) | 성공 |
| PostgreSQL 연결 | 성공 |
| Discord ID 기반 회원 조회 | 성공 |
| 회원가입 스키마 기본 검증 | 성공 |
| FastAPI 인증 API 등록 | 성공 |
| 비인증 사용자 회원가입 차단 (401) | 성공 |
| 신규 회원 여부 판단 | Mock 테스트 성공 |
| 기존 회원 자동 로그인 분기 | Mock 테스트 성공 |

---

### 9.2 회원 조회 테스트

```powershell
uv run --directory backend python -c "from app.services.member_service import get_member; print(get_member('000000000000000000'))"
```

해당 Discord ID가 DB에 없으면 `None`을 반환합니다.

이 테스트는 조회 전용이며 DB에 데이터를 저장하지 않습니다.

---

### 9.3 신규 회원 / 기존 회원 Mock 테스트

테스트 파일:

```text
backend/tests/test_auth_flow.py
```

실행:

```powershell
python -m pytest backend/tests/test_auth_flow.py -q
```

현재 콜백의 302 리디렉션과 이후 `/auth/me` 세션으로 신규·기존 회원을 구분합니다.
테스트 수집 시 HTTP 요청을 실행하지 않습니다.

해당 테스트는 Discord와 PostgreSQL 응답을 Mock으로 대체하므로 실제 외부 서비스에 회원을 생성하지 않습니다.

---

### 9.4 추가 검증 필요 항목

- 신규 회원 실제 PostgreSQL INSERT
- 회원가입 완료 후 실제 세션 유지 및 재로그인
- 실제 Discord 기존 회원 자동 로그인
- DB 저장 실패 및 제약조건 충돌 상황
- 로그인과 모임 기능의 실제 회원 ID 연동
- 프론트엔드 최종 연동
- 배포 환경 HTTPS 및 쿠키 보안 설정

---

## 10. API 테스트 시 주의사항

공용 Aiven PostgreSQL을 사용하고 있으므로 실제 회원가입 및 생성 API 테스트 시 데이터가 저장될 수 있습니다.

테스트 데이터를 생성하기 전에 팀원들과 협의하고, 데이터를 삭제할 경우 다른 테이블의 외래키 참조 여부를 확인해야 합니다.

현재 로그인 세션은 Starlette의 서명된 쿠키를 사용합니다.

- 쿠키는 서명되지만 내용이 암호화되는 것은 아닙니다.
- Discord Access Token과 Client Secret을 세션 쿠키에 저장하지 않습니다.
- `/auth/me`는 세션을 기준으로 로그인 상태를 반환합니다.
- 배포 전에는 회원 상태 검증, 세션 만료·무효화, 권한 검사 등을 보완해야 합니다.

---

## 11. 이후 개발 계획

1. React 로그인 화면 구현 및 Discord 로그인 연결
2. Discord 인증 완료 후 React 페이지 리디렉션
3. 신규 회원의 닉네임·기수·트랙 입력 화면 연결
4. React 회원가입 폼과 `POST /auth/signup` 연결
5. PostgreSQL 실제 회원가입 및 재로그인 테스트
6. 모임 기능의 개발용 회원 ID `-1` 제거
7. 실제 로그인 회원과 게시판·모임 기능 연동
8. 공통 인증 및 권한 검사 적용
9. 응답 스키마 및 오류 응답 규격 정리
10. 배포 환경 보안 설정 및 최종 통합 테스트

---

현재 백엔드는 Discord 인증, 회원 조회, 신규·기존 회원 분기, 회원가입 API와 게시판·모임 API의 기본 구조가 구현된 상태입니다.

로그인 기능과 게시판·모임 기능의 실제 회원 인증 연동 및 최종 프론트엔드 통합 테스트는 추가 작업이 필요합니다.

## 12. Issue #6 게시판 백엔드 리팩터링 (2026-10-14)

### 계층과 트랜잭션

게시판은 Router → Service → Repository → PostgreSQL 순서입니다.
Router는 요청 검증·인증·업로드를 연결하고, Service가 한 업무에 한 DB 연결을 열어
권한과 처리 순서를 관리합니다. Repository는 전달받은 커서만 사용하며 커밋하지 않습니다.
게시글·댓글 저장 후 응답 데이터도 커밋 전에 조회하여 응답 조회 실패 시 전체 롤백합니다.
게시글 생성의 동기 DB 처리는 thread pool에서 실행해 비동기 요청 처리 흐름을 막지 않습니다.

### 인증과 프론트 연동

- 기존 Discord OAuth 세션의 `member_id`와 `user.discord_id`를 DB에서 함께 검증합니다.
- 유효한 로그인 세션이 있으면 개발용 헤더로 회원 ID를 바꿀 수 없습니다.
- `X-Dev-Member-ID`는 세션이 없고 `APP_ENV=development` 또는 `test`일 때만 허용합니다.
  이 헤더는 개발용 신뢰 기능이므로 외부에 공개된 서버에서 개발 환경을 사용하면 안 됩니다.
- 운영은 `APP_ENV=production`(기본값)과 기존 `SESSION_SECRET_KEY`를 사용합니다.
  새 환경변수는 없습니다. 기존 OAuth Router와 회원 Service는 변경하지 않았습니다.
- 같은 출처의 `/api` 프록시에서는 기존 fetch가 세션 쿠키를 전달합니다.
  API를 다른 출처로 직접 호출할 경우 프론트 담당자가 `credentials: 'include'`와
  CORS·쿠키 설정을 확인해야 합니다.
- URL, Method, 요청·응답 스키마, 상태 코드, `/uploads/posts/...` 경로를 유지했습니다.
  게시글 목록은 기존 배열 응답이며 기존에 없는 페이지네이션을 추가하지 않았습니다.
- 연결 실패의 503 상태는 유지하되 상세 DB 진단은 서버 로그에만 남깁니다.

### 초기 로딩 조회 개선

`list_posts`는 게시판 확인 1회 + 게시글·댓글 집계 1회 + 이미지 일괄 조회 1회입니다.
빈 게시글 목록은 이미지 SQL을 생략합니다. 이미지의 `display_order, image_id` 순서와
게시글별 매핑·빈 이미지 목록을 유지합니다. 댓글 조회는 게시글 존재 확인과 댓글 조회만 합니다.

동일 대역 데이터로 변경 전 소스(`ba330782a4f51d65e3c0802450c6b0027b280bac`)와 비교한 결과:

| 입력 | 이전 SQL 호출 | 이후 SQL 호출 | 이전/이후 연결 생성 |
|---|---:|---:|---:|
| 게시글 0개 | 2 | 2 | 2 / 1 |
| 게시글 1개 | 3 | 3 | 2 / 1 |
| 게시글 25개 | 27 | 3 | 2 / 1 |
| 게시글 100개 | 102 | 3 | 2 / 1 |
| 댓글 목록 | 3 | 2 | 2 / 1 |

위 값은 Service·Repository를 실행하여 **커서 대역의 execute 호출을 계측한 값**입니다.
실제 PostgreSQL 쿼리 실행 횟수·응답 시간의 실측이 아닙니다. 인증 조회 1회는 표에서 제외했습니다.
대역 응답과 전체 OpenAPI는 이전·이후 동일했습니다. 실DB 실행 계획·첫 요청/반복 요청 시간·
응답 크기는 미측정입니다. 공유 DB에 쓰기·삭제·마이그레이션을 수행하지 않았습니다.

프론트 코드상 게시판 초기 요청은 게시판 목록 → 첫 게시판 게시글 목록 2개입니다.
앱의 로그인 확인 `/auth/me`까지 포함하면 정상 로그인 진입 경로는 3개입니다.
개발 `StrictMode`의 effect 재실행으로 중복 요청 가능성이 있습니다. 브라우저 실측은 하지 않았습니다.
프론트 파일은 변경하지 않았습니다. `frontend/src/services/boardApi.js`의 `mediaUrl()`은
`new URL('/api')`처럼 상대 주소만으로 URL을 만들고 있으므로 프론트 담당자가
`new URL(path, window.location.origin)`처럼 기준 주소를 지정해야 합니다.

### 재현 가능한 안전한 테스트

저장소 루트에서 backend 내부에만 환경을 만들 수 있습니다.

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
$env:RUN_POSTGRES_INTEGRATION = '0'
backend/.venv/Scripts/python.exe -m pytest backend/tests -q -p no:cacheprovider --basetemp=backend/.pytest-tmp
backend/.venv/Scripts/python.exe -m compileall -q backend/app backend/tests
```

검증 환경은 Windows / Python 3.14입니다. 결과는 **70 passed, 1 skipped**입니다.
기존 인증 테스트는 실제 302 콜백에 맞추어 수정했습니다. HTTP 테스트는 두 종류입니다:
기존 `client` fixture는 인증 dependency를 override하고 실제 Service·Repository를 실행합니다.
실제 인증 테스트는 override 없이 서명 세션·헤더·401/422·사용자 불일치를 검증합니다.
모든 DB 결과는 대역이며 Discord 토큰 교환·회원 조회도 대역입니다.
파일 테스트는 backend 내부 임시 경로만 사용합니다.

통합 테스트는 `RUN_POSTGRES_INTEGRATION=1`일 때 쓰기를 수행하므로 **독립된 폐기 가능한
테스트 DB를 확인한 경우에만** 실행합니다. 이번 환경에는 격리 DB가 없고 Docker 엔진도
실행 중이지 않아 통합 테스트를 제외했습니다. 공유 Aiven DB에서는 실행하지 않습니다.
Python 3.14에서 FastAPI/Starlette의 deprecated API 경고 56개가 발생했으며 실패는 아닙니다.

모임 Router/Service의 개발 사용자 `-1`, 인증 연결, 참여 인원 집계와 ORM 조회 최적화는
모임 담당자와 별도로 조율할 항목입니다. OAuth Router·회원 Service·DB 설정·ORM 구조는
이번 게시판 리팩터링에서 변경하지 않았습니다.

모임 화면은 목록 응답의 모임마다 별도 참가자 수 API를 호출합니다. 이 HTTP N+1은
`frontend/src/App.jsx`의 `loadMeetups()` 및 모임 담당자에게 전달할 개선 사항이며,
게시판 진입에서는 모임 컴포넌트가 마운트되지 않아 게시판 초기 병목과 구분했습니다.

## 13. PR 전 최종 감사 (2026-10-15)

### 수정 범위와 작성 이력

감사 시작 HEAD와 원격 HEAD는 `b071873c2e71cc3e019d79497c3a6014c84fb094`로
일치했으며 미커밋 변경이 없었습니다. 최신 develop은
`ba330782a4f51d65e3c0802450c6b0027b280bac`입니다.
`AGENTS.md`, CODEOWNERS, 저장소 내 pytest CI workflow는 확인되지 않았습니다.

`git log --follow`, `git blame`, `feature/board`, `feature/board-2`의 실제 커밋을
확인했습니다. `55deb2a`에서 skwldls050505가 게시판 Router/Service, core/auth,
DB 커서, 업로드, requirements, conftest를 추가했습니다. Router/Service의 이후
카테고리·닉네임 관련 변경은 minji 이력입니다. README 최초 이력은 doldolkooong,
인증 문서·테스트의 주요 이력은 Seona-jang이며 sohee0345의 통합 변경도 있습니다.
작성 이력만으로 현재 소유권을 단정하지 않습니다.

- A(게시판 전용): Router, Service, Repository, 업로드, 게시판 회귀 테스트는 유지합니다.
- B(실행에 필요한 공통 변경): 세션 어댑터, DB 트랜잭션 안전 처리, 기존 런타임의
  누락 의존성, 테스트 격리 설정, 실행 문서는 유지합니다.
- C(다른 담당자 전달): OAuth Router/Service, 모임, 공통 config/database/main,
  프론트 쿠키·이미지 URL 수정은 직접 변경하지 않았습니다.
- D(불필요한 변경 축소): 로그인 테스트의 추가 OAuth state 검증과 전면 스타일
  변경을 제외하고 원래 테스트 흐름·가짜 회원 데이터를 최대한 유지했습니다.
  게시판 테스트의 미사용 import도 제거했습니다.

테스트 4개 파일의 최종 결정은 KEEP입니다. conftest는 공유 DB와 비밀 설정 없이
테스트할 격리를 제공하고, 게시판·업로드 테스트는 N+1·권한·파일 정리 회귀를
검증합니다. 로그인 테스트를 develop 버전으로 복원한 임시 실행은
`KeyError: signup_required`로 수집 단계에서 실패했습니다. 필요한 변경은 302
리디렉션 검사와 import 시 HTTP 실행을 피하는 pytest 함수화로 최소화했습니다.
로그인 담당자에게 이 최소 계약 수정의 검토를 요청할 수 있습니다.

### 감사에서 재현하여 수정한 문제

COMMIT 응답이 유실되면 서버가 이미 데이터를 저장했을 수 있습니다. 이전 코드는
이 오류와 커밋 성공 후 연결 종료 오류를 모두 업로드 실패로 취급하여 파일을
삭제했습니다. 대역 기반 HTTP 테스트 3개가 수정 전에 실패했고 파일이 삭제됨을
확인했습니다.

- 통신 오류로 COMMIT 결과가 불명확하면 `CommitOutcomeUnknownError`와 503으로
  구분하고 업로드 파일을 보존합니다. SQLSTATE가 있는 명시적 거부는 기존 정리
  흐름을 유지합니다.
- rollback/close의 드라이버 오류는 종류만 로그에 기록하고 원래 결과를 덮지 않습니다.
- 커밋 성공 후 close 실패는 성공 응답·파일을 유지합니다.
- 결과가 불명확하여 보존된 파일은 DB 참조 확인 후 담당자가 정리해야 합니다.
  자동 삭제·재시도·새 인프라는 추가하지 않았습니다.

### 환경변수와 실제 HTTP 검증

루트 `.env`를 읽기만 했으며 값·토큰·Secret은 출력하거나 Git에 포함하지 않았습니다.
APP_ENV, DB_HOST/PORT/USER/PASSWORD/NAME, DISCORD_CLIENT_ID/SECRET/REDIRECT_URI,
SESSION_SECRET_KEY는 설정되어 있고 실제 프로세스에 반영됩니다.
DB_SSLMODE와 FRONTEND_ORIGINS는 미설정으로 기존 코드 기본값을 사용합니다.
필수 설정 누락, 변수명 불일치, 이전 OAuth 설정 누락 시작 오류는 재현되지 않았습니다.
config와 db_connect는 동일 루트 파일을 override 없이 로딩합니다.

임시 로컬 Uvicorn 서버를 실행하고 PostgreSQL 연결에
`PGOPTIONS=-c default_transaction_read_only=on`을 적용했습니다.
`SHOW transaction_read_only`가 on임을 확인했습니다. 모든 실DB HTTP 요청은 GET이며
DB 생성·수정·삭제·마이그레이션을 실행하지 않았습니다.

| 실제 HTTP 확인 | 결과 |
|---|---|
| `/`, `/health`, `/health/db` | 200; 실제 DB 연결 성공 |
| 게시판 목록·상세, 게시글 목록·상세, 댓글 목록 | 200 |
| 인증 누락·존재하지 않는 회원 | 401 |
| 없는 게시판·게시글·실제 삭제된 게시글 | 404 |
| 잘못된 경로 파라미터·sort·검색 길이 | 422 |
| 빈 검색 결과 | 200, 빈 배열 |
| 운영 모드의 개발 헤더 | 401 |
| 로컬 생성 서명 세션 + 실제 회원/Discord ID DB 검증 | 200 |
| DB 연결 실패를 별도 프로세스에서 유도 | 503, 상세 접속 진단 비노출 |

`member_id=-1`의 실제 존재를 먼저 확인한 뒤 개발 헤더를 사용했습니다.
서명 세션은 로컬에서 구성했으므로 실제 Discord OAuth 성공으로 해석하지 않습니다.
기존 develop SQL과 현재 SQL의 실제 HTTP JSON 9개가 동일했고 전체 OpenAPI도 동일합니다.
쓰기·다른 회원 수정/삭제·업로드 실패 검증은 대역/TestClient로만 수행했습니다.

**기존 이미지 파일 누락:** DB의 이미지 메타데이터 1개와 기존 URL은 정상 반환됩니다.
저장 경로는 상대 경로이며 현재 정적 루트 내부로 해석됩니다. 그러나 해당 로컬
원본 파일이 없어서 실제 이미지 GET은 404입니다. 파일이 존재하는 임시 디렉터리의
정적 조회 테스트는 200입니다. DB 행을 지우거나 대체 파일을 만들지 않았습니다.
원본 파일 담당자가 `uploads/posts/`의 누락 자산을 복원하거나 올바른 파일 서버로
연결해야 합니다. 이는 backend 외부이며 이번 작업에서 수정하지 않았습니다.

### 실제 성능 계측

공유 DB에 소량의 순차 GET만 사용했습니다. 아래 SQL 수는 인증 SELECT 1회도 포함하며,
드라이버 cursor.execute 호출과 연결 생성 시간을 임시 로컬 진단으로 계측했습니다.
실DB 첫 목록 응답에는 게시판 2번의 글 3개, 게시판 4번의 글 1개가 있습니다.

| API | 이전 SQL/연결 | 현재 SQL/연결 | 이전 1회(ms) | 현재 첫 요청(ms) | 현재 반복 평균(ms) | 표본 p95(ms) | 응답 크기 |
|---|---|---|---:|---:|---:|---:|---:|
| 게시판 2 게시글 목록 | 6 / 3 | 4 / 2 | 7613.91 | 4865.31 | 5038.83 | 5165.46 | 907 B |
| 해당 게시글 댓글 | 4 / 3 | 3 / 2 | 6993.29 | 4761.03 | 4778.84 | 4858.88 | 2 B |
| 게시판 4 게시글 목록 | 4 / 3 | 4 / 2 | 7549.70 | 5062.89 | 4925.87 | 5024.01 | 299 B |
| 해당 게시글 댓글 | 4 / 3 | 3 / 2 | 6804.02 | 4886.87 | 4817.42 | 4950.62 | 2 B |

반복 평균은 각 API 5회, p95는 해당 5회 표본의 최근접 순위 값(최댓값)입니다.
이전은 단일 요청이므로 위 시간만으로 개선율이나 운영 SLA를 보장하지 않습니다.
현재 게시글 목록의 연결 생성 합계 평균은 약 3298~3373ms, SQL 호출 시간 합계는
약 1622~1659ms입니다. N+1 제거와 연결 수 감소는 확인됐지만 연결·네트워크 지연이
여전히 큽니다. 이번 최종 감사에서는 연결 풀을 새로 도입하지 않았습니다.
기존 대역 계측의 게시글 25개 27→3회, 100개 102→3회(인증 제외)도 회귀 테스트로 유지됩니다.

### 최종 테스트와 인계

```powershell
$env:RUN_POSTGRES_INTEGRATION = '0'
python -m pytest backend/tests -q -p no:cacheprovider --basetemp=backend/.audit-pytest
python -m compileall -q backend/app backend/tests
```

최종 결과: **73 passed, 1 skipped**. Python 3.14의 기존 의존성 경고 56개가 있습니다.
격리 PostgreSQL 쓰기 통합 테스트는 DB가 없고 Docker 엔진도 실행 중이지 않아 제외했습니다.
실DB 읽기 검증과 이 미실행 쓰기 검증을 구분합니다. 임시 도구·설치 파일·로그·자산은
커밋하지 않으며 실행한 임시 서버는 종료했습니다.

원격 feature/7-board-frontend, feature/8-meetup-backend, feature/11-login-backend는
확인 당시 develop의 과거 커밋으로, 각각 develop 대비 고유 변경이 없었습니다.
열린 PR도 없었습니다. 아직 Push되지 않은 담당자 작업은 확인할 수 없습니다.
프론트의 상대 이미지 URL 생성, 쿠키 전달·StrictMode 중복 요청은 기존 전달 사항이며
프론트 파일은 수정하지 않았습니다. 로그인/모임의 금지 파일도 수정하지 않았습니다.

준비 상태는 **READY WITH WARNINGS**입니다. 코드 변경은 PR 검토 가능하지만 누락 이미지
원본 복원, 실DB 쓰기·실제 OAuth·브라우저 통합, 높은 DB 연결 지연 확인이 남아 있습니다.
PR 생성·Merge·Issue 종료는 수행하지 않습니다.
