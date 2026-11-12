# PlayMate Backend

FastAPI 서버의 회원·게시판·취업·모임·마이페이지·관리자 API를 관리합니다. **2026-11-04 `develop` 코드 기준** 문서이며, 코드 구현과 운영 검증은 구분합니다.

## 1. 기술 스택

- Python **3.13 이상** (`pyproject.toml` 기준), `uv`
- FastAPI, Pydantic, SQLAlchemy
- PostgreSQL, `psycopg`(ORM), `psycopg2`(일부 직접 SQL/연결 풀)
- Discord OAuth2, Starlette 서명 세션 쿠키
- 테스트: pytest, httpx, 일회용 PostgreSQL 통합 테스트(필요한 경우)

패키지 설치 기준은 **저장소 루트의 `pyproject.toml`/`uv.lock`**입니다. `backend/requirements.txt`는 버전 구성이 달라 운영 설치 기준으로 혼용하지 않습니다.

## 2. 코드 구조

```text
backend/
├── app/
│   ├── main.py                 # FastAPI 앱 / 미들웨어 / 라우터
│   ├── core/                  # 환경변수·DB·세션 인증·업로드
│   ├── routers/               # API 엔드포인트
│   ├── schemas/               # 요청/응답 유효성 검사
│   ├── services/              # 업무 로직 및 트랜잭션
│   ├── repositories/          # DB 읽기/쓰기
│   ├── models/                # SQLAlchemy 모델
│   ├── domain/                # 모임 프로그램 정책
│   ├── integrations/          # 이벤트 연계
│   ├── jobs/                  # 모임 예약 처리
│   └── constants/             # 공용 분류 상수
├── scripts/                   # 진단 스크립트
└── tests/                     # 단위·API·DB 통합 테스트
```

세부 파일 분류: [core](app/core/README.md) / [models](app/models/README.md) / [routers](app/routers/README.md) / [schemas](app/schemas/README.md) / [services](app/services/README.md)

## 3. 설치 및 실행

저장소 루트에서 실행합니다.

```powershell
# develop 최신 코드
git fetch origin
git switch develop
git pull --ff-only origin develop

# 의존성 설치
uv sync

# 실행
uv run --directory backend uvicorn app.main:app --reload --port 8000
```

실행 전 루트 `.env`를 설정해야 합니다. `APP_ENV=development`를 명시하면 로컬 HTTP 로그인과 Swagger 문서 사용이 가능합니다.

```dotenv
APP_ENV=development
DISCORD_CLIENT_ID=your_id
DISCORD_CLIENT_SECRET=your_secret
DISCORD_REDIRECT_URI=http://localhost:8000/auth/discord/callback
SESSION_SECRET_KEY=replace_with_secure_random_string
DB_HOST=your_host
DB_PORT=5432
DB_USER=your_user
DB_PASSWORD=your_password
DB_NAME=your_database
DB_SSLMODE=require
FRONTEND_URL=http://localhost:5173
FRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
DB_POOL_MAX_CONNECTIONS=2
DB_POOL_WAIT_SECONDS=2
```

> 루트 `.env.example`은 현재 `develop` 트리에서 확인되지 않습니다. 실제 Secret은 담당자에게 별도로 전달받습니다.

| 확인 주소 | 용도 |
|---|---|
| `GET /` | 서버 응답 |
| `GET /health` | 서비스 상태 |
| `GET /health/db` | DB 연결 상태 |
| `/docs` | Swagger (development/test 환경만 노출) |
| `GET /auth/me` | 로그인/회원 상태 |

## 4. API 영역

| 모듈 | 기본 경로 | 기능 |
|---|---|---|
| `auth.py` | `/auth` | Discord 로그인·회원가입·탈퇴·로그아웃 |
| `board.py` | `/api` | 게시판·게시글·댓글·좋아요·스크랩 |
| `board_moderation.py` | `/api`, `/api/admin` | 게시글 신고·신고 관리 |
| `activity.py` | `/api` | 사용 시간·게시판 방문 기록 |
| `admin.py` | `/api/admin` | 관리자 대시보드·공지·회원 관리 |
| `career.py` | `/api/career` | 취업 후기·이직 이야기·라운지·연구소 |
| `career_news.py` | `/api/career/news` | 분야별 취업 뉴스·스크랩 |
| `recruit.py` | `/api/recruits` | 모임 모집·참여·활동·소셜 기능 |
| `recruit_program.py` | `/api/recruits` | 프로그램 확장·커리큘럼·XP 등 일부 기능 |
| `mypage.py` | `/api/mypage` | 프로필·레벨·출석·경험치·활동 내역 |

**주의:** `recruit_program.py`의 `router`는 기존 모임 CRUD를 덮어쓰지 않도록 자동 등록하지 않습니다. `main.py`에서는 `features_router`만 등록하며, 모임 기본 요청은 `recruit.py`의 디스패치 계층을 이용합니다.

## 5. 인증 및 권한

```text
Discord OAuth 로그인 → callback → 회원 DB 조회
  ├─ 가입 회원: 로그인 세션 저장 → 서비스 이용
  └─ 미가입 회원: 추가정보 입력 → 가입 후 서비스 이용
```

- OAuth `state`를 검증합니다.
- `get_current_member_id()`는 세션에 저장된 회원 ID·Discord ID와 DB의 활성 회원 상태를 검증합니다.
- `X-Dev-Member-ID`는 **development/test에서만**, 세션이 없을 때 허용됩니다. 운영 서버에서는 사용되지 않습니다.
- 탈퇴 회원은 API 접근이 제한되며, 작성자 표시에 `탈퇴한 사용자` 정책을 적용한 코드가 있습니다.
- 관리자 UI 표시만으로 권한을 보장하지 않으며 API의 관리자 검증을 기준으로 합니다.

## 6. 데이터 및 DB 연결

`core/database.py`는 SQLAlchemy ORM 세션과 작은 풀을, `core/db_connect.py`는 직접 SQL용 psycopg2 풀을 제공합니다.

- ORM 풀: 프로세스당 `pool_size=1`, `max_overflow=0`
- 직접 SQL 풀: `DB_POOL_MAX_CONNECTIONS` **1~4**, 기본 **2**
- 멀티 워커·Bot·크롤러 실행 시 **전체 PostgreSQL 연결 한도**를 합산합니다.
- 세션과 커서는 `finally`/컨텍스트 매니저로 반환해야 합니다.
- 스키마 변경은 [`database/sql/`](../database/README.md) 파일과 적용 이력을 확인합니다. ORM 자동 생성으로 운영 DB를 수정하지 않습니다.

## 7. 별도 작업

모임 예약 스케줄러는 웹 서버와 **별도 프로세스**입니다.

```powershell
uv run python -m backend.app.jobs.run_recruit_scheduler --once
# 주기 실행은 --once 제외, 운영 반영 전 대상 DB·기능 플래그 확인
```

취업 뉴스 수집·PostgreSQL 반영은 [`database/scripts/collect_career_news.py`](../database/README.md)를 참고합니다. 독립 크롤러만 실행한다고 서비스 DB가 자동 갱신되지는 않습니다.

## 8. 테스트

```powershell
# 저장소 루트, pytest가 설치된 환경
uv run --with pytest pytest backend/tests -q
# 특정 테스트 예시
uv run --with pytest pytest backend/tests/test_auth_flow.py -q
```

일부 테스트는 격리 DB 주소가 없으면 건너뛰거나 실패할 수 있습니다. **공용·운영 PostgreSQL을 테스트 초기화 대상으로 지정하면 안 됩니다.** 프론트의 실제 세션 쿠키·Discord 인증·운영 데이터는 별도 수동 검증이 필요합니다.

## 9. 베타 배포 체크

- [ ] `APP_ENV=production`, HTTPS, 정확한 `FRONTEND_ORIGINS`·`FRONTEND_URL`
- [ ] `020_member_withdrawal.sql`, `021_recruit_skills.sql` 등 필요한 마이그레이션 적용
- [ ] DB 연결 한도 및 동시 요청 점검
- [ ] 업로드 크기 제한·요청 속도 제한을 프록시에서 구성
- [ ] 개발 헤더 무시, Swagger 비공개, CSRF 위험 평가
- [ ] 실제 Discord 로그인/탈퇴, 권한, 관리자, 게시판/모임 회귀 테스트

상세 보안 조건: [베타 배포 보안 전제조건](../docs/BETA_SECURITY_DEPLOYMENT.md)

## 10. 문서 관리

새 API는 `routers` → `schemas` → `services` → `repositories` → SQL/테스트 순으로 검토합니다. 기능이 추가되면 엔드포인트, 인증 요구사항, DB 마이그레이션, 재현 테스트를 함께 업데이트합니다.
