# PlayMate 게시판 설치 · 실행 · Swagger API 실습 통합 가이드

> **Windows · VS Code · PowerShell 기준**  
> 저장소: https://github.com/Six-Over-Sleep/playmate/tree/feature/board  
> 브랜치: `feature/board` · 프론트엔드: React + Vite · 백엔드: FastAPI · DB: Aiven PostgreSQL

이 문서 하나로 **처음 Clone하는 팀원**, **기존 코드를 Pull하는 팀원**, **화면을 실행하는 팀원**, **Swagger에서 게시판 API를 검증하는 팀원** 모두 따라 할 수 있습니다.

**중요:** `localhost`는 자기 컴퓨터를 가리킵니다. 한 명이 서버를 실행했다고 다른 팀원의 PC에서 같은 주소로 접속되는 것은 아닙니다. 공용 Aiven DB를 사용하면 한 명이 작성·수정·삭제한 테스트 데이터가 다른 팀원에게도 영향을 줍니다.

## 1. 전체 실행 순서

| 단계 | 수행할 일 | 확인 방법 |
|---|---|---|
| 1 | Git, Python, Node.js, VS Code 설치 | 버전 출력 |
| 2 | 처음이면 Clone, 이미 받았다면 Pull | `feature/board` 브랜치 확인 |
| 3 | Python 가상환경과 패키지 설치 | 설치 오류 없음 |
| 4 | `.env` 설정 및 Aiven 연결 | DB 점검 스크립트 실행 |
| 5 | FastAPI 백엔드 실행 | `/health`, `/health/db` 응답 |
| 6 | React 프론트엔드 실행 | `http://localhost:5173` 접속 |
| 7 | Swagger API 실습 | 13개 엔드포인트 기능 확인 |
| 8 | UI·데이터 확인 및 Git 작업 | 체크리스트와 `git status` 확인 |

## 2. 프로젝트 폴더 구조와 역할

```text
playmate/
├── README.md                    # 프로젝트 전체 소개
├── .env.example                 # 개인별 .env 생성 양식
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 앱, 라우터 등록, 상태 확인
│   │   ├── routers/board.py     # 게시판·게시글·댓글 API 주소
│   │   ├── schemas/board.py     # 요청 및 응답 필드 검증
│   │   ├── services/board_service.py  # 게시판 DB 처리 로직
│   │   └── core/                # DB 연결, 개발 인증, 업로드
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── tests/                  # 백엔드 테스트
├── frontend/
│   ├── README.md                # 프론트엔드 폴더 설명
│   ├── BOARD_SETUP_GUIDE.md     # 현재 문서
│   ├── package.json             # npm 명령과 의존성
│   └── src/                     # React 화면, 서비스, 스타일
├── database/
│   ├── sql/                     # 스키마·마이그레이션 SQL
│   └── scripts/                 # DB 연결·스키마 점검
├── docs/                        # 프로젝트 문서 및 기존 검증 자료
├── ai/                          # AI 관련 기능
└── crawler/                     # 크롤링 관련 기능
```

| 작업 | 주로 확인할 위치 |
|---|---|
| 게시판 모달, 버튼, 레이아웃, 색상 | `frontend/src/components/board/`, `frontend/src/styles/` |
| 게시판 페이지와 정렬 UI | `frontend/src/pages/board/`, `frontend/src/services/boardApi.js` |
| API 주소·요청 방식 | `backend/app/routers/board.py` |
| 데이터 입력·권한·삭제 처리 | `backend/app/services/board_service.py` |
| API 입력 형식 | `backend/app/schemas/board.py` |
| DB 접속·개발 회원 인증 | `backend/app/core/`, 루트 `.env` |
| DB 테이블·컬럼 | `database/sql/`, `database/scripts/` |

> `.venv/`, `frontend/node_modules/`, 개인 `.env`는 일반적으로 로컬에만 두며 GitHub에 업로드하지 않습니다. **이 문서는 설치·실행 및 현재 API 실습을 다루며, 모든 기능의 테스트 통과를 보장한다는 뜻은 아닙니다.**

## 3. 개발 환경 설치

| 프로그램 | 용도 | 공식 다운로드 |
|---|---|---|
| Git | Clone, Pull, Push | https://git-scm.com/downloads/win |
| VS Code | 코드 편집·터미널 | https://code.visualstudio.com/ |
| Python (권장 3.12) | FastAPI 실행 | https://www.python.org/downloads/ |
| Node.js (LTS 권장) | React + Vite 실행 | https://nodejs.org/ |

VS Code → **Terminal → New Terminal**에서 확인합니다.

```powershell
git --version
python --version
node --version
npm.cmd --version
```

`node` 또는 `npm.cmd`가 인식되지 않지만 Node.js가 이미 설치되어 있다면:

```powershell
Test-Path "C:\Program Files\nodejs\node.exe"
& "C:\Program Files\nodejs\node.exe" --version
$env:Path += ";C:\Program Files\nodejs"
node --version
npm.cmd --version
```

이 PATH 변경은 **현재 터미널에만** 적용됩니다. 설치 자체가 없다면 Node.js를 설치하고 VS Code를 완전히 재시작하세요.

## 4. GitHub 코드 받기: Clone과 Pull 구분

### A. 처음 받는 팀원 — Clone

프로젝트가 아직 로컬에 없는 경우:

```powershell
cd "$HOME\Desktop"
git clone -b feature/board https://github.com/Six-Over-Sleep/playmate.git
cd playmate
git branch --show-current
git status
```

`feature/board` 브랜치와 깨끗한 작업 트리가 확인되면 다음 단계로 이동합니다.

### B. 이미 Clone한 팀원 — Pull

프로젝트를 받은 적이 있다면 다시 Clone할 필요가 없습니다. 아래 경로는 예시이므로 본인 프로젝트 위치로 바꾸세요.

```powershell
cd C:\dev\project\playmate
git status
git switch feature/board
git pull origin feature/board
git status
```

`git status`에 변경 파일이 있다면 **먼저 백업하거나 커밋/스태시**한 뒤 Pull하세요. 로컬에 브랜치가 없다면 다음을 실행합니다.

```powershell
git fetch origin
git switch --track origin/feature/board
```

`Already up to date.`는 이미 최신이라는 의미입니다. **기존 `.env`는 Pull을 이유로 삭제하거나 덮어쓰지 마세요.** 다른 사람의 Push와 이력이 갈라졌다면 강제 Push·`reset --hard`로 해결하려 하지 말고 변경 내역을 확인합니다.

## 5. Python 가상환경과 패키지 설치

**프로젝트 최상위 `playmate/` 폴더에서 실행합니다.**

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements-dev.txt
```

가상환경을 이미 만든 팀원은 **다시 생성하지 말고** 새 터미널에서 활성화한 후 필요한 경우 패키지만 갱신합니다.

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements-dev.txt
```

프론트엔드 의존성 설치(처음 1회 또는 패키지 변경 시):

```powershell
cd frontend
npm.cmd install
cd ..
```

## 6. Aiven PostgreSQL과 `.env` 설정

루트에 `.env`가 없는 팀원만 아래 명령을 실행합니다.

```powershell
Copy-Item .env.example .env
notepad .env
```

실제 접속값은 DB 담당자에게 별도 전달받습니다. 아래는 **입력 양식**이지 실제 계정 정보가 아닙니다.

```dotenv
DB_HOST=실제_Aiven_Host
DB_PORT=실제_Aiven_Port
DB_USER=실제_DB_User
DB_PASSWORD=실제_DB_Password
DB_NAME=실제_DB_Name
DB_SSLMODE=require

APP_ENV=development
FRONTEND_ORIGINS=http://localhost:5173

VITE_API_BASE_URL=http://localhost:8000/api
VITE_DEV_MEMBER_ID=실제로_존재하는_member_id
```

- DB 포트가 반드시 `5432`인 것은 아닙니다. Aiven 접속 화면을 확인하세요.
- `VITE_DEV_MEMBER_ID`는 프론트엔드의 **개발 전용** 설정이며 DB `members.member_id`에 존재하는 정수 ID로 바꿔야 합니다.
- `.env`에는 비밀번호가 들어 있으므로 **GitHub에 커밋하거나 Discord에 공유하면 안 됩니다.**
- 이미 `.env`를 갖고 있다면 그대로 사용하고, `.env.example`에서 변수 구성이 바뀌었는지만 확인합니다.

프로젝트 루트에서 읽기 위주의 DB 연결·스키마 확인:

```powershell
python database\scripts\check_connection.py
python database\scripts\inspect_schema.py
```

**주의:** `python database\scripts\apply_board_migration.py`는 공용 DB 구조를 변경합니다. 팀원들이 임의로 반복 실행하지 말고 DB 담당자와 적용 여부를 확인하세요.

## 7. FastAPI 및 React 실행

### 터미널 1: 백엔드

프로젝트 루트에서:

```powershell
.\.venv\Scripts\Activate.ps1
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

`Uvicorn running on http://127.0.0.1:8000` 및 `Application startup complete`를 확인하고 **터미널을 닫지 마세요.**

| 확인 항목 | 주소 |
|---|---|
| 백엔드 실행 상태 | http://localhost:8000/health |
| 실제 DB 연결 상태 | http://localhost:8000/health/db |
| Swagger 문서 | http://localhost:8000/docs |

`/health`가 정상이어도 DB 연결이 실패할 수 있으니 `/health/db`까지 확인합니다.

### 터미널 2: 프론트엔드

새 VS Code 터미널을 열고 프로젝트 루트에서:

```powershell
cd frontend
npm.cmd run dev
```

패키지 오류가 나면 `npm.cmd install` 실행 후 다시 시도합니다. 정상 실행 시 표시되는 주소, 일반적으로 **http://localhost:5173**, 로 접속합니다. Vite가 다른 포트를 안내하면 실제 출력된 포트를 사용합니다.

## 8. Swagger 실습 전에 꼭 알아둘 것

1. Swagger는 **http://localhost:8000/docs**에서 확인합니다. 본인 컴퓨터에서 백엔드를 실행해야 열립니다.
2. 현재 게시판 백엔드는 **개발 전용 회원 ID 헤더**를 요구합니다. 일반 로그인이나 Discord OAuth가 연결된 상태라고 가정하면 안 됩니다.
3. 모든 게시판 API 요청에 `X-Dev-Member-ID` 헤더와 **DB에 실제 존재하는 정수 회원 ID**가 필요합니다. 서버의 `APP_ENV`는 `development` 또는 `test`여야 합니다.
4. Swagger의 `Try it out` → 입력 → `Execute`로 요청합니다. Swagger에서 해당 헤더 입력란이 보이면 값을 넣으세요. 일반적으로 이 프로젝트에서는 의존성에 의해 헤더 파라미터로 표시됩니다.
5. GET은 조회, POST는 생성, PATCH는 수정, DELETE는 삭제입니다. **공용 Aiven DB에 연결했다면 POST/PATCH/DELETE는 다른 팀원 데이터에도 영향을 줍니다.**
6. 직접 만든 **테스트 게시판·테스트 게시글·테스트 댓글**만 수정/삭제하세요. 삭제는 논리 삭제라 DB에 이력이 남을 수 있습니다.
7. `board_id`, `post_id`, `comment_id`는 예시 숫자를 입력하지 말고, **실제 POST 응답에 나온 ID**를 적어 두세요.

### 응답 코드 빠르게 읽기

| 코드 | 의미 | 대표 상황 |
|---|---|---|
| 200 OK | 조회 또는 수정 성공 | GET, PATCH |
| 201 Created | 생성 성공 | POST |
| 204 No Content | 삭제 성공, 응답 본문 없음 | DELETE |
| 401 Unauthorized | 개발용 회원 헤더 누락·유효하지 않은 ID | 인증 확인 |
| 403 Forbidden | 본인 소유가 아닌 데이터 수정·삭제 | 작성자 권한 검사 |
| 404 Not Found | 없는/삭제된 게시판·게시글·댓글 | ID 및 삭제 상태 확인 |
| 409 Conflict | 중복 등 상태 충돌 가능 | 응답 `detail` 확인 |
| 422 Unprocessable Entity | 필수 필드 누락·검증 오류 | 스키마 및 입력값 확인 |
| 503 Service Unavailable | DB 접속 장애 등 | `/health/db` 및 서버 로그 확인 |

실제 코드와 DB 상태에 따라 구체적인 오류 메시지는 달라질 수 있습니다. **Swagger Response body의 `detail`과 백엔드 터미널 로그를 함께 확인**하세요.

## 9. 게시판 API 전체 목록 (현재 코드 기준 12개)

| 번호 | HTTP | 엔드포인트 | 기능 |
|---:|---|---|---|
| 1 | GET | `/api/boards` | 게시판 목록 조회 |
| 2 | POST | `/api/boards` | 게시판 생성 |
| 3 | GET | `/api/boards/{board_id}` | 게시판 상세 조회 |
| 4 | GET | `/api/boards/{board_id}/posts` | 게시글 목록·검색·정렬 |
| 5 | POST | `/api/boards/{board_id}/posts` | 게시글 생성 및 이미지 업로드 |
| 6 | GET | `/api/boards/{board_id}/posts/{post_id}` | 게시글 상세 조회 |
| 7 | PATCH | `/api/boards/{board_id}/posts/{post_id}` | 게시글 수정 |
| 8 | DELETE | `/api/boards/{board_id}/posts/{post_id}` | 게시글 삭제 |
| 9 | GET | `/api/boards/{board_id}/posts/{post_id}/comments` | 댓글 목록 조회 |
| 10 | POST | `/api/boards/{board_id}/posts/{post_id}/comments` | 댓글 생성 |
| 11 | PATCH | `/api/comments/{comment_id}` | 댓글 수정 |
| 12 | DELETE | `/api/comments/{comment_id}` | 댓글 삭제 |

> 게시판 3개 + 게시글 5개 + 댓글 4개 = **총 12개**입니다. `/health`, `/health/db`는 별도의 서버 상태 확인 API 2개로, 위 목록에 포함하지 않았습니다.

## 10. Swagger에서 순서대로 실습하기

**실습 규칙:** 자신의 테스트 데이터만 사용하고 매 단계에서 생성된 ID를 기록하세요. 브라우저에서 `http://localhost:8000/docs` 접속 → 해당 API 펼치기 → `Try it out` → 헤더/경로/요청 본문 입력 → `Execute` → `Response code`와 `Response body` 확인 순서입니다.

### 실습 A. 게시판 목록 조회 (GET `/api/boards`)

1. `GET /api/boards` 선택
2. `X-Dev-Member-ID`에 유효한 회원 ID 입력
3. Execute → 목록 JSON 및 기본 자유게시판 확인

정상 응답은 일반적으로 `200`입니다.

### 실습 B. 테스트 게시판 생성 (POST `/api/boards`)

현재 백엔드 `BoardCreate` 스키마에는 **`category`가 필수값**입니다. **프론트엔드 생성 모달에서 카테고리 선택 UI를 없앤 것과는 별개의 문제**입니다. Swagger 테스트에서는 반드시 `category`를 보내야 합니다.

```json
{
  "name": "Swagger 게시판 실습",
  "category": "자유",
  "description": "API 연습용 게시판",
  "creation_reason": "팀 내부 테스트"
}
```

`X-Dev-Member-ID` 헤더도 입력하세요. 성공하면 `201`과 응답의 **`id`(board_id)**를 기록합니다. `category`는 현재 스키마에서 `자유`, `정보공유`, `분실물`, `취업`만 허용합니다. 서비스 최종 요구사항과 백엔드 스키마의 차이는 추후 통일이 필요합니다.

### 실습 C. 게시판 상세 조회 (GET `/api/boards/{board_id}`)

방금 생성한 게시판 응답의 **`id`**를 `board_id`에 넣고 실행합니다. 제목·설명이 일치하는지 확인하세요.

### 실습 D. 게시글 생성 (POST `/api/boards/{board_id}/posts`)

이 API는 JSON 입력이 아니라 **Form / multipart 업로드** 방식입니다.

- `board_id`: 위 실습에서 만든 게시판 ID
- `title`: `Swagger 게시글 테스트`
- `body`: `게시판 API 작동 확인용 글입니다.`
- `images`: 선택 사항. 이미지를 넣을 경우 Swagger의 파일 선택기를 사용
- `X-Dev-Member-ID`: 본인 테스트 회원 ID

정상 응답은 `201`이며 **`id`(post_id)**를 기록하세요. 이미지는 최대 3장까지 지원하는 구현입니다. 업로드 파일 제약 사항은 `backend/app/core/uploads.py`에서 확인합니다.

### 실습 E. 게시글 목록·검색·정렬 (GET `/api/boards/{board_id}/posts`)

`board_id`에 테스트 게시판 ID를 넣고 실행합니다. 선택적인 쿼리 파라미터:

- `q`: 제목·본문 검색을 위한 검색어. 예: `Swagger`
- `sort`: 기본값 `latest` (최신순). 다른 정렬값은 현재 서비스 구현을 확인해 사용

게시글을 만들기 전 빈 배열 `[]`이 나올 수 있으며, 데이터가 없다는 의미이지 반드시 오류는 아닙니다.

### 실습 F. 게시글 상세 조회 (GET `/api/boards/{board_id}/posts/{post_id}`)

기록한 `board_id`와 `post_id`를 입력합니다. 제목, 본문, 작성자 익명 표시, 이미지 URL 등을 확인합니다.

### 실습 G. 게시글 수정 (PATCH `/api/boards/{board_id}/posts/{post_id}`)

기존 **작성자와 같은 회원 ID**로 실행합니다.

```json
{
  "title": "Swagger 게시글 테스트 (수정)",
  "body": "내용 수정이 정상 반영되는지 확인합니다."
}
```

현재 `PostWrite` 스키마에서는 **`title`, `body` 둘 다 입력**해야 합니다. 성공하면 `200`, 다시 상세 조회하여 반영 여부를 확인합니다. 다른 회원 ID로 요청하면 권한 검사로 거절되어야 합니다.

### 실습 H. 댓글 생성 (POST `/api/boards/{board_id}/posts/{post_id}/comments`)

```json
{
  "body": "Swagger 댓글 작성 테스트"
}
```

`board_id`, `post_id`, 회원 헤더 입력 후 실행합니다. 성공 `201`의 응답에서 **`id`(comment_id)**를 기록합니다.

### 실습 I. 댓글 목록 조회 (GET `/api/boards/{board_id}/posts/{post_id}/comments`)

방금 작성한 댓글 내용과 `comment_id`가 목록에 표시되는지 확인합니다.

### 실습 J. 댓글 수정 (PATCH `/api/comments/{comment_id}`)

```json
{
  "body": "Swagger 댓글 수정 테스트"
}
```

본인이 쓴 댓글만 수정할 수 있습니다. 성공 후 댓글 목록에서 내용이 바뀌었는지 확인합니다.

### 실습 K. 댓글 삭제 (DELETE `/api/comments/{comment_id}`)

**본인 테스트 댓글**을 삭제합니다. 정상 응답은 `204`로 응답 본문이 없을 수 있습니다. 다시 댓글 조회해 삭제 처리 결과를 확인합니다.

### 실습 L. 게시글 삭제 (DELETE `/api/boards/{board_id}/posts/{post_id}`)

마지막에 **본인이 만든 테스트 게시글**만 삭제합니다. 정상 응답은 `204`입니다. 이후 상세 조회·목록에서 삭제 반영 여부를 확인합니다. Soft Delete 처리라 DB의 물리적 행 삭제와는 다를 수 있습니다.

> 현재 Swagger API 목록에는 **게시판 삭제 API가 없습니다.** 공용 DB에 테스트 게시판이 생성되면 남을 수 있으므로 테스트 게시판을 무분별하게 만들지 말고 DB 담당자와 정리하세요.

## 11. 권한·예외 상황 점검

| 시험 | 기대 결과 |
|---|---|
| 헤더 없이 게시판 조회 | `401` |
| 존재하지 않는 회원 ID | `401` |
| 다른 회원 ID로 내 게시글·댓글 PATCH / DELETE | `403` 등 권한 거절 |
| 존재하지 않는 게시글 ID | `404` |
| 공백 제목·본문 | `422` |
| 이미지 최대 수량 초과 | 유효성 검사로 거절 |
| 백엔드 종료 후 프론트 조회 | API 연결 오류 표시 |

다른 실제 회원의 ID를 무단으로 사용하지 말고 **팀에서 허가된 테스트 회원 계정**으로만 권한 테스트를 진행하세요. 공용 DB라면 테스트 후 기록을 남기세요.

## 12. 자주 발생하는 오류 해결

| 현상 | 먼저 확인할 내용 |
|---|---|
| `git` 명령어 없음 | Git 설치, VS Code 재시작 |
| `npm.cmd`·`node` 인식 안 됨 | Node.js 설치와 PATH, 필요 시 터미널 재시작 |
| `Activate.ps1` 실행 제한 | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| `ModuleNotFoundError` | `.venv` 활성화 및 requirements 설치 |
| `/docs` 접속 불가 | Uvicorn 실행 상태·포트 8000 확인 |
| `/health` 성공, `/health/db` 실패 | DB Host·Port·SSL·비밀번호·네트워크 확인 |
| API `401` | `APP_ENV=development`, `X-Dev-Member-ID`, 실제 회원 ID |
| API `403` | 본인이 작성한 글·댓글인지 확인 |
| API `422` | 필수 필드, JSON/Form 차이, 문자열 길이·이미지 제약 확인 |
| API `404` | `board_id`, `post_id`, `comment_id` 실값 확인 |
| 프론트 `Failed to fetch` | 백엔드 주소, CORS, 포트 확인 |
| `git pull` 실패 | `git status` 및 로컬 수정 사항 보관 |
| `git push` 거절 | 팀원 변경사항 먼저 반영, 강제 Push 금지 |

## 13. 실습 완료 체크리스트

- [ ] `feature/board`에서 Clone 또는 Pull 완료
- [ ] Python 가상환경 활성화 및 패키지 설치
- [ ] `.env` 설정, `/health/db` 확인
- [ ] FastAPI 실행, Swagger 접속
- [ ] React 실행, 게시판 웹사이트 접속
- [ ] 개발용 테스트 회원 ID 준비 및 인증 헤더 입력
- [ ] 게시판 목록·생성·상세 테스트
- [ ] 게시글 생성·목록·상세·수정·삭제 테스트
- [ ] 댓글 생성·목록·수정·삭제 테스트
- [ ] 이미지 첨부, 검색·정렬 UI 점검
- [ ] 공용 DB에 남긴 테스트 데이터 기록

## 14. 이후 GitHub에 변경 내용 올리기

프로젝트 루트에서 작업 파일을 확인한 후 해당 파일만 커밋하는 것이 안전합니다.

```powershell
git status
git add frontend/BOARD_SETUP_GUIDE.md
git commit -m "docs: 게시판 통합 설치 및 API 실습 가이드 보완"
git push origin feature/board
```

> 문서 작성 기준: `feature/board` 브랜치의 `backend/app/routers/board.py`, `backend/app/schemas/board.py`, `backend/app/core/auth.py` 및 기존 게시판 설치 가이드. 실제 배포된 버전 또는 이후 커밋에 따라 Swagger 화면·입력값·상태 코드가 달라질 수 있으니 **실습 전에 현재 코드와 `/docs`를 함께 확인**하세요.
