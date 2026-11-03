# 베타 운영 배포 보안 전제조건 (#82)

베타 서버를 열기 전에 아래 항목을 배포 담당자가 직접 확인한다.
코드는 `APP_ENV` 값 하나로 개발/운영 동작을 나누므로, **운영 서버의 `APP_ENV` 설정이 가장 중요하다.**

## 1. `APP_ENV`에 따른 동작

| 항목 | `development`·`test` | 그 외 모든 값·미설정(운영) |
|---|---|---|
| 세션 쿠키 `Secure` | 꺼짐(로컬 HTTP 로그인 가능) | **켜짐(HTTPS에서만 쿠키 전송)** |
| 세션 쿠키 `HttpOnly`·`SameSite=Lax` | 켜짐 | 켜짐 |
| `X-Dev-Member-ID` 개발용 헤더 | 세션이 없을 때만 허용 | **무시(401)** |
| `/docs`, `/redoc`, `/openapi.json` | 제공 | **404** |
| `/health/db` 응답 | `{"status": "ok"}` | `{"status": "ok"}` |
| 서버 내부 `RuntimeError` 응답 | 고정 문구 503 | 고정 문구 503 |

- 운영 서버는 `APP_ENV=production`을 명시한다. 로컬 `.env`를 그대로 복사하면 `development`가 되어
  **누구나 `X-Dev-Member-ID` 헤더로 다른 회원(관리자 포함)으로 위장할 수 있다.**
- 오타·`prod`·`staging` 같은 값은 모두 운영으로 처리된다(안전한 기본값).

## 2. HTTPS 전제조건

운영에서는 세션 쿠키에 `Secure`가 붙으므로 **HTTPS가 아니면 로그인이 유지되지 않는다.**

- [ ] 사용자가 접속하는 프론트 주소와 API 주소가 모두 `https://`이다.
- [ ] 리버스 프록시(또는 호스팅 서비스)에서 `http://` 요청을 `https://`로 리다이렉트한다.
      리다이렉트·HSTS는 실제 프록시 구성을 확정한 뒤 프록시에서 설정한다(앱 코드에는 추가하지 않았다).
- [ ] `DISCORD_REDIRECT_URI`가 `https://<운영 도메인>/auth/discord/callback`이며 Discord 개발자 포털에도 같은 값이 등록되어 있다.
- [ ] `FRONTEND_URL`이 운영 프론트 `https://` 주소이다(미설정 시 `http://localhost:5173`으로 이동한다).
- [ ] `FRONTEND_ORIGINS`에는 운영 프론트 `https://` origin만 쉼표로 적는다. **`*`는 절대 사용하지 않는다**
      (쿠키 인증과 함께 쓰면 모든 사이트가 로그인 사용자 권한으로 API 응답을 읽을 수 있다).
- [ ] 프록시가 TLS를 종료하고 앱에는 HTTP로 전달하는 구조여도 쿠키 `Secure` 동작에는 문제가 없다
      (브라우저↔프록시 구간이 HTTPS이면 된다).

## 3. 비밀값·빌드 환경

- [ ] 운영용 `SESSION_SECRET_KEY`는 로컬과 다른 새 값을 사용한다(32자 이상 무작위).
- [ ] 프론트 운영 빌드 환경에는 `VITE_DEV_MEMBER_ID`를 두지 않는다.
      `VITE_` 값은 모두 공개 JS 번들에 포함되므로 토큰·비밀번호를 넣지 않는다.
      (코드상 운영 빌드는 개발용 헤더를 보내지 않지만, 값 자체를 두지 않는 것이 안전하다.)
- [ ] 공용 DB는 신뢰 IP(허용 목록)에서만 접속되도록 설정한다.
- [ ] 운영 Discord OAuth 클라이언트 ID·시크릿이 운영 값이며 저장소·프론트 번들에 포함되지 않았다.
- [ ] 백엔드 의존성은 `uv.lock` 기준(`uv sync`)으로 설치한다. `backend/requirements.txt`는 FastAPI 등 버전이
      다르고 `httpx`가 빠져 있어 운영 설치에 사용하지 않는다(정리는 별도 이슈).

## 3-1. 프록시·실행 설정 (앱 코드에 없음, 배포 환경에서 설정)

- [ ] 리버스 프록시에서 요청 본문 크기를 제한한다(예: 일반 API 1MB, 게시글 이미지 업로드 16MB 내외).
      앱은 이미지 개수(3개)·크기(5MB)를 검사하지만 그 전에 본문 전체를 받으므로 프록시 제한이 필요하다.
- [ ] 로그인·댓글·좋아요·신고 등 API에 IP·계정 기준 요청 속도 제한을 둔다(앱에는 속도 제한이 없다).
- [ ] DB 연결 수를 맞춘다. 프로세스(worker)마다 psycopg2 풀 최대 `DB_POOL_MAX_CONNECTIONS`(1~4, 기본 2)와
      SQLAlchemy 풀 1개를 쓴다. `worker 수 × (DB_POOL_MAX_CONNECTIONS + 1)`이 DB 최대 연결 수와
      다른 서비스(디스코드 봇·수집기) 연결을 합쳐 한도를 넘지 않게 한다.
      모임 API도 요청마다 인증 조회로 psycopg2 풀을 잠깐 사용한다.

## 4. 운영 DB 마이그레이션 (배포 전 필수 확인)

아래 마이그레이션은 앱 코드가 전제로 사용한다. **운영 DB 백업 후** 적용 여부를 배포 담당자가 직접 확인한다.
이 문서 작성 시점에는 운영 DB 적용 여부를 확인하지 않았다.

- [ ] `database/sql/020_member_withdrawal.sql` 적용 여부 확인 (`members.member_status` 컬럼, 기본값 `ACTIVE`)
      로그인 인증(`core/auth.py`)이 `member_status = 'ACTIVE'`를 조건으로 사용하므로,
      **미적용 시 로그인한 회원의 모든 인증 요청이 실패한다.**
- [ ] `database/sql/021_recruit_skills.sql` 적용 여부 확인 (프로젝트 모임 기술 사전)
      미적용 시 프로젝트 모임의 기술 선택을 사용할 수 없다.

## 5. 배포 직후 확인 (운영 주소에서)

```bash
# 개발용 헤더만으로는 인증되지 않아야 한다 → 401
curl -s -o /dev/null -w "%{http_code}\n" -H "X-Dev-Member-ID: 1" https://<운영 API>/api/boards
# API 문서는 비공개 → 404
curl -s -o /dev/null -w "%{http_code}\n" https://<운영 API>/docs
# DB 상태는 내부 정보 없이 {"status":"ok"}
curl -s https://<운영 API>/health/db
# 로그인 시작 응답의 쿠키에 Secure; HttpOnly; SameSite=Lax 포함
curl -s -D - -o /dev/null https://<운영 API>/auth/discord/login | grep -i set-cookie
# 비로그인 상태의 기존 모임 수정·삭제 거부 → 401 (테스트용 모임 ID 사용, 거부되므로 데이터는 바뀌지 않는다)
curl -s -o /dev/null -w "%{http_code}\n" -X PATCH -H "Content-Type: application/json" \
  -d '{"title":"권한 확인"}' https://<운영 API>/api/recruits/<테스트 모임 ID>
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE https://<운영 API>/api/recruits/<테스트 모임 ID>
```

```bash
# 활성 회원 전용 정책: 비로그인 모임 조회 → 401
curl -s -o /dev/null -w "%{http_code}\n" https://<운영 API>/api/recruits
# 업로드 이미지 응답에 nosniff 포함
curl -s -D - -o /dev/null https://<운영 API>/uploads/<기존 이미지 경로> | grep -i x-content-type-options
```

- [ ] 테스트 계정 2개로 확인: 다른 회원이 만든 기존 모임 수정·삭제 → 403, 작성자 본인 → 성공
- [ ] 실제 Discord 로그인 → 회원가입 → `/auth/me` → 로그아웃 흐름을 테스트 계정으로 확인
- [ ] 테스트 계정 탈퇴 후, 탈퇴 전에 복사해 둔 다른 브라우저 세션으로 모임 조회·댓글 → 401
- [ ] 실제 PostgreSQL 통합 테스트를 **일회용 로컬 DB**에서 실행했다
      (`PLAYMATE_BOARD_TEST_DB_URL`, `PLAYMATE_LOCAL_TEST_DB_URL`, `RECRUIT_TEST_DATABASE_URL` 등. 공용 DB 금지)

## 6. 해결된 항목 (운영 환경 검증은 별도 필요)

아래는 코드와 격리 자동 테스트로 확인했으며, **실제 운영 환경에서는 아직 검증하지 않았다.**

- **모임 API 인증(F1)**: 세션의 member_id만 믿던 모임 생성·좋아요·스크랩·댓글 경로가 공통 인증
  (회원 존재·Discord ID 일치·`member_status = 'ACTIVE'`)을 사용한다. 탈퇴 회원의 남은 세션은 401.
- **모임 조회 인증(F2)**: 폐쇄형 서비스 정책에 따라 모임 목록·상세·참여자·인원·댓글·기술 사전 조회도
  가입을 마친 활성 회원만 가능하다(비로그인·가입 미완료·탈퇴 401).
  자동 테스트: `backend/tests/recruit/test_meetup_auth_security.py`(실제 라우트·실제 인증 함수·격리 SQLite).
- **닉네임 정책(F3)**: 회원가입·마이페이지 변경 모두 2~20자, 예약어(관리자·운영자·익명·탈퇴한 사용자·admin 등) 거부.
  중복은 DB 고유 제약으로 409.
- **외부 링크(F6)**: 모임 `purchase_url`은 생성·수정 모두 http·https 주소만 허용(javascript·data·file 등 422).
- **업로드 응답**: `/uploads` 응답에 `X-Content-Type-Options: nosniff`.
- **OAuth 테스트 안전성**: `test_auth_flow.py`가 실제 앱 모듈을 대역으로 바꾸고 실제 네트워크 전송을 막는다.
- **테스트 DB 안전성**: PostgreSQL 테스트는 로컬·이름에 test가 포함된 전용 DB 주소가 있을 때만 접속한다.

- **Legacy 모임 PATCH/DELETE 작성자 권한 검사 누락(Critical)** → PR #90에서 수정됨.
  `RecruitDispatchService.require_legacy_owner`가 로그인(401)·회원 존재(403)·작성자 일치(403)를 확인한다.
  - 자동 테스트(`backend/tests/recruit/test_legacy_owner_permissions.py`, 격리 SQLite·가짜 인증)로
    비로그인 401, 다른 회원·관리자 403, 거부 시 데이터 불변, 작성자 수정·삭제 성공을 확인했다.
  - **실제 운영 환경(실제 로그인 세션·운영 DB)에서는 아직 검증하지 않았다.** 5번의 확인 절차로 검증한다.
  - 현재 정책상 관리자(ADMIN)도 다른 회원의 기존 모임을 수정·삭제할 수 없다. 관리자 조치가 필요하면 별도 정책 결정이 필요하다.

## 7. 아직 남은 위험 (별도 이슈)

- CSRF는 `SameSite=Lax`에만 의존(Origin 검사 미들웨어 미도입)
- 세션 14일 유지·로그아웃 시 서버 측 무효화 없음(서명 쿠키 방식. 탈퇴·비활성 회원은 요청마다 DB로 차단됨)
- `/health/db`는 인증 없이 DB 연결을 사용(요청 제한은 프록시에서 검토)
- 업로드: 요청 크기 제한은 프록시에 의존, 이미지 메타데이터(EXIF) 미제거, 삭제·숨김 글의 이미지가 주소로 계속 접근 가능
- 회원 과정·기수는 가입 시 본인 입력값(검증 없음, 기수 상한 없음)이라 과정 게시판 쓰기 권한이 자기 신고에 의존
- 일반 게시판·모임 목록 일부는 개수 제한(페이지네이션) 없이 전체를 반환
- 관리자도 다른 회원의 기존 모임을 수정·삭제할 수 없음(정책 결정 필요)
- 백엔드 의존성 파일 이원화(`uv.lock` vs `backend/requirements.txt`)
- 실제 PostgreSQL 통합 테스트·실제 Discord 로그인은 이 브랜치에서 실행하지 않았다(위 5번 수동 확인 필요)
