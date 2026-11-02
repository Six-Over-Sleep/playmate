# 모임 백엔드 구현 결과와 연결 전 점검

2026-10-26 / `feature/33-meetup-backend-function-fix`

## 기준 코드

처음에는 작업 브랜치가 오래된 `f22aa52`에 있어 XP/마이페이지 파일이 없었습니다. 사용자가 받은 최신 develop `3de523e`에 해당 파일이 있음을 재확인했고, **동일 feature 브랜치만 fast-forward**했습니다. 새 커밋을 만들거나 develop을 수정하지 않았습니다.

최신 코드에는 공통 XP·마이페이지가 있습니다. 다만 현재 XP 유형은 출석/게시글/댓글/대댓글이며, 모임 인정·주간 인증·완료·원 지급 참조 회수를 지원하지 않습니다. 마이페이지에도 신청서에 불러올 커리어 6항목 저장/조회 API는 없습니다. 따라서 기존 서비스를 복제하지 않고 모임 연결 인터페이스를 준비했습니다.

## 구현한 부분

- 프로젝트/스터디 생성 규칙, 서버 권한에 따른 인원 차이와 사용자 개설자 자동 참여.
- 프로젝트 기술별 자리 확보, 다중 기술, 확정/대기 접수와 취소 재심사.
- 스터디 선착순 대기/승격, 마감 이후 신청/충원 차단.
- 직접 입력 6항목 복사본 저장, nonempty career_item_ids 거절, 공개 응답에서 신청 자료 제외.
- 전날 팀장 선정, 희망자 우선/관리자 모임 예외, 이탈 시 신청순 승계.
- 최대 2회·각 14일 연장, 요청 키/본문 비교 재시도, 일정 버전 변경.
- 최종 미달의 예외 시작/취소, 예정 시각 최소 인원 재검사, CANCELED/ABORTED/COMPLETED 구분.
- 타인 첫 신청 이후 핵심 조건 변경 금지, 개설자 부분 수정과 권한 검사.
- 커리큘럼 버전 충돌과 편집 정책 주입, 활동·결과물·후기 저장.
- 개인 인정 정책/XP 지급·회수 예약 인터페이스, 원 지급 참조, 실패 재시도와 중복 방지.
- 별도 예약 실행 함수, 디스코드 전달 outbox, 구 일정 요청 폐기.
- 확정자만 기존 recruit_members JOINED에 반영. 기존 회원 닉네임·좋아요·스크랩 테이블 재사용.
- 기존 KST naive 일정과 신규 UTC 일정 변환, 논리 삭제된 게시글 조회/예약 처리 제외.

## 실제 실행에 아직 연결하지 않은 부분

후속 ‘2번 실제 API 연결’ 요청에 따라 **main 앱에 기존/신규 분기와 중복되지 않는 확장 주소를 등록했습니다.** 기본 활성화 설정은 false이며 공유 DB 배포나 `.env` 변경은 실행하지 않았습니다. 기존 임시 인증/권한의 전면 변경, 실제 로그인 검증, 봇과 예약 처리의 책임 분담은 다음 단계입니다. 상세 결과는 `docs/MEETUP_API_CONNECTION.md`를 참고합니다.

공유 DB 마이그레이션은 실행하지 않았습니다. 공통 기술 ID/이름 조회 어댑터, 관리자 생성 모임의 커리큘럼 편집 기준, 개인 참여/완료 판정 주체·정책, 모임 XP 유형/한도/회수 계약도 아직 실제 제공자가 필요합니다. 사용자 생성 스터디는 별도 연결 대기로 막지 않고 개설자에게 저장을 허용합니다. 미연결 기능을 가짜 성공으로 처리하지 않습니다.

기존 운동/게임/공동구매의 `-1` 경로는 협의 보류 범위이므로 그대로입니다. **전체 종류의 3회 이탈 제한이 운영에 이미 적용되었다고 말할 수 없습니다.** 신규 생성 시 자동 참여로 제한을 우회하는 것은 새 서비스에서 차단합니다. 기존 확정/대기는 제한 이후에도 보존합니다.

스토리지 업로드·마이페이지 커리어 불러오기·디스코드 봇 구현·기술 게임·보상 정책/레벨 계산은 이번 코드에 중복 구현하지 않았습니다.

## 파일별 역할

모든 경로의 루트는 `C:/dev/project/playmate/`입니다. 기존 파일을 덮어쓰지 않고 아래 파일을 추가했습니다.

| 파일 | 역할 |
|---|---|
| backend/app/domain/recruit_program.py | DB/시계에 의존하지 않는 신청·대기·팀장·일정·상태 규칙 |
| backend/app/domain/__init__.py | 도메인 패키지 초기화 |
| backend/app/models/recruit_program.py | 프로그램·신청·이탈·커리큘럼·활동·인정·전달·재시도 모델 |
| backend/app/schemas/recruit_program.py | 입력 필드·시간대·종류별 필수값 검증 |
| backend/app/repositories/recruit_program_repository.py | ORM 접근·행 잠금·저장·기존 구조 동기화·일괄 집계 |
| backend/app/services/recruit_program_service.py | 생성·조회·신청·수정·결정·커리큘럼·활동·예약 유스케이스 |
| backend/app/services/recruit_reward_service.py | 개인 인정·지급/회수 예약·외부 전달 재시도 |
| backend/app/integrations/recruit_events.py | 인정 정책·공통 XP/외부 전달 계약 |
| backend/app/integrations/__init__.py | 연동 패키지 초기화 |
| backend/app/routers/recruit_program.py | 격리 API 연결, 공통 로그인 사용, 업무 오류 변환 |
| backend/app/main.py | 중복되지 않는 모임 확장 주소 등록 |
| backend/app/routers/recruit.py | 기존 기본 주소에서 기존/신규 모임 분기 |
| backend/app/core/recruit_config.py | 명시적 신규 기능 활성화 설정 |
| backend/app/schemas/recruit_dispatch.py | 기존/신규 생성 계약 구분, 검증 실패 fallback 방지 |
| backend/app/services/recruit_dispatch_service.py | 기존 동작 보존·신규 요청 연결·기능 중지 시 우회 차단 |
| backend/app/jobs/process_recruit_jobs.py | 명시적으로 구성한 서비스의 단회 예약 실행 |
| backend/app/jobs/__init__.py | 예약 패키지 초기화 |
| backend/tests/recruit/conftest.py | 메모리 DB·기술 사전·정책 대역 |
| backend/tests/recruit/test_program_domain.py | 시간 경계·기술 배정·팀장·연장·예외 시작·중도 종료 |
| backend/tests/recruit/test_program_service.py | 저장·권한·대기·이탈 제한·롤백·커리큘럼·활동 |
| backend/tests/recruit/test_program_api.py | HTTP 계약·로그인 주입·권한·입력 오류 |
| backend/tests/recruit/test_program_contract.py | 목록 조회 수·기존 응답·마이페이지 호환·DDL 대조 |
| backend/tests/recruit/test_program_rewards.py | 개인별 인정·중복·외부 실패/재시도·원 지급 회수 |
| backend/tests/recruit/test_program_postgres.py | 명시적 전용 DB에서 마지막 자리 동시 신청 검증 |
| backend/tests/recruit/manual_api.py | 실제 DB/OAuth와 분리된 수동 Swagger 서버 |
| backend/tests/recruit/test_manual_api.py | 수동 서버의 회원 전환·대기·승격·가상 시간 검증 |
| backend/tests/recruit/test_runtime_api.py | 실제 main 앱 경로에서 기존/신규 호환·권한·설정 검사 |
| database/sql/012_recruit_programs.sql | 기존 데이터 변경 없는 새 테이블 9개 DDL |
| docs/MEETUP_API_CONTRACT.md | 소희 연결용 경로·필드·예시·지원 범위·미연결 기능 |
| docs/MEETUP_BACKEND_IMPLEMENTATION.md | 이 구현 결과와 검증 범위 |
| docs/MEETUP_MANUAL_API_TEST.md | 사용자가 직접 누르는 Swagger 테스트 순서 |
| docs/MEETUP_PROMPT_AUDIT.md | 개발 프롬프트 대조 결과와 보완·보류 항목 |
| docs/MEETUP_API_CONNECTION.md | 2단계 API 연결 결과·실제 활성화 보류 사유 |

## 최초 구현 당시 검증과 한계

```powershell
& .\.venv\Scripts\python.exe -m pytest backend/tests/recruit backend/tests/test_join_deadline.py backend/tests/test_recruit_social.py backend/tests/test_board_api.py -q
```

신규 모임 규칙/저장/API와 기존 모임 마감·소셜·게시판 회귀를 검증했습니다. 실제 로그인 대신 명시적 인증 대역을 사용했고, 기본 DB는 메모리 SQLite입니다. 마이그레이션은 PostgreSQL DDL 생성 결과와 파일 내용을 대조했으며 실제 적용 검증과는 구분합니다.

전용 PostgreSQL URL이 없어 실제 행 잠금 테스트는 스킵했습니다. 로컬 Docker 엔진도 실행 중이 아니었습니다. 실제 DB 잠금/격리 수준·공유 DB DDL 적용·실제 OAuth·프론트 연결·스토리지·봇·XP 지급은 검증 완료가 아닙니다. 최종 테스트 수는 작업 완료 메시지에 기록합니다.

Windows 샌드박스에서 asyncio의 로컬 socketpair 생성이 정지해 격리 API 테스트와 formatter는 권한을 조정해 실행했습니다. 외부 OAuth/공유 DB를 호출하지 않았습니다. 기존 backend/requirements.txt의 누락 설치분 psycopg[binary]를 가상환경에 설치했고, 이번 파일만 Black/4칸 들여쓰기로 정리했습니다. 프로젝트 의존성 파일이나 다른 담당자 파일은 별도로 수정하지 않았습니다.

성능 수치 개선을 주장하는 작업이 아니므로 실제 HTTP 응답 시간 개선율은 측정/보고하지 않았습니다. 목록 모임 수가 늘어도 조회 횟수가 늘지 않는 조건만 격리 테스트로 검증했습니다.

커밋·푸시·PR·병합은 실행하지 않았습니다. 개인 .env와 실제 DB 데이터도 변경하지 않았습니다.

## #76 상태 변경 전용 예약 실행 (2026-11-02)

프로젝트 루트에서 별도 터미널로 실행합니다. API 서버와 봇은 기존대로 실행하며,
이 명령을 API worker 시작 이벤트에 등록하지 않습니다.

```powershell
cd C:\dev\project\playmate
& .\.venv\Scripts\python.exe -m backend.app.jobs.run_recruit_scheduler --once
# 한 주기 확인 후 계속 실행하려면 --once를 제외합니다.
& .\.venv\Scripts\python.exe -m backend.app.jobs.run_recruit_scheduler
```

루트 `.env`의 기존 DB/OAuth 설정을 재사용합니다. 공통 설정 모듈이 OAuth 설정도
필수로 요구하는 기존 구조는 변경하지 않았습니다. 비밀값을 로그에 출력하지 않습니다.
아래 값은 예시이며 이번 작업에서 개인 `.env`를 변경하지 않습니다.

```ini
ENABLE_RECRUIT_PROGRAMS=true
RECRUIT_SCHEDULER_INTERVAL_SECONDS=60
RECRUIT_SCHEDULER_RETRY_SECONDS=30
```

주기와 재시도 간격은 양의 정수 초입니다. 잘못된 설정은 실행 오류로 종료합니다.
시작 직후 한 주기를 실행하고, 정상 주기는 기본 60초, 실패 주기는 기본 30초 후
재실행합니다. 실제 상태 반영에는 실행 주기와 DB 대기 시간이 추가될 수 있습니다.
`--once`는 실패가 하나라도 있으면 종료 코드 1, 성공하면 0을 반환합니다.
반복 실행은 `Ctrl+C` 또는 SIGTERM으로 종료하며 현재 주기 완료 후 자원을 반환합니다.
종료 요청은 대기를 깨우지만 진행 중 DB 호출을 강제 중단하지는 않습니다.

한 모임의 실패는 해당 트랜잭션만 롤백하고 다음 모임을 처리합니다. 실패한 모임은
다음 주기에 다시 조회합니다. 대상 조회/연결 장애는 새 세션으로 재시도합니다.
오류 로그에는 모임 ID와 예외 종류만 기록하므로 원문 DB 오류·개인 자료가 노출되지 않습니다.
정상 로그의 processed는 이번 주기에 처리한 모임 수이며 중복 없는 전환 횟수는 아닙니다.

일정이 연장되거나 두 실행기가 같은 대상을 읽으면 행 잠금 뒤 최신 일정·상태를
확인합니다. 일정 버전별 이벤트 키로 중복 기록을 막습니다. 재시작하면 지난 대상도
처리하며, 종료 시각까지 지난 정상 모임은 운영 종료 상태로 따라잡습니다.
운영 종료는 개인별 완료 인정이나 XP 지급을 의미하지 않습니다.

실행기는 상태와 기존 Outbox 사건만 저장합니다. `process_once`나 Outbox 전송기를
호출하지 않으므로 XP 지급·회수, 디스코드 전송은 수행하지 않습니다.
기존 XP/봇 기능을 삭제하거나 비활성화한 것은 아닙니다.

### 운영 설정과 담당자 전달

- 실행 진입점 구현과 로컬 검증까지 수행합니다. 서버 서비스·작업 스케줄러 등록,
  자동 시작·재시작 정책은 이번에 적용하지 않았습니다. 터미널 종료 시 반복 실행도 끝납니다.
- 봇 담당자: `playmate-discord-bot/repositories/meeting_repository.py`의
  `list_provisionable_recruits`는 마감과 게시글 삭제 여부로 채널 생성 대상을 찾고
  `recruit_programs.lifecycle_status`의 취소 여부를 검사하지 않습니다.
  스터디 인원 미달 취소와 채널 생성의 경합, 연장 후 이미 생성된 채널 처리를 확인해야 합니다.
  기존 봇의 생성 이력/선점 처리를 재사용하고 채널 생성기를 추가로 만들지 않습니다.
- XP 담당자: `backend/app/services/meetup_xp_service.py`의 직접 SQL을 공통 책임과
  Repository 경계에 맞춰 정리할 필요가 있습니다. 기존 승인/회수 API는 유지했습니다.
  `recruit_reward_service.py`의 Outbox 지급과 직접 승인 경로는 키가 다르므로 두 경로를
  함께 연결하기 전에 활동 단위 중복 지급 방지 계약을 확인해야 합니다.
  이번 예약 실행은 어느 경로에도 지급을 요청하지 않습니다. XP 내부 동시성·원장 검증은
  이번 상태 변경 검증에 포함하지 않습니다.
- 소희님: 정상 종료 후 후기 버튼은 `permissions.can_write_review`를 사용합니다.
  기존 진행 중 활동 버튼의 `can_write_activity` 의미는 유지합니다.

### 재현 가능한 격리 검증

```powershell
$env:RUN_RECRUIT_POSTGRES_TESTS='1'
# 공유 DB가 아닌 전용 로컬 PostgreSQL URL로 설정합니다.
$env:RECRUIT_TEST_DATABASE_URL='<전용 테스트 PostgreSQL URL>'
& .\.venv\Scripts\python.exe -m pytest backend/tests/recruit -q
```

PostgreSQL 테스트는 UUID 스키마를 생성해 현재 `012_recruit_programs.sql`을 적용하고
종료 시 해당 스키마만 삭제합니다. 실제 OAuth·프론트 통합·운영 상시 실행·XP 지급·봇
외부 전송을 검증한 것은 아닙니다. 범위 밖 옛 회원/Router 테스트는 별도로 보고합니다.

2026-11-02 최종 결과: `backend/tests/recruit`와 `test_join_deadline.py`를 함께
실행해 100개 통과, 스킵 0개입니다. 별도 임시 PostgreSQL 16 컨테이너에서 DDL,
동시 신청, 두 예약 실행기, 실제 별도 Python 프로세스의 `--once` 반복 실행과
잘못된 설정의 종료 코드까지 검증했습니다. 전용 컨테이너는 검증 후 정리합니다.
CLI 단독 첫 검증에서 시간 초과가 한 번 발생했으나 재실행 및 최종 전체 실행은 통과했습니다.

최초 확인 시 `backend/tests/test_recruit_join_member.py`는 8개 통과, 3개 실패였습니다.
이후 사용자 요청으로 이 테스트 파일도 수정 범위에 추가했습니다. 기본 회원 -1 기대를
회원 ID 필수 검증으로 교체하고, 옛 Router 직접 호출은 실제 HTTP Router·Dispatch·
인증 연결로 바꿨습니다. DB 경계만 대역을 사용해 로그인 회원 ID/Discord ID 확인,
참여·취소로 회원 ID 전달, 비로그인 요청의 401 및 저장 미호출을 검증합니다.
실제 OAuth나 실제 DB 인증을 검증한 것은 아닙니다.
수정한 회원 테스트와 `test_runtime_api.py`를 함께 실행해 27개가 통과했습니다.
앞서 남았던 실패 3개는 해소됐으며, 저장소 전체 테스트 통과를 의미하지는 않습니다.

### 1차 모임 조회 반복 제거 (통합 응답 이전)

1차 변경에서 상세의 모임·게시글·설정 재조회를 줄였습니다. 이후 아래 통합 응답
구현으로 대체했습니다. 쓰기에 필요한 기존 전체 이력 조회와 행 잠금은 유지합니다.
수정·연장 응답도 `detail_context`로 부가 정보를 한 번에 읽습니다.

참여자 조회는 확정자의 표시 필드·담당 기술·닉네임만 한 번에 읽습니다.
대기자/취소자의 커리어 JSON을 적재하지 않습니다. 인원 조회는 신청서를 복원하지 않고
DB 집계로 확정·대기 수를 구합니다. 기존 응답 필드, 익명 조회, 회원 확인,
미존재/삭제 모임의 404 처리를 유지했습니다.

같은 격리 SQLite 데이터와 새 요청에 준하는 세션 정리 조건에서 측정한 SELECT 수:
- 목록: 6 → 6회 (모임 1개/6개에서도 일정)
- 상세: 9 → 6회
- 참여자: 5 → 3회
- 인원: 4 → 3회

수치는 Dispatch 분기를 포함하되 공통 로그인 인증 DB와 테이블 존재 확인을 제외합니다.
원격 DB 응답 시간이나 개선율을 측정한 결과가 아닙니다. 인증 확인, 쓰기 잠금,
DB 연결 풀은 제거하거나 완화하지 않았습니다. 프론트의 중복 HTTP 요청은 별도 수정이
필요하며 이번 백엔드 변경으로 브라우저 요청 수가 줄어들지는 않습니다.

조회 개선 후 최종 검증은 `backend/tests/recruit`, `test_recruit_join_member.py`,
`test_join_deadline.py`를 함께 실행해 117개 통과, 스킵 0개입니다. 별도 임시
PostgreSQL에서 집계·JSON 투영·참여자 표시·대기 상태·예약 실행 회귀까지 확인했습니다.

### 최종 상세 통합과 속도 측정

신규 프로젝트·스터디의 상세는 `detail_bundle`에서 한 SELECT로 모임·설정·확정자·
인원·본인 신청·본인 제한 상태·좋아요를 읽습니다. 확정자와 본인 대기 신청의 최소
필드만 JOIN하고, 전체 대기 수는 상관 집계합니다. 따라서 다른 대기자의 커리어를
읽거나 대기자 수만큼 상세 응답 행을 만들지 않습니다. 기존 인증·회원 확인과
기존/신규 모임 분기는 별도로 유지합니다. 캐시로 오래된 상태를 재사용하지 않습니다.

상세 응답에 `members`, `participation`이 추가됩니다. 기존 독립 API는 그대로
유지하며 프론트 수정은 하지 않았습니다. 기존 운동·게임·공동구매의 계약도 유지합니다.
소희님이 통합 필드를 사용하고 상세 조회 진입점을 하나로 정리해야 실제 화면에서도
한 요청이 됩니다. 목록 조회와 활동/댓글 등 다른 기능까지 합친 API는 아닙니다.

측정 환경: 별도 로컬 Docker PostgreSQL 16, 실제 main 앱의 ASGI 요청,
확정 5명·대기 20명의 스터디 1개, 매 요청 별도 Session, 공통 인증은 대역.
각 시나리오 예열 5회 후 50회 측정했습니다. SQL에는 DB 테이블 존재 확인을 포함하지만
공통 로그인 인증 DB 쿼리는 포함하지 않습니다. 실제 TCP HTTP 서버·브라우저 렌더링·
운영 DB 지연·OAuth는 측정하지 않았습니다.

- 변경 전: 상세 완료 후 참여자/인원 병렬 조회, HTTP 3회, SELECT 총 15회.
  평균 32.221ms, 중앙값 30.144ms, p95 49.403ms.
- 변경 후: 통합 상세 HTTP 1회, 핵심 SELECT 1회.
  분기·회원 확인·테이블 존재 확인 포함 SELECT 총 4회.
  평균 13.797ms, 중앙값 13.633ms, p95 16.284ms.
- 같은 로컬 시나리오의 평균 소요 시간은 약 57.2% 감소했습니다.
  이 수치를 실제 서비스의 속도 개선율로 해석하면 안 됩니다.

최종 검증: 모임 전용 테스트·회원 식별·마감 회귀 121개 통과, 스킵 0개.
실제 PostgreSQL JSON 투영·집계, 단일 핵심 SELECT, 빈 모임/삭제/미존재,
다른 대기자 비공개, 본인 제한/좋아요/스크랩, 독립 API와 통합 응답 일치까지
검증했습니다. 전용 테스트 컨테이너와 임시 측정 스크립트는 검증 후 정리합니다.
