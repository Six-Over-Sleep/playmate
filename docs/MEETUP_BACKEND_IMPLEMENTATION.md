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
| database/sql/20261026_recruit_programs.sql | 기존 데이터 변경 없는 새 테이블 9개 DDL |
| docs/MEETUP_API_CONTRACT.md | 소희 연결용 경로·필드·예시·지원 범위·미연결 기능 |
| docs/MEETUP_BACKEND_IMPLEMENTATION.md | 이 구현 결과와 검증 범위 |
| docs/MEETUP_MANUAL_API_TEST.md | 사용자가 직접 누르는 Swagger 테스트 순서 |
| docs/MEETUP_PROMPT_AUDIT.md | 개발 프롬프트 대조 결과와 보완·보류 항목 |
| docs/MEETUP_API_CONNECTION.md | 2단계 API 연결 결과·실제 활성화 보류 사유 |

## 검증과 한계

```powershell
& .\.venv\Scripts\python.exe -m pytest backend/tests/recruit backend/tests/test_join_deadline.py backend/tests/test_recruit_social.py backend/tests/test_board_api.py -q
```

신규 모임 규칙/저장/API와 기존 모임 마감·소셜·게시판 회귀를 검증했습니다. 실제 로그인 대신 명시적 인증 대역을 사용했고, 기본 DB는 메모리 SQLite입니다. 마이그레이션은 PostgreSQL DDL 생성 결과와 파일 내용을 대조했으며 실제 적용 검증과는 구분합니다.

전용 PostgreSQL URL이 없어 실제 행 잠금 테스트는 스킵했습니다. 로컬 Docker 엔진도 실행 중이 아니었습니다. 실제 DB 잠금/격리 수준·공유 DB DDL 적용·실제 OAuth·프론트 연결·스토리지·봇·XP 지급은 검증 완료가 아닙니다. 최종 테스트 수는 작업 완료 메시지에 기록합니다.

Windows 샌드박스에서 asyncio의 로컬 socketpair 생성이 정지해 격리 API 테스트와 formatter는 권한을 조정해 실행했습니다. 외부 OAuth/공유 DB를 호출하지 않았습니다. 기존 backend/requirements.txt의 누락 설치분 psycopg[binary]를 가상환경에 설치했고, 이번 파일만 Black/4칸 들여쓰기로 정리했습니다. 프로젝트 의존성 파일이나 다른 담당자 파일은 별도로 수정하지 않았습니다.

성능 수치 개선을 주장하는 작업이 아니므로 실제 HTTP 응답 시간 개선율은 측정/보고하지 않았습니다. 목록 모임 수가 늘어도 조회 횟수가 늘지 않는 조건만 격리 테스트로 검증했습니다.

커밋·푸시·PR·병합은 실행하지 않았습니다. 개인 .env와 실제 DB 데이터도 변경하지 않았습니다.
