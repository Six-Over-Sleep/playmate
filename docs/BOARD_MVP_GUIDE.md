# PlayMate 게시판 MVP 실행·검증 가이드

## 1. 구성과 DB 정책

React → FastAPI → Aiven PostgreSQL로 동작한다. 기존 `members`, `posts`, `recruits`, `boards`, `comments`를 재사용하고 누락된 게시판 컬럼과 `post_images`만 추가한다. 글과 댓글은 `deleted_at` 논리 삭제이며, `recruits`에 연결된 모임 글은 게시판 API의 조회·수정·삭제에서 제외된다.

기본 자유게시판은 마이그레이션이 여러 번 실행되어도 `WHERE NOT EXISTS`로 한 번만 생성된다. 공개 작성자명은 `members.public_anonymous_id`이고 실제 `member_id`는 응답 화면에 노출하지 않는다.

주요 파일:

- `backend/app/core/db_connect.py`: psycopg2, SSL, 트랜잭션
- `backend/app/core/auth.py`: 개발 전용 회원 검증; Discord OAuth 연결 지점
- `backend/app/routers/board.py`: API와 이미지 검증
- `backend/app/services/board_service.py`: PostgreSQL 쿼리와 권한 검사
- `database/sql/001_board_mvp.sql`: 추가 전용 스키마
- `frontend/src/`: 게시판 목록·상세·생성·글/댓글·이미지 UI

## 2. 처음 설치하기

PowerShell에서 다음을 실행한다.

```powershell
Set-Location 'C:\Users\Playdata\Desktop\toy_board'
git branch --show-current
python --version
node --version
npm --version

python -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend\requirements-dev.txt

Set-Location frontend
npm install
Set-Location ..
```

루트 `.env`에는 아래 이름을 사용한다. 실제 비밀번호는 출력하거나 커밋하지 않는다.

```dotenv
DB_HOST=
DB_PORT=5432
DB_USER=
DB_PASSWORD=
DB_NAME=
DB_SSLMODE=require
APP_ENV=development
FRONTEND_ORIGINS=http://localhost:5173
VITE_API_BASE_URL=http://localhost:8000/api
VITE_DEV_MEMBER_ID=
```

Aiven은 `DB_SSLMODE=require`를 유지한다. `VITE_DEV_MEMBER_ID`에는 실제 `members.member_id`를 넣는다. 서버도 해당 회원이 존재하는지 다시 확인한다.

## 3. DB 연결과 마이그레이션

먼저 데이터 변경 없는 검사를 실행한다.

```powershell
python database\scripts\check_connection.py
python database\scripts\inspect_schema.py
```

개발/테스트 DB임을 확인한 뒤에만 실행한다.

```powershell
python database\scripts\apply_board_migration.py
```

pgAdmin, `psql` 또는 Aiven 콘솔 Query editor에서 확인한다.

```sql
SELECT current_database(), version();
SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name;
SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='public' AND table_name='posts' ORDER BY ordinal_position;

SELECT board_id, board_name, category, description, created_by, is_default, created_at
FROM boards ORDER BY is_default DESC, created_at;

SELECT post_id, board_id, author_member_id, title, deleted_at
FROM posts ORDER BY post_id DESC LIMIT 20;

SELECT comment_id, post_id, author_member_id, body, deleted_at
FROM comments ORDER BY comment_id DESC LIMIT 20;
```

`database/sql/002_verify_board_relations.sql`의 세 쿼리가 모두 0행인지 확인한다. 기존 데이터가 있으면 삭제하지 말고 팀과 먼저 정리한다.

## 4. 서버 실행

터미널 1:

```powershell
Set-Location 'C:\Users\Playdata\Desktop\toy_board\backend'
..\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

- `http://localhost:8000/health`: FastAPI 프로세스 확인
- `http://localhost:8000/health/db`: 실제 PostgreSQL 연결과 DB명 확인
- `http://localhost:8000/docs`: API 문서

터미널 2:

```powershell
Set-Location 'C:\Users\Playdata\Desktop\toy_board\frontend'
npm run dev
```

브라우저에서 `http://localhost:5173`을 연다.

## 5. 기능 검증 순서

1. 왼쪽 최상단 `자유게시판`을 확인하고 클릭한다.
2. `+ 게시판 만들기`에서 카테고리, 이름, 소개, 만드는 이유를 입력한다. 생성 직후 선택되고 새로고침 후 유지되어야 한다.
3. `+ 글쓰기`에서 제목·본문과 최대 3장 이미지를 선택한다. 미리보기/제거 후 등록하고 상세로 이동하는지 본다.
4. 상세의 제목, 익명 ID, 작성일, 줄바꿈 본문, 이미지를 확인한다.
5. 댓글을 등록하고 즉시 개수와 목록이 갱신되는지 본다. 새로고침 후에도 유지되어야 한다.
6. 다른 회원 ID로 `.env`의 `VITE_DEV_MEMBER_ID`를 바꾸고 서버/프론트를 재시작한다. 타인 글/댓글 PATCH·DELETE는 403이어야 한다.
7. 검색 결과 없음과 API 실패를 구분한다. 백엔드를 끄면 빈 목록 문구가 아니라 연결 오류와 다시 시도 버튼이 보여야 한다.

개발자 도구는 F12 → Network → Fetch/XHR에서 URL, Method, Status, Response를 확인한다. 정상 코드는 조회/수정 200, 생성 201, 삭제 204, 미인증 401, 권한 없음 403, 없음 404, 중복 409, 입력 오류 422, DB 연결 장애 503이다.

## 6. PowerShell API 예시

```powershell
$headers = @{ 'X-Dev-Member-ID' = '1' }
Invoke-RestMethod 'http://localhost:8000/api/boards' -Headers $headers

$board = @{ name='알고리즘 질문'; category='자유'; description='함께 문제를 풀어요'; creation_reason='질문 공간 필요' } | ConvertTo-Json
Invoke-RestMethod 'http://localhost:8000/api/boards' -Method Post -Headers $headers -ContentType 'application/json' -Body $board
```

글과 이미지 등록은 Swagger `/docs`의 `POST /api/boards/{board_id}/posts`에서 `Try it out`을 누르고 `title`, `body`, `images`를 입력하는 것이 가장 쉽다.

## 7. 자동화 테스트

```powershell
Set-Location 'C:\Users\Playdata\Desktop\toy_board'
.\.venv\Scripts\Activate.ps1
pytest backend\tests -q
Set-Location frontend
npm run build
```

격리된 PostgreSQL 테스트 DB에서만 통합 테스트를 켠다.

```powershell
$env:RUN_POSTGRES_INTEGRATION='1'
pytest backend\tests\integration -q
Remove-Item Env:RUN_POSTGRES_INTEGRATION
```

운영 또는 팀 공용 DB에서는 통합 테스트를 실행하지 않는다.

## 8. 오류 해결

- `Failed to fetch`: 백엔드 8000 포트 실행, `VITE_API_BASE_URL`, CORS를 확인한다.
- `/health` 성공, `/health/db` 503: DB 호스트/포트/TLS/허용 IP/계정 권한을 확인한다.
- 401: `X-Dev-Member-ID` 또는 `VITE_DEV_MEMBER_ID`가 없거나 실제 회원이 아니다.
- 404: `/api` 접두사와 ID를 확인한다.
- 422: 공백 필드, 3장 초과, 5MB 초과, 허용되지 않은 이미지 또는 위조 이미지다.
- CORS: `FRONTEND_ORIGINS=http://localhost:5173` 설정 후 백엔드를 다시 시작한다.
- 테이블 없음: 공용 `members`, `posts`, `recruits` 존재를 먼저 확인하고 마이그레이션을 적용한다.

## 9. Git 병합 점검

```powershell
git branch --show-current
git status
git diff --stat
git diff
git check-ignore .env .venv frontend/node_modules frontend/dist uploads
```

`.env`, 업로드 이미지, 의존성, 빌드 결과는 커밋하지 않는다. 충돌 가능성이 높은 파일은 `backend/app/main.py`, `frontend/src/App.jsx`, `.env.example`, `.gitignore`다. Discord OAuth가 합쳐질 때 `get_current_member_id`를 실제 로그인 의존성으로 교체한다.
