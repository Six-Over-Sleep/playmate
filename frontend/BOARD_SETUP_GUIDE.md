# PlayMate 게시판 설치 및 실행 가이드

GitHub 저장소: [Six-Over-Sleep/playmate](https://github.com/Six-Over-Sleep/playmate/tree/feature/board)
작업 브랜치: **`feature/board`**

| 구분      | 기술                           |
| --------- | ------------------------------ |
| Frontend  | React + Vite                   |
| Backend   | Python + FastAPI               |
| Database  | Aiven PostgreSQL               |
| 버전 관리 | Git + GitHub                   |
| 안내 환경 | Windows / VS Code / PowerShell |

이 문서는 **GitHub에서 프로젝트를 처음 받는 팀원**과 **이미 프로젝트를 받은 뒤 최신 코드를 가져와야 하는 팀원**을 모두 위한 안내입니다.

> **처음 받는 사람 → `git clone` / 이미 받은 사람 → `git pull`**
> `feature/board`는 게시판 개발 브랜치이며, 해당 브랜치에 Push해도 `main`에 자동 반영되지는 않습니다.

## 전체 실행 순서

1. Git, Python, Node.js, VS Code 설치
2. 코드 가져오기: 처음이면 **Clone**, 이미 받았다면 **Pull**
3. Python 가상환경 및 백엔드 패키지 설치
4. `.env` 작성 및 PostgreSQL DB 연결 확인
5. FastAPI 백엔드 실행
6. React 프론트엔드 실행
7. 브라우저에서 게시판 기능 테스트
8. 이후 최신 코드 갱신 및 GitHub Push

---

## 프로젝트 폴더 구조와 역할

처음 코드를 받은 팀원은 먼저 전체 폴더의 역할을 확인하세요. **각 폴더는 담당하는 기능이 다르므로, 수정할 기능에 맞는 위치에서 작업**하면 됩니다.

```text
playmate/
├─ ai/                       # AI 관련 기능 및 실험 코드
├─ backend/                  # FastAPI 서버와 게시판 API
│  ├─ app/
│  │  ├─ core/               # DB 연결, 인증 등 공통 설정
│  │  ├─ routers/            # API 주소와 요청 처리
│  │  └─ services/           # 게시판 데이터 처리 및 비즈니스 로직
│  ├─ tests/                 # 백엔드 테스트
│  ├─ requirements.txt       # 백엔드 의존성
│  └─ requirements-dev.txt   # 개발·테스트용 추가 의존성
├─ crawler/                  # 외부 데이터 수집 관련 코드
├─ database/                 # PostgreSQL SQL 및 DB 점검 스크립트
│  ├─ sql/                   # 테이블/관계 등 SQL 관리
│  └─ scripts/               # DB 연결 확인·스키마 검사 등
├─ docs/                     # 프로젝트 설명 및 개발·검증 문서
│  ├─ BOARD_MVP_GUIDE.md     # 게시판 MVP 실행·테스트 상세 가이드
│  └─ BOARD_SETUP_GUIDE.md   # 지금 보고 있는 게시판 설치 가이드
├─ frontend/                 # React + Vite 화면
│  ├─ src/                   # 게시판 화면·컴포넌트·API 호출 코드
│  ├─ package.json           # 프론트엔드 패키지 및 실행 스크립트
│  └─ vite.config.js         # Vite 개발 서버 설정
├─ .env.example              # 환경변수 양식 (비밀번호 없음)
├─ .gitignore                # Git에 올리지 않을 파일/폴더 지정
└─ README.md                 # 프로젝트 전체 소개 및 문서 링크
```

> 위 트리는 **주요 폴더와 파일만 표시한 간략 구조**입니다. 세부 파일은 작업에 따라 추가되거나 변경될 수 있습니다.

### 어떤 작업을 할 때 어디를 수정하나요?

| 작업 내용                            | 주로 확인할 위치                                            | 설명                                                 |
| ------------------------------------ | ----------------------------------------------------------- | ---------------------------------------------------- |
| 게시판 생성 창의 위치·디자인 수정   | `frontend/src/`                                           | 화면 구성, 버튼, 모달, CSS 등 사용자에게 보이는 부분 |
| 정렬 버튼·목록 표시 동작 수정       | `frontend/src/`                                           | 화면 상태와 API 호출·정렬 관련 코드 확인            |
| 게시글·댓글 등록/수정/삭제 API 수정 | `backend/app/routers/`, `backend/app/services/`         | 요청 처리와 실제 데이터 처리 로직                    |
| DB 연결 문제 확인                    | `backend/app/core/`, `.env`                             | 접속 정보 및 인증·연결 설정                         |
| 테이블·컬럼 구조 확인               | `database/sql/`, `database/scripts/`                    | SQL 및 DB 점검 코드. 공용 DB 수정은 담당자 협의 필요 |
| 패키지 설치·서버 실행 설정          | `backend/requirements-dev.txt`, `frontend/package.json` | Python/Node 의존성과 실행 스크립트                   |
| 사용 방법·테스트 방법 업데이트      | `docs/BOARD_SETUP_GUIDE.md`, `docs/`                    | 새 팀원이 따라 할 수 있는 프로젝트 문서              |
| AI·크롤링 관련 개발                 | `ai/`, `crawler/`                                       | 게시판 이외 기능별 코드                              |

**자주 헷갈리는 점:** `frontend`는 화면을, `backend`는 API·서버를, `database`는 DB 스키마·점검 코드를 담당합니다. 실제 게시글 데이터는 소스 폴더가 아니라 **연결된 PostgreSQL DB에 저장**됩니다.

`.venv/`(Python 가상환경), `frontend/node_modules/`(설치된 Node 패키지), `.env`(개인 접속 정보)는 설치 후 로컬 PC에 생성되는 파일·폴더이며, 보통 GitHub에 올리지 않습니다.

---

## STEP 1. 개발 환경 설치

| 프로그램 | 용도                                           | 설치 주소                                    |
| -------- | ---------------------------------------------- | -------------------------------------------- |
| Git      | GitHub 코드 다운로드 및 버전 관리              | [다운로드](https://git-scm.com/downloads/win) |
| VS Code  | 코드 편집 및 터미널                            | [다운로드](https://code.visualstudio.com/)    |
| Python   | FastAPI 백엔드 실행 (권장: 3.12)               | [다운로드](https://www.python.org/downloads/) |
| Node.js  | React 프론트엔드 실행 (지원되는 LTS 버전 권장) | [다운로드](https://nodejs.org/)               |

VS Code에서 **Terminal → New Terminal**을 열고 PowerShell에서 아래 명령어를 실행합니다.

```powershell
git --version
python --version
node --version
npm.cmd --version
```

각 프로그램의 버전이 나오면 정상입니다. 명령어를 찾을 수 없다고 나오면 해당 프로그램을 설치하고 VS Code를 다시 실행합니다.

---

## STEP 2. GitHub에서 코드 가져오기

**본인 상황에 맞는 A 또는 B 중 하나만 진행하세요.**

### A. 처음 프로젝트를 받는 팀원 — `git clone`

아직 본인 PC에 `playmate` 프로젝트가 없는 경우입니다.

**① 프로젝트를 저장할 위치로 이동**

```powershell
cd "$HOME\Desktop"
```

**② `feature/board` 브랜치를 지정하여 Clone**

```powershell
git clone -b feature/board https://github.com/Six-Over-Sleep/playmate.git
```

**③ 생성된 프로젝트 폴더로 이동**

```powershell
cd playmate
```

**④ 현재 브랜치와 Git 상태 확인**

```powershell
git branch --show-current
git status
```

브랜치가 `feature/board`이고 수정된 파일이 없다면 아래와 유사하게 표시됩니다.

```text
On branch feature/board
Your branch is up to date with 'origin/feature/board'.

nothing to commit, working tree clean
```

완료되었다면 **STEP 3**으로 이동합니다.

### B. 이미 프로젝트를 받은 팀원 — `git pull`

이미 프로젝트를 Git으로 Clone한 경우 **다시 Clone할 필요가 없습니다.** 기존 프로젝트 폴더에서 최신 코드를 가져오면 됩니다.

**① VS Code에서 기존 `playmate` 프로젝트 열기**

VS Code에서 **File → Open Folder**로 기존 폴더를 열고 새 터미널을 실행합니다. 또는 해당 프로젝트가 설치된 경로로 이동합니다.

```powershell
# 예시: C:\dev\project\playmate에 설치된 경우
cd C:\dev\project\playmate
```

> 폴더 위치는 컴퓨터마다 다를 수 있습니다. 바탕화면에 Clone했다면 `cd "$HOME\Desktop\playmate"`를 사용합니다.

**② 수정 중인 코드가 있는지 확인**

```powershell
git status
```

`nothing to commit, working tree clean`이라면 다음 단계로 진행하면 됩니다. 수정 파일이 있다면 먼저 Commit하거나 안전하게 백업/스태시하여 작업을 보관하세요. `pull` 도중 로컬 변경과 충돌할 수 있습니다.

**③ 게시판 브랜치로 이동**

```powershell
git switch feature/board
```

로컬에 해당 브랜치가 없다면 아래 명령어로 원격 브랜치를 가져와 연결합니다.

```powershell
git fetch origin
git switch --track origin/feature/board
```

**④ 최신 코드 가져오기**

```powershell
git pull origin feature/board
```

**⑤ 상태 다시 확인**

```powershell
git status
```

`Already up to date.`가 나오면 이미 최신입니다. 새 코드가 내려받아졌다면 변경된 파일들이 출력될 수 있습니다.

**주의사항**

- **기존 `.env`는 삭제하거나 덮어쓰지 않습니다.** 로컬 접속 정보는 계속 사용합니다.
- `git pull`은 소스코드를 갱신할 뿐, 라이브러리 설치나 서버 실행까지 자동으로 해주지는 않습니다.
- 원격과 로컬 이력이 갈라졌거나 충돌이 발생하면 임의로 `reset --hard` 또는 강제 Push하지 말고 변경 내용을 확인합니다.
- 이미 개발 환경을 설치했다면 STEP 3~4를 확인한 후 **STEP 5부터 서버를 재실행**하면 됩니다.

### Clone과 Pull의 차이

| 상황                    | 사용할 명령어                                 | 설명                               |
| ----------------------- | --------------------------------------------- | ---------------------------------- |
| 최초 1회 다운로드       | `git clone -b feature/board <저장소 주소>`  | 새 프로젝트 폴더 생성              |
| 이미 받은 프로젝트 갱신 | `git pull origin feature/board`             | 기존 폴더에 최신 코드 반영         |
| 내 작업 GitHub 업로드   | `git add` → `git commit` → `git push` | 내 변경사항을 원격 브랜치에 업로드 |

---

## STEP 3. Python 가상환경 및 백엔드 라이브러리 설치

**프로젝트 최상위 폴더(`playmate`)에서 실행합니다.**

### ① 가상환경 생성 (최초 1회)

```powershell
python -m venv .venv
```

### ② PowerShell 가상환경 실행 허용

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

현재 터미널 세션에만 적용되는 설정입니다.

### ③ 가상환경 활성화

```powershell
.\.venv\Scripts\Activate.ps1
```

정상적으로 실행되면 터미널 앞에 `(.venv)`가 표시됩니다.

### ④ 백엔드 패키지 설치

```powershell
python -m pip install --upgrade pip
python -m pip install -r backend\requirements-dev.txt
```

FastAPI, Uvicorn, PostgreSQL 연결 라이브러리 등 필요한 패키지를 설치합니다.

> **이미 설치한 팀원:** `.venv`를 매번 다시 생성할 필요는 없습니다. 터미널을 새로 열 때 가상환경만 활성화하면 됩니다. `requirements-dev.txt`에 변경이 생겼다면 패키지 설치 명령어를 다시 실행하세요.

---

## STEP 4. PostgreSQL DB 연결 설정

각 팀원은 로컬에 `.env` 파일이 필요합니다. **실제 DB 호스트, 계정, 비밀번호는 DB 담당자로부터 안전하게 전달받아야 합니다.**

### ① `.env` 파일 생성 (최초 1회)

프로젝트 루트에서 실행합니다.

```powershell
Copy-Item .env.example .env
notepad .env
```

> **기존 `.env`가 있으면 위 복사 명령어를 다시 실행하지 않습니다.** `git pull` 후 `.env.example`의 변수 구성이 달라졌다면 필요한 항목만 기존 `.env`에 추가하세요.

### ② 환경변수 입력

아래는 입력 형식입니다. DB 접속 정보는 실제 발급된 값으로 바꾸세요.

```dotenv
# Aiven PostgreSQL
DB_HOST=실제_PostgreSQL_호스트
DB_PORT=5432
DB_USER=실제_DB_계정
DB_PASSWORD=실제_DB_비밀번호
DB_NAME=실제_DB_이름
DB_SSLMODE=require

# Backend
APP_ENV=development
FRONTEND_ORIGINS=http://localhost:5173

# Frontend
VITE_API_BASE_URL=http://localhost:8000/api
VITE_DEV_MEMBER_ID=1
```

- `DB_PORT=5432`는 예시입니다. **실제 Aiven 접속 포트**를 확인하세요.
- `DB_SSLMODE=require`로 SSL 연결을 사용합니다.
- `VITE_DEV_MEMBER_ID=1`도 예시입니다. 실제 DB의 `members.member_id`에 존재하는 값을 사용해야 합니다.
- `.env`에는 비밀번호가 있으므로 **GitHub Push, 공개 채팅, 스크린샷 공유를 금지**합니다.

### ③ DB 연결 확인

가상환경이 활성화된 상태에서 **프로젝트 루트**에서 실행합니다.

```powershell
python database\scripts\check_connection.py
python database\scripts\inspect_schema.py
```

DB에 정상 연결되면 데이터베이스 정보, 테이블 및 스키마를 확인할 수 있습니다.

> **중요:** `python database\scripts\apply_board_migration.py`는 DB 구조를 변경합니다. 공용 DB에 이미 적용됐을 수 있으므로 **모든 팀원이 임의로 실행하면 안 됩니다.** DB 담당자가 적용 여부를 먼저 확인하세요.

---

## STEP 5. FastAPI 백엔드 실행

첫 번째 터미널을 사용합니다. **프로젝트 루트에서** 다음 명령어를 실행합니다.

```powershell
.\.venv\Scripts\Activate.ps1
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

정상 실행 시 다음과 비슷하게 표시됩니다.

```text
Uvicorn running on http://127.0.0.1:8000
Application startup complete.
```

**실행 중인 터미널을 닫지 마세요.** 브라우저에서 아래 주소들을 확인합니다.

| 확인 항목        | 주소                            |
| ---------------- | ------------------------------- |
| FastAPI 상태     | http://localhost:8000/health    |
| PostgreSQL 상태  | http://localhost:8000/health/db |
| Swagger API 문서 | http://localhost:8000/docs      |

`/health`뿐 아니라 `/health/db`도 정상인지 확인해야 게시판 데이터를 사용할 수 있습니다.

---

## STEP 6. React 프론트엔드 실행

백엔드 터미널은 그대로 두고 VS Code에서 **새 터미널을 하나 더 엽니다.** 새 터미널에서 **프로젝트 루트 기준**으로 다음 명령어를 실행합니다.

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

패키지는 처음 한 번 설치해야 합니다. 기존에 설치했고 의존성 변경이 없다면 `npm.cmd run dev`만 실행해도 됩니다.

정상 실행되면 아래와 유사한 주소가 표시됩니다.

```text
VITE ready
Local: http://localhost:5173/
```

**게시판 접속: http://localhost:5173**

두 서버를 동시에 실행한 상태여야 합니다.

| 터미널   | 서버             | 포트 |
| -------- | ---------------- | ---- |
| 터미널 1 | FastAPI 백엔드   | 8000 |
| 터미널 2 | React 프론트엔드 | 5173 |

---

## STEP 7. 게시판 기능 테스트

브라우저에서 아래 항목을 순서대로 확인합니다.

- [ ] 자유게시판 목록 조회
- [ ] 게시판 만들기 버튼 및 화면 중앙 생성 창 동작
- [ ] 게시판 생성 시 불필요한 카테고리 입력 없이 생성 가능 여부
- [ ] 게시판 정렬 버튼 정상 동작
- [ ] 게시글 작성 및 상세 조회
- [ ] 댓글 작성 및 조회
- [ ] 게시글 수정 및 삭제
- [ ] 새로고침 후 DB에 저장된 내용 유지

기능별 추가 설명: [BOARD_MVP_GUIDE.md](BOARD_MVP_GUIDE.md). 기존 문서에 남아 있는 이전 UI 설명은 최신 구현과 다를 수 있습니다.

---

## STEP 8. 이후 GitHub 최신 코드 받기 및 Push

### ① 팀원이 Push한 최신 코드 받기

기존 `playmate` 폴더에서 실행합니다.

```powershell
git status
git switch feature/board
git pull origin feature/board
```

**수정 중인 파일이 있으면 먼저 안전하게 보관하세요.** Pull은 여러 번 실행해도 괜찮고, 새 변경사항이 없다면 `Already up to date.`가 나옵니다.

### ② 내가 수정한 코드 올리기

```powershell
git status
git add .
git commit -m "fix: 게시판 UI 및 기능 수정"
git push origin feature/board
```

커밋 전 `.env` 등 비밀정보가 포함되지 않았는지 확인해야 합니다. 여러 명이 같은 브랜치를 사용한다면, 다른 팀원이 먼저 Push한 경우 최신 내용을 반영한 뒤 Push해야 합니다. **강제 Push(`--force`)는 팀원 변경사항을 덮어쓸 수 있으므로 사용하지 마세요.**

---

## 자주 발생하는 오류

| 오류                              | 확인 및 해결 방법                                                     |
| --------------------------------- | --------------------------------------------------------------------- |
| `git` 명령어를 찾을 수 없음     | Git 설치 후 VS Code 재시작                                            |
| `npm.cmd` 명령어를 찾을 수 없음 | Node.js LTS 설치 후 터미널 재시작                                     |
| `Activate.ps1` 실행 제한        | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` 실행   |
| `ModuleNotFoundError`           | 가상환경 활성화 후`requirements-dev.txt` 재설치                     |
| PostgreSQL 연결 실패              | `.env` 호스트/계정/포트/SSL/네트워크 확인                           |
| 게시판 요청에서`401`            | `VITE_DEV_MEMBER_ID`가 실제 회원 ID인지 확인                        |
| `Failed to fetch`               | 백엔드 8000 포트, API 주소, CORS 설정 확인                            |
| `/health/db`에서 `503`        | PostgreSQL 연결 또는 인증 확인                                        |
| `localhost:5173` 접속 불가      | 프론트엔드 실행 여부와 Vite에 표시된 실제 포트 확인                   |
| Pull 중 로컬 변경사항 경고        | `git status`로 확인하고 수정 파일을 커밋/백업/스태시한 뒤 다시 시도 |
| Push 거절 (`non-fast-forward`)  | 원격 변경사항을 먼저 반영하고 충돌 해결 후 재시도                     |

---

## 최종 요약: 상황별 실행 명령어

### A. 처음 받는 팀원 — 최초 1회

```powershell
cd "$HOME\Desktop"
git clone -b feature/board https://github.com/Six-Over-Sleep/playmate.git
cd playmate

git branch --show-current
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements-dev.txt

Copy-Item .env.example .env
notepad .env
# 실제 DB 접속 정보를 입력하고 저장

python database\scripts\check_connection.py
python database\scripts\inspect_schema.py
```

### B. 이미 받은 팀원 — 최신 코드 받기

```powershell
# 이미 설치된 프로젝트 폴더에서 실행
git status
git switch feature/board
git pull origin feature/board
```

### C. 터미널 1 — 백엔드 실행 (프로젝트 루트에서)

```powershell
.\.venv\Scripts\Activate.ps1
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

### D. 터미널 2 — 프론트엔드 실행 (프로젝트 루트에서)

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

**최종 접속 주소: http://localhost:5173**

> `feature/board`는 게시판 개발 브랜치입니다. 별도의 PR이나 병합 전까지 `main`에 자동 반영되지 않습니다.
