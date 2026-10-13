# PlayMate Backend

PlayMate 커뮤니티 서비스의 **FastAPI 기반 백엔드 서버**입니다.

회원 인증, 회원가입, 게시판, 댓글, 모임 등 서비스의 API와 비즈니스 로직을 담당합니다.

현재 `feature/login` 브랜치에서는 **Discord OAuth2 간편 로그인 및 회원가입 기능**을 개발하고 있습니다.

## 1. 기술 스택

| 구분 | 기술 |
|---|---|
| Language | Python 3.13 이상 |
| Backend | FastAPI |
| Package Manager | uv |
| Database | Aiven PostgreSQL |
| Database Driver | psycopg |
| HTTP Client | httpx |
| Data Validation | Pydantic |
| Authentication | Discord OAuth2 |
| Session | Starlette SessionMiddleware |
| API Documentation | Swagger UI |

## 2. 백엔드 폴더 구조

```text
backend/
├── app/
│   ├── __init__.py
│   ├── main.py
│   │
│   ├── core/
│   │   ├── config.py
│   │   └── database.py
│   │
│   ├── routers/
│   │   ├── __init__.py
│   │   └── auth.py
│   │
│   ├── services/
│   │   ├── auth_service.py
│   │   └── member_service.py
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
| `main.py` | FastAPI 애플리케이션 생성, 세션 미들웨어 설정 및 라우터 등록 |
| `core/config.py` | `.env` 환경변수 로드 |
| `core/database.py` | PostgreSQL 연결 객체 생성 |
| `routers/auth.py` | Discord 로그인, 콜백, 회원가입, 회원 조회, 로그아웃 API |
| `services/auth_service.py` | Discord 토큰 교환 및 사용자 정보 조회 |
| `services/member_service.py` | PostgreSQL 회원 조회 및 신규 회원 등록 |
| `schemas/member.py` | 회원가입 요청 데이터 검증 |
| `models/member.py` | 회원 DB 모델 정의를 위한 파일 (현재 별도 ORM 모델 미구현) |
| `tests/test_auth_flow.py` | Discord 인증 이후 신규·기존 회원 분기 테스트 |

### 폴더별 역할

- `routers/`: API 엔드포인트 정의
- `services/`: 비즈니스 로직 및 외부 서비스 통신
- `schemas/`: Pydantic 요청·응답 데이터 구조 및 검증
- `models/`: 데이터베이스 ORM 모델 정의 영역
- `core/`: DB 연결, 인증, 환경변수 등 공통 설정
- `tests/`: 백엔드 기능 테스트

## 3. 개발 환경 설정

Windows / VS Code / PowerShell 기준입니다.

### 3.1 프로젝트 Clone

```powershell
git clone git@github.com:Six-Over-Sleep/playmate.git
cd playmate
git switch feature/login
```

이미 Clone한 경우에는 다시 Clone할 필요가 없습니다.

### 3.2 uv 환경 설정

프로젝트 최상위 `playmate/` 폴더에서 실행합니다.

```powershell
uv sync
```

`pyproject.toml`에 정의된 의존성을 기반으로 `.venv` 환경을 구성합니다.

현재 로그인 기능에서 사용하는 주요 라이브러리는 다음과 같습니다.

```text
fastapi
uvicorn
httpx
python-dotenv
itsdangerous
pydantic
psycopg[binary]
```

필요한 라이브러리를 새로 추가할 때는 프로젝트 최상위에서 다음 명령어를 사용합니다.

```powershell
uv add 패키지명
```

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
```

Discord 관련 설정값은 Discord Developer Portal에서 확인할 수 있습니다.

- Discord Developer Portal: https://discord.com/developers/applications
- OAuth2 Scope: `identify`
- Redirect URI: `http://localhost:8000/auth/discord/callback`

`SESSION_SECRET_KEY`는 다음 명령어로 생성할 수 있습니다.

```powershell
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**보안 주의사항**

- `.env` 파일을 GitHub에 업로드하지 않습니다.
- Client Secret, DB 비밀번호, Session Secret은 외부에 노출하지 않습니다.
- `.gitignore`에 `.env`, `.venv/`, `__pycache__/`를 등록합니다.
- 실제 배포 환경에서는 HTTPS와 보안 쿠키 설정을 적용해야 합니다.

## 4. FastAPI 서버 실행

프로젝트 최상위 폴더에서 다음 명령어를 실행합니다.

```powershell
uv run --directory backend uvicorn app.main:app --reload --port 8000
```

정상 실행 시 다음 메시지가 출력됩니다.

```text
Uvicorn running on http://127.0.0.1:8000
Application startup complete.
```

### 접속 주소

| 주소 | 기능 |
|---|---|
| `http://localhost:8000/` | 서버 실행 상태 확인 |
| `http://localhost:8000/docs` | Swagger API 문서 |
| `http://localhost:8000/auth/discord/login` | Discord 로그인 시작 |
| `http://localhost:8000/auth/me` | 현재 로그인 상태 확인 |

서버 종료는 터미널에서 `Ctrl + C`를 사용합니다.

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
  "nickname": "선아",
  "cohort": 36,
  "track": "AI"
}
```

현재 프론트엔드 및 스키마에서는 `track`이라는 필드명을 사용하고, 실제 DB에서는 `course` 컬럼에 저장하도록 매핑합니다.

## 6. 인증 API 명세

모든 인증 관련 API는 `/auth` 접두사를 사용합니다.

| Method | Endpoint | 기능 |
|---|---|---|
| GET | `/auth/discord/login` | Discord OAuth2 인증 시작 |
| GET | `/auth/discord/callback` | Discord 인증 코드 처리 및 회원 조회 |
| GET | `/auth/me` | 현재 사용자 인증·가입 상태 확인 |
| POST | `/auth/logout` | 로그인 세션 초기화 |
| POST | `/auth/signup` | 신규 회원 추가정보 등록 |

### 6.1 Discord 로그인

`GET /auth/discord/login`

Discord 인증 페이지로 리디렉션합니다.

인증 과정에서 OAuth2 `state`를 생성하고 세션에 저장합니다.

### 6.2 Discord Callback

`GET /auth/discord/callback`

Discord 인증 후 전달된 코드를 액세스 토큰으로 교환하고, 사용자 정보를 조회합니다.

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

### 6.3 회원가입

`POST /auth/signup`

Discord 인증 세션이 존재하는 사용자만 회원가입할 수 있습니다.

요청 Body:

```json
{
  "nickname": "테스트",
  "cohort": 36,
  "track": "AI"
}
```

성공 시 HTTP `201 Created`와 회원정보를 반환하도록 구현했습니다.

이미 가입된 Discord 계정이거나 DB 고유 제약조건을 위반하면 `409 Conflict`를 반환합니다.

**실제 공용 DB에 대한 회원 INSERT 테스트는 아직 진행하지 않았습니다.**

### 6.4 현재 사용자 조회

`GET /auth/me`

Discord 인증 세션과 PlayMate 회원가입 완료 여부를 구분합니다.

- 인증 정보가 없으면 `401 Unauthorized`
- Discord 인증만 완료했다면 `signup_required: true`
- 회원가입까지 완료했다면 `signup_required: false`

### 6.5 로그아웃

`POST /auth/logout`

현재 세션을 초기화합니다.

## 7. PostgreSQL 연결 및 회원 테이블

### 7.1 DB 연결

`core/database.py`에서 `psycopg`를 사용해 Aiven PostgreSQL에 연결합니다.

환경변수로부터 Host, Port, User, Password, Database, SSL 설정값을 가져옵니다.

연결 확인 명령어:

```powershell
uv run --directory backend python -c "from app.core.database import get_db_connection; conn = get_db_connection(); print('PostgreSQL 연결 성공!'); conn.close()"
```

### 7.2 members 테이블 구조

DBeaver에서 확인한 현재 공용 PostgreSQL `public.members` 테이블의 컬럼은 다음과 같습니다.

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

- `member_id`: `GENERATED BY DEFAULT AS IDENTITY` 방식으로 자동 생성
- `discord_id`: UNIQUE 인덱스 설정
- `created_at`, `updated_at`: `CURRENT_TIMESTAMP` 기본값
- `role_code`: 현재 회원가입 코드에서 `USER` 지정

공용 DB의 스키마를 변경하지 않고 기존 테이블을 활용합니다.

회원의 중복 가입 여부는 `discord_id`로 확인합니다.

## 8. 현재 테스트 결과

### 8.1 완료된 테스트

| 테스트 | 결과 |
|---|---|
| Discord OAuth2 로그인 및 권한 승인 | 성공 |
| Discord 사용자 정보 조회 | 성공 |
| 로그인 세션 유지 (`/auth/me`) | 성공 |
| PostgreSQL 연결 | 성공 |
| Discord ID 기반 회원 조회 | 성공 |
| 회원가입 스키마 기본 검증 | 성공 |
| FastAPI 인증 API 5개 등록 | 성공 |
| 비인증 사용자 회원가입 차단 (401) | 성공 |
| 신규 회원 여부 판단 | Mock 테스트 성공 |
| 기존 회원 자동 로그인 분기 | Mock 테스트 성공 |

### 8.2 회원 조회 테스트

```powershell
uv run --directory backend python -c "from app.services.member_service import get_member; print(get_member('000000000000000000'))"
```

해당 Discord ID가 DB에 없으면 `None`을 반환합니다.

이 테스트는 조회 전용이며 DB에 데이터를 저장하지 않습니다.

### 8.3 신규 회원 / 기존 회원 Mock 테스트

테스트 파일:

```text
backend/tests/test_auth_flow.py
```

실행 명령어:

```powershell
uv run --directory backend python -m tests.test_auth_flow
```

예상 출력:

```text
신규 회원 구분 성공!
기존 회원 자동 로그인 성공!
모든 인증 분기 테스트 통과!
```

해당 테스트는 Discord와 PostgreSQL의 응답을 Mock으로 대체하므로 실제 외부 서비스에 회원을 생성하지 않습니다.

### 8.4 미검증 사항

- 신규 회원 실제 PostgreSQL INSERT
- 회원가입 완료 후 실제 세션 유지 및 재로그인
- 실제 Discord 기존 회원 자동 로그인
- DB 저장 실패 및 제약조건 충돌 상황
- 프론트엔드 연동
- 배포 환경에서 HTTPS 및 쿠키 보안 설정

## 9. API 테스트 시 주의사항

공용 Aiven PostgreSQL을 사용하고 있으므로 실제 회원가입 테스트 시 데이터가 저장됩니다.

테스트 데이터 생성 전 팀원들과 협의하고, 삭제할 경우 다른 테이블의 외래키 참조 여부를 확인해야 합니다.

또한 현재 세션은 Starlette의 서명된 쿠키를 사용합니다.

- 쿠키는 서명되지만 내용이 암호화되는 것은 아닙니다.
- Discord Access Token과 Client Secret을 세션 쿠키에 저장하지 않습니다.
- 현재 `/auth/me`는 세션을 기준으로 로그인 상태를 반환합니다.
- 배포 전에는 회원 상태 검증, 세션 만료·무효화, 권한 검사 등을 보완해야 합니다.

## 10. 이후 개발 계획

1. React 로그인 화면 구현 (`Discord로 계속하기`)
2. Discord 인증 완료 후 React 페이지로 리디렉션
3. 신규 회원의 닉네임·기수·트랙 입력 화면 구현
4. React 회원가입 폼과 `POST /auth/signup` 연결
5. PostgreSQL 실제 회원가입 및 재로그인 테스트
6. 게시판·모임 기능과 공통 회원 인증 연동
7. 배포 환경 보안 설정 및 최종 통합 테스트

현재 백엔드는 Discord 인증, 회원 조회, 신규·기존 회원 분기, 회원가입 API의 기본 구조까지 구현된 상태입니다.

**실제 DB 저장 및 프론트엔드 연동 검증은 추후 진행 예정입니다.**