# Issue #88 모임 수정 및 검증 결과

검증일: 2026-11-03 (Asia/Seoul). 브랜치: `feature/88-meetup-back`. 기준: 원격 fetch로 확인한 `origin/develop` (`73b8b70`).

## ① 수정 내용과 검증

| 기능 | 기존 문제 | 수정 내용 | 검증 결과 |
|---|---|---|---|
| 오류 메시지 | 원본 검증 문구와 상단 오류만 표시 | 모임 전용 한국어 메시지, validation loc를 폼 필드에 연결, 내부 오류 비노출, 공용 알림 재사용 | 유틸리티 테스트 통과. 실제 서버 오류 Toast는 로그인 환경 추가 확인 |
| 필수 입력 UX | 기본 validation bubble·alert로 분산 | noValidate, 인라인 오류·ARIA, 첫 오류로 스크롤·포커스, 수정 시 오류 해제 | 격리된 실제 컴포넌트에서 빈 제목 등록→제목 포커스, 입력 후 오류 해제 직접 확인 |
| 날짜/시간 UI | 입력 스타일과 시간대 처리 불일치 | 기본 날짜 선택기 접근성 유지, 보라색 스타일 통일, 최소 날짜·날짜 관계 검증, UTC→서울 수정값 변환 | 날짜 유틸리티 통과. 브라우저에서 24시간 전 마감 계산과 종료일 오류 포커스 확인 |
| 프로젝트 기술 선택 | 사전 API 미연결, 서버도 UnavailableSkillCatalog 사용 | DB 기술 사전·GET /api/recruits/skills·생성/수정 검증 연결, 필수/담당 기술 선택, 로딩·재시도 | 실제 일회용 PostgreSQL에서 마이그레이션 반복 적용·프로젝트 기술 저장·재조회 통과. 연결 DB 적용은 보류 |
| Discord 프로필 | 참여자 ID만 반환·회색 원만 렌더링 | 기존 members.nickname/profile_image_url을 일반·신규 모임 참여자에 매핑, 이미지 실패 시 기본 UI | SQLite에서 상세·별도 참여자 API·일반 참여자 조회 매핑 통과. 실제 Discord 이미지 화면은 미검증 |
| 댓글 | API와 상세 UI 연결 누락 | 목록·작성·답글·수정·삭제 연결, 서버 작성자 권한 유지, 성공 후 재조회, 실패 시 초안 보존 | 기존 서비스·HTTP 인증 테스트 통과. 실제 로그인 UI의 저장은 미검증 |
| 좋아요 | API 메서드·컴포넌트 핸들러 연결 누락 | 등록/취소 API, 서버 반환 숫자·상태로 상세/목록 갱신, 연타 차단 | 서비스·HTTP 테스트 통과. 실제 로그인 UI의 저장은 미검증 |
| 스크랩 | 상세 핸들러 연결 누락 | 등록/해제 API와 서버 상태 연결, 성공 알림 | 서비스·HTTP 테스트 통과. 실제 마이페이지 화면 동기화는 미검증 |
| 삭제 권한 | 함수 유무만으로 노출, 기존 모임 수정/삭제 서버 작성자 검사 누락 | 실제 로그인 회원 ID 전달, 작성자만 버튼 노출, 기존 모임 서버 작성자 검사, 접근성 확인 dialog | 비로그인/타인 삭제·수정 거절 테스트 통과. 실제 계정별 화면·모달 조작은 미검증 |
| 정기 스터디 | 신규 API에 불필요한 필드 전송, 초기 INSERT의 정기 일정 누락, 수정 일정 메타데이터 불일치 | 생성/수정 요청 필드 분리, 초기 정기 일정 저장, 변경된 전체 시작과 정기 첫 날짜/시간 동기화 | SQLite·실제 일회용 PostgreSQL 생성/수정/새 세션 재조회 통과. 신고된 실환경 500의 원본 traceback은 없어 원인 확정·해결 완료 판정 보류 |
| 게임 모집 상태 | 마감일을 화면 상태 판단에 사용하지 않음, 일반 정원을 마감과 혼용 | 마감일과 정원 충족을 구분하고 마감 우선, 기존 실제 참여 집계·행 잠금 유지, 일반 인원 조회값 우선 | 상태 우선순위·0명 유지 유틸리티와 참여/취소·정원 동시성 회귀 통과. 실화면 재진입은 추가 확인 |
| 기타 연결 | 로그인 ID 누락, 일반 요청에 신규 API 판별 필드 혼입, 공동구매에 숨겨진 일정 요구 | 앱→모임 로그인 ID 전달, 요청 필드 분리, 공동구매 일정 계약 정합성 보완, 수정 상세 필드 실제 저장 | 기존 API 회귀·전용 검증 통과 |

프로젝트·스터디의 모집 마감은 기존 서버 정책대로 **시작 24시간 전**이며 화면에서 자동 설정한다. 서버 권한과 업무 규칙은 우회하지 않았다. 프로그램 수정 화면에서 지원하지 않는 장소/스터디 메타정보·반복 요일 변경은 비활성화하고 지원 범위를 안내한다. 개설자 담당 기술은 수정 화면에 기존 선택을 표시하며, 기존 서버 정책에 없는 담당 신청 변경 API를 새로 만들지는 않았다.

## ② 변경 파일 목록

아래 경로는 저장소 루트 기준이다. 작업 시작부터 있던 `playmate-discord-bot/.env.example` 삭제는 건드리지 않았고 커밋에서 제외했다.

| 파일 | 역할 및 변경 이유 |
|---|---|
| `backend/app/models/member.py` | 기존 Discord 프로필 이미지 컬럼 ORM 매핑 |
| `backend/app/models/recruit_program.py` | DB 기술 사전 모델 |
| `backend/app/repositories/recruit.py` | 참여자 공개 프로필 일괄 조회 |
| `backend/app/repositories/recruit_program_repository.py` | 정기 초기 일정 저장·프로필 조회 |
| `backend/app/routers/recruit.py` | 공개 기술 목록 API 등록 |
| `backend/app/routers/recruit_program.py` | 실제 DB 기술 사전 주입 |
| `backend/app/schemas/recruit.py` | 공동구매 일정·서울 시간대·부분 수정 검증 |
| `backend/app/services/recruit.py` | 작성자 정보 응답·카테고리 상세 수정·단기 일정 검증 |
| `backend/app/services/recruit_dispatch_service.py` | 기존 모임 수정·삭제 작성자 인가 |
| `backend/app/services/recruit_member.py` | 일반 참여자 프로필 응답·기존 성능 print 제거 |
| `backend/app/services/recruit_program_service.py` | 정기 일정 수정 메타데이터 동기화 |
| `backend/app/services/recruit_skill_catalog.py` | DB 기술 목록 조회·ID 검증 공통화 |
| `backend/tests/recruit/test_issue88.py` | 정기 저장·프로필·기술·인가·공동구매/시간대 테스트 |
| `backend/tests/recruit/test_program_postgres.py` | 일회용 PostgreSQL 기술 마이그레이션·프로젝트·정기 저장 회귀 |
| `backend/tests/test_recruit_social.py` | 상세 작성자 응답에 맞는 fixture와 소유권 assertion 보강 |
| `database/sql/021_recruit_skills.sql` | 기존 학습 기술 코드에 대응하는 추가형 기술 사전 마이그레이션 |
| `docs/issue-88-meetup-review.md` | 검증 근거·제한·수동 점검·배포 전제 기록 |
| `frontend/src/App.jsx` | 로그인 회원 ID·관리자 여부를 모임 화면에 전달 |
| `frontend/src/components/meetup/MeetupFeedback.jsx` | 성공·오류 알림 및 키보드 접근성 확인 모달 |
| `frontend/src/components/meetup/MeetupMemberList.jsx` | 실제 프로필 이미지와 실패 대체 표시 |
| `frontend/src/components/meetup/MeetupSection.jsx` | 반응·댓글·삭제 확인·알림 연결 |
| `frontend/src/hooks/meetup/useMeetupEditor.js` | 요청 계약·필드 오류·스크롤/포커스·마감 자동 계산 |
| `frontend/src/hooks/meetup/useMeetups.js` | 댓글/스크랩 연결·서버 상태 갱신·중복 요청과 읽기 실패 처리 |
| `frontend/src/pages/meetup/MeetupDetailPage.jsx` | 작성자 버튼·로그인 상태·댓글 동작 연결 |
| `frontend/src/pages/meetup/MeetupEditorPage.jsx` | 기술 조회·인라인 오류·폼 접근성·날짜 입력 안내 |
| `frontend/src/services/meetupApi.js` | 기존 서버의 반응·댓글 및 신규 기술 조회 endpoint 연결 |
| `frontend/src/styles/meetup.css` | 날짜·오류·알림·확인창·모바일 스타일 |
| `frontend/src/utils/meetup.js` | 서울 시간대 수정값·모집 마감/정원 상태 |
| `frontend/src/utils/meetup.test.js` | 날짜·상태·요청 계약·오류 회귀 테스트 |
| `frontend/src/utils/meetupForm.js` | 폼 검증·안전한 오류 변환·허용 요청 필드 |

## ③ 테스트 결과

- 모임 중심 최종 검사: **170 passed**. SQLite/대역과 localhost 일회용 PostgreSQL 사용. 정원 마지막 자리 동시 신청·중복 요청·취소/대기·권한·생성/수정·기술 사전 반복 적용 포함.
- 범위를 확장한 백엔드 회귀: **445 passed, 4 failed, 1 skipped**. 이후 최종 서울 시간대/공백 수정 검증 보완은 모임 170건으로 다시 통과 확인.
- 실패 4건은 수정 전 `73b8b70`을 별도 임시 폴더에서 실행해 **같은 4건 실패**를 재현했다.
  - `test_auth_flow.py` 2건: 실제 앱의 `backend.app.routers.auth`와 테스트가 patch하는 `app.routers.auth`가 달라 인증 대역이 적용되지 않음. 가짜 OAuth code에 대해 502 반환.
  - `test_board_comment_avatar.py` 2건: 탈퇴자 조건이 추가된 SQL과 기존 SQL 문자열 assertion 불일치.
- PostgreSQL 외부 통합 모음 및 DB에 직접 접속하는 레거시 스크립트(`test_host`, `test_database`, `test_attendance_bonus`, `test_skill_accuracy`, `test_skill_xp`)는 최종 회귀 대상에서 제외. 최초 광범위 수집 시 후자 3건은 테스트 전용 localhost:1 연결 시간 초과로 수집 실패했으며 실제 DB 변경은 없었다.
- 프론트엔드: `node --test frontend/src/utils/meetup.test.js frontend/src/utils/scrapTime.test.js` → **14 passed**.
- 프론트엔드 빌드: `npm.cmd run build --prefix frontend` → 성공. 기존 단일 JS 청크 500kB 경고는 남음.
- `git diff --check` → 통과. 별도 lint/typecheck 스크립트·설정이 없어 해당 검사는 미실행.
- 현재 가상환경은 FastAPI 0.143 계열로 저장소 requirements의 0.115.14와 달랐다. 최종 서버 검사는 기존 런타임을 바꾸지 않고 임시 디렉터리에 FastAPI 0.115.14 / Starlette 0.46.2를 설치해 실행했다. 기본 최신 런타임에서는 기존 라우트 검사 1건이 `_IncludedRouter.path` 차이로 실패했음.
- 브라우저: 실제 `/meetup`은 로그인 화면까지만 확인. 별도 임시 서버에서 **동일 Editor 컴포넌트**를 띄워 빈 제목 포커스·오류 해제·마감 자동 계산·종료일 오류 포커스·390px 가로 넘침 없음을 확인했다. 이 임시 서버에는 데이터 저장 API가 없었으며 기술 목록은 빈 fixture였다. 따라서 실제 서비스 E2E나 기술 API UI 성공으로 주장하지 않는다.
- 테스트 컨테이너와 임시 UI 서버·브라우저 탭은 검증 후 종료했다.

최종 모임 서버 검사 명령(환경값은 일회용 DB에만 지정):

```powershell
# PYTHONPATH: 임시 FastAPI 0.115.14 런타임
# RUN_RECRUIT_POSTGRES_TESTS=1
# RECRUIT_TEST_DATABASE_URL: 일회용 localhost PostgreSQL
.venv/Scripts/python.exe -m pytest backend/tests/recruit backend/tests/test_recruit_social.py backend/tests/test_recruit_join_member.py backend/tests/test_join_deadline.py -q
```

## ④ 남은 문제와 배포 전제

1. **연결 DB에 `recruit_skills`가 아직 없다.** 관련 스키마 존재 여부만 READ ONLY 트랜잭션으로 확인했다. `members.nickname/profile_image_url` 및 신규 모임 테이블은 존재한다. 운영 스키마·데이터는 변경하지 않았다. 배포 절차에서 `database/sql/021_recruit_skills.sql` 적용 및 GET /api/recruits/skills 확인이 필요하다. 미적용 상태에서는 친절한 오류·재시도가 표시되고 프로젝트 기술 선택은 사용할 수 없다.
2. **신고된 정기 스터디 실환경 500의 원본 traceback을 확보하지 못했다.** 확인 가능한 요청 계약·정기 저장 경로·시간대 문제는 수정하고 격리 실제 PostgreSQL에서 생성/수정/재조회를 통과했다. 연결 DB의 recruits CHECK 제약조건은 없었으므로 '제약조건이 500의 확정 원인'이라고 판단하지 않는다. 실제 실패 요청/서버 오류 로그와 비교한 최종 재현 검증이 남았다.
3. **실제 로그인 세션의 전체 화면 E2E가 남았다.** 데이터 변경 금지를 지키기 위해 실제 모임 생성/참여/삭제/댓글/좋아요/스크랩을 실행하지 않았다. 실제 Discord 이미지 접근·Kakao 지도·마이페이지 스크랩·여러 계정 권한 화면은 별도 테스트 환경에서 확인해야 한다.
4. 전체 백엔드 회귀에는 위에서 기준 커밋에서도 재현한 4건 실패가 남는다. 관련 기능 코드를 무관하게 변경하거나 기존 테스트를 삭제해 숨기지 않았다.

## ⑤ 직접 확인할 체크리스트

아래 저장 테스트는 테스트 계정과 별도 테스트 환경에서 진행한다.

- [ ] 빈 제목으로 등록 → 제목으로 자동 이동·포커스·오류 표시. 제목을 입력하면 오류 해제.
- [ ] 인원/요일/시간/종료일/스터디 주제/필수 기술을 각각 누락 → 해당 첫 오류 입력으로 이동.
- [ ] 종료일을 시작일 이전으로 지정 → 종료 필드에 안내. 프로젝트·스터디 시작일 선택 → 마감이 정확히 24시간 전으로 설정.
- [ ] 단기/정기 스터디 생성 → 상세·목록 표시, 새로고침, 수정 저장 후 일정·반복 요일 유지. 500 발생 시 요청과 서버 traceback 수집.
- [ ] 기술 사전 마이그레이션 후 프로젝트 필수/담당 기술 선택 → 저장·상세·수정 화면에서 이름과 선택값 유지. 목록 조회 실패 시 재시도 가능.
- [ ] 운동/게임/공동구매 생성 → 신규 프로그램 스키마 오류 없이 저장. 공동구매에 숨겨진 시작/종료 입력을 요구하지 않음.
- [ ] 참여/취소 → 확정·대기 상태와 인원 변경. 새로고침·목록 복귀·재진입 후 동일 인원. 여러 계정 동시 신청 시 정원 초과 없음.
- [ ] 게임 정원 충족/자리 있음/마감 경과 → 각각 정원 충족/모집중/모집 마감. 목록과 상세가 일치.
- [ ] 실제 Discord 로그인 참여자 → 올바른 닉네임·이미지. 깨진 이미지나 미등록 이미지 → 대체 프로필.
- [ ] 좋아요 두 번 → 등록·취소와 숫자 복구, 새로고침 후 상태 유지. 카드 목록 숫자 갱신.
- [ ] 스크랩 등록/해제 → 상세와 마이페이지에 반영, 새로고침 후 유지.
- [ ] 댓글/답글 작성·수정·삭제 → 즉시 갱신·새로고침 후 유지. 타인 댓글은 수정·삭제 불가. 실패 시 초안 유지.
- [ ] 작성자만 수정/삭제 버튼 노출. 다른 계정·비로그인 API 요청은 거절. 확인 모달에서 취소/Escape → 데이터 변경 없음. 삭제 성공 → 목록과 알림.
- [ ] 오류 API 상황 → 원본 서버 문구 대신 한국어 알림, 같은 알림이 중복으로 쌓이지 않음.
- [ ] 모바일·긴 제목/설명·키보드 조작 → 가로 넘침·버튼 겹침 없음. 뒤로 가기/새로고침 후 URL과 화면 일치.

## ⑥ 준비 상태

**NOT READY — 베타 오픈의 최종 승인 기준.** 수정본의 모임 자동 테스트와 빌드는 통과했지만, 기술 사전의 연결 DB 적용 및 신고된 실환경 500 검증이 남아 베타 준비 완료로 판정하지 않는다.

- 작업 브랜치: `feature/88-meetup-back`.
- 코드·테스트·보고서는 이 브랜치에만 커밋. 최종 커밋 SHA와 파일 수는 최종 응답에 제공.
- Push: 미실행. PR: 미생성. Merge: 미실행.
- 기존 봇 `.env.example` 삭제는 그대로 보존하고 커밋에서 제외.
