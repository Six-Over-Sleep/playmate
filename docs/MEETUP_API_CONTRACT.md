# 프로젝트·스터디 백엔드 연결 계약

최신 적용 상태(2026-10-26): 사용자 승인 후 공유 DB의 신규 테이블 9개 생성이 완료됐습니다. 적용 이력은 `docs/MEETUP_MIGRATION_APPLIED.md`에 기록했습니다. 본문에서 공유 DB 적용을 준비 단계로 설명한 부분은 이 적용 기록으로 갱신됩니다. API 활성화와 실제 로그인 검증은 별도입니다.

기준: 2026-10-26, `feature/33-meetup-backend-function-fix`, develop `3de523e`.
민지 담당 백엔드 구현이며 소희 담당 프론트 소스는 수정하지 않았습니다.

## 현재 사용할 수 있는 범위

**기존/신규 API 분기를 main 앱에 연결했습니다. 공유 DB에 기능을 활성화한 상태는 아닙니다.**
기존 주소는 `recruit.py`의 분기 서비스가 처리하고, 연장·예외 시작·취소·활동 등 중복되지 않는 주소만 별도 등록했습니다. 새 기능은 `ENABLE_RECRUIT_PROGRAMS=true`일 때 활성화하며 기본은 false입니다. 개인 `.env`는 변경하지 않았습니다.

기존 `-1` 참여 인증, 기존 수정/삭제 권한, 관리자 자동 참여 변경의 협의 경계는 유지합니다. 신규 쓰기는 검증된 공통 회원 인증을 사용합니다. 같은 경로의 두 핸들러를 등록하지 않았고, 각 method/path 조합이 한 번만 등록되는지 검증했습니다. 신규 스터디는 category만으로 판별하지 않고 `recruit_programs` 기록으로 구분합니다.

실제 연결 전 필요한 작업:

1. 추가형 마이그레이션을 전용 PostgreSQL에서 검증하고 공유 DB 적용 승인을 받습니다.
2. 기존/신규 분기와 공개 조회 연결 코드는 완료했습니다. 익명 응답에는 본인 신청·제재 정보를 넣지 않고 모든 쓰기 권한을 false로 반환합니다. 실제 로그인 검증은 다음 단계입니다.
3. 기존 임시 참여 인증과 수정/삭제 권한 변경을 합의합니다. 신규 쓰기는 공통 `get_current_member_id`와 서버 회원 권한 검사를 사용합니다.
4. 공통 기술 사전의 실제 ID/이름 조회 어댑터를 연결합니다. 현재 미연결 프로젝트 생성은 명시적 503입니다.
5. 사용자 생성 스터디는 개설자만 커리큘럼을 저장합니다. 관리자 생성 모임의 편집 주체·편집 기간은 협의 후 연결하며, 관리자라는 이유로 자동 허용하지 않습니다.
6. 기존 봇의 마감 처리와 신규 예약 처리 중 어느 쪽이 각 모임을 담당할지 정합니다. 두 실행기가 같은 상태를 동시에 바꾸면 안 됩니다.

기능을 끈 상태의 신규 모임은 기존 쓰기 규칙으로 우회하지 못하도록 503으로 거절하고 목록에서 제외합니다. 기존 모임은 마이그레이션 전 DB에서도 기존 경로로 처리됩니다. 신규 생성 입력 오류를 기존 스키마의 extra 무시로 성공시키지 않습니다.

DELETE는 기존 모임의 논리 삭제 의미를 유지합니다. 신규 모임은 개설자의 모집 중 초안이며 다른 회원의 신청 이력이 없을 때만 논리 삭제를 지원합니다. 참여 이력이 있는 모임은 취소/종료 절차를 사용합니다. 새 API 연결/현재 활성화 제한은 `docs/MEETUP_API_CONNECTION.md`를 참고합니다.

## 공통 기능 재확인 결과

최신 develop에는 다음 기능이 있습니다. ‘공통 XP·마이페이지 전체가 없다’는 설명은 최신 코드에 해당하지 않습니다.

| 기존 파일 | 현재 확인한 내용 | 모임에서 아직 연결할 수 없는 부분 |
|---|---|---|
| `backend/app/services/xp_service.py` | 레벨 계산, ATTEND/POST/COMMENT/REPLY 지급, POST/COMMENT 회수 | 모임 실제 참여·주간 인증·완료 보상 유형, 모임 원 지급 참조 회수 계약 |
| `backend/app/services/skill_xp_service.py` | 기술별 학습 XP | 프로젝트 기술 사전의 숫자 ID 매핑, 베타 모임 자격 판정 |
| `backend/app/routers/mypage.py` | `/api/mypage` 프로필·레벨·XP 이력·출석·학습·내 활동 조회 | 학력·자격증·경험·수상·포트폴리오 커리어 항목 CRUD/선택 조회 |
| `backend/app/models/member.py` | 닉네임·실제 회원 권한 | 새 모임 전용 회원 DB를 만들 필요 없음 |

XP 공통 구현을 복제하거나 모임을 POST 보상으로 속여 호출하지 않습니다. 공통 담당자가 모임 유형과 인정/회수 계약을 지원하면 기존 outbox의 어댑터에 연결합니다. 마이페이지 커리어 불러오기는 원래 합의대로 후속 단계입니다.

## 경로와 응답

기본 경로는 기존과 같은 `/api/recruits`입니다. 신규 라우터의 경로를 임의로 바꿔 프론트에 강요하지 않습니다.

| 메서드/경로 | 요청 | 응답 |
|---|---|---|
| POST `/api/recruits` | ProgramCreate | 201 `{recruit_id, post_id}` |
| GET `/api/recruits?category=project` | study 또는 project, 생략 시 둘 다 | 배열, 별도 items 래퍼 없음 |
| GET `/api/recruits/{id}` | 없음 | 상세 객체·본인 신청 요약·서버 permissions |
| PATCH `/api/recruits/{id}` | 보낸 필드만 | 변경된 상세 |
| POST `/api/recruits/{id}/join` | 프로젝트 신청서, 스터디는 본문 생략 가능 | 확정/대기 모두 200, application_status·reason_code |
| DELETE `/api/recruits/{id}/join` | 없음 | 취소/이탈 결과·확정/대기 인원 |
| GET `/api/recruits/{id}/members` | 없음 | 확정 참여자만, 비공개 신청 자료 제외 |
| GET `/api/recruits/{id}/count` | 없음 | 기존 current_members/capacity/remaining + waiting_count |
| POST `/api/recruits/{id}/extension` | starts_at, ends_at, schedule_version, request_key | 새 일정·버전·횟수 |
| POST `/api/recruits/{id}/exception-start` | schedule_version | 결정 기록, 즉시 시작하지 않음 |
| POST `/api/recruits/{id}/cancel` | reason | CANCELED 상세 |
| POST `/api/recruits/{id}/abort` | reason | ABORTED 상세 |
| GET/PUT `/api/recruits/{id}/curriculum` | PUT: version, items | version, items |
| GET/POST `/api/recruits/{id}/activities` | POST: 활동 입력 | 목록 배열 / 201 활동 객체 |

업무 오류는 `{ "detail": "설명" }`, 스키마 오류는 FastAPI의 detail 배열입니다. 401 인증, 403 권한, 404 대상 없음, 409 업무 충돌, 422 입력 오류, 503 미연결 기능입니다.

## 생성과 신청 예시

아래 ID는 설명용입니다. 실제 공통 기술 사전 ID를 사용해야 합니다.

```json
{
  "title": "웹 서비스 프로젝트",
  "body": "함께 구현합니다.",
  "category": "project",
  "recruit_mode": "short",
  "capacity": 5,
  "starts_at": "2026-11-10T19:00:00+09:00",
  "ends_at": "2026-11-30T19:00:00+09:00",
  "required_skill_ids": [101, 102],
  "creator_application": {
    "skill_ids": [101],
    "career_item_ids": [],
    "leader_volunteer": true,
    "direct_input": {
      "skills": [], "education": null, "certificates": null,
      "experience": "개인 프로젝트 경험", "awards": null, "portfolio_url": null
    }
  }
}
```

일정은 시간대 필수입니다. deadline_at은 생략하면 시작 24시간 전으로 계산하고, 보내면 같은 시각인지 검사합니다. 단기 meeting_start/meeting_end를 함께 보내면 starts_at/ends_at과 같아야 합니다. 정기는 regular_days/regular_time/regular_start_date가 필요하고 첫 일정과 starts_at을 대조합니다. 정기의 meeting_end를 전체 종료일로 재사용하지 않습니다.

스터디는 `study_type: TECHNOLOGY | CERTIFICATE`, 기술 공부는 `difficulty: BEGINNER | ADVANCED`, 자격증은 difficulty null, study_topic 필수입니다. 기존 study_period/study_method를 보존합니다.

신청에는 같은 creator_application 형식을 사용합니다. `career_item_ids`는 생략 또는 []만 허용합니다. nonempty/null은 422입니다. 직접 입력 6항목은 선택 입력이며 제출 시 복사하고 마이페이지에 저장하지 않습니다. 자기신고를 증빙 진위 검증으로 표시하지 않습니다.

응답 핵심:

```json
{
  "application_status": "WAITING",
  "reason_code": "CAPACITY_FULL",
  "participant_count": 5,
  "waiting_count": 1,
  "lifecycle_status": "READY"
}
```

본인 신청 요약은 application_id/application_status/skill_ids/leader_volunteer입니다. 목록·상세·참여자 목록에 학력·경험·포트폴리오 등 신청 자료를 넣지 않습니다. 기존 like_count/liked_by_me/scrapped_by_me와 닉네임은 기존 테이블을 조회합니다.

## 확정된 규칙

- USER 정원 2~5, 개설자 자동 확정 포함. ADMIN 정원 2~4, 자동 참여 제외.
- 프로젝트는 남은 자리 수 >= 미충족 기술 수일 때 확정합니다. 한 사람이 여러 기술을 맡을 수 있습니다.
- 스터디는 신청순 선착순, 초과 신청 WAITING. 취소 시 마감 전 기존 대기자부터 승격합니다.
- 프로젝트 대기자는 기술 조건을 다시 검사하며 부적합한 앞 대기자를 건너뛸 수 있습니다.
- 둘 다 시작 24시간 전 신규 신청·승격 마감, 예정 시각 시작. 스터디 미달은 삭제가 아닌 취소.
- USER 프로젝트 팀장 최초 선정은 전날 확정자 중 희망자 우선·신청순, ADMIN은 희망 여부와 무관하게 신청순. 승계는 남은 확정자 신청순입니다.
- 연장은 팀장만 최대 2회, 매회 기존 시작일 다음 날~14일 이내 한국 달력 날짜, 새 마감은 미래·종료는 새 시작 이후여야 합니다.
- 연장 재시도는 request_key와 원 요청 전체를 비교합니다. 같은 키/같은 요청은 원 결과, 다른 요청은 409입니다.
- 2회 연장 후 마지막 마감에 확정 2명 이상이면 기술 미충족 예외 시작 선택 가능. 시작 시점 최소 2명은 다시 검사합니다. 미선택·조건 미달은 자동 취소.
- 타인 첫 신청(대기/나중에 취소한 신청 포함) 이후 일반 PATCH로 정원·필수 기술·시작·종료를 바꿀 수 없습니다. 공식 연장만 예외입니다.
- 마감 후 또는 연장 이후의 일정 변경을 일반 PATCH로 우회할 수 없습니다. 응답의 extension_window/my_eligibility/exception_start로 날짜 범위·본인 제한·예외 선택 유효 여부를 확인합니다.
- 시작 후 실제 확정 참여자의 자발적 이탈만 누적합니다. 3회부터 신규 신청 제한, 기존 확정·대기 신청은 보존합니다. 1명 남은 프로젝트의 중도 종료는 ABORTED이며 정상 완료 보상이 아닙니다.
- **모든 종류 적용이라는 목표는 유지하지만, 기존 운동·게임·공동구매의 실제 로그인/이탈 경로 연결은 협의 보류 상태입니다. 현재 운영 전체에 적용됐다고 안내하면 안 됩니다.**

## 활동·XP·예약 처리

활동: WEEKLY_CHECK는 week 양수 필수, 프로젝트 OUTPUT은 INTERIM/FINAL 필수, REVIEW는 정상 운영 종료 후 확정 참여자가 작성합니다. 스토리지 연결 전 attachment_ids는 빈 배열만 허용하고 텍스트·HTTP(S) 링크를 지원합니다.

날짜에 따른 COMPLETED는 운영 종료입니다. 전원 개인 참여/완료 인정이나 XP를 자동 지급하지 않습니다. 인정 정책이 없으면 내부 recognize도 503입니다. 인정 API는 공개하지 않았습니다.

개인 인정과 XP_GRANT 예약은 같은 트랜잭션에 저장합니다. 재시도는 같은 사건 키를 사용하며, 무효 시 XP_REVOKE가 원 지급 참조를 지정합니다. 실제 어댑터가 없으면 PENDING으로 유지합니다. 외부 지급 확정 참조를 받은 뒤에만 지급 확인 상태를 기록합니다. 주간 한도·재인정/복구·판정 권한은 공통 담당자와 확정할 항목입니다.

예약 실행은 `backend.app.jobs.process_recruit_jobs.process_once(service, gateways)`를 별도 실행기가 호출합니다. API worker 시작 시 반복 작업을 만들지 않습니다. 서비스와 gateway를 명시적으로 구성해야 하며 기본 구성만으로 공유 DB나 디스코드에 전송하지 않습니다.

DISCORD_PREPARE/SCHEDULE_CHANGED/ROSTER_CHANGED/PROGRAM_CANCELED/PROGRAM_ABORTED/OPERATING_PERIOD_ENDED는 중복 방지 키·모임 ID·일정 버전으로 전달합니다. 일정 변경 시 구버전 대기 요청은 SUPERSEDED 처리합니다. 전달 실패는 활동 저장을 취소하지 않고 재시도합니다. 수신 측 중복 방지와 네트워크 타임아웃은 어댑터 계약입니다.

기존 recruits 시간 컬럼은 KST naive, 신규 recruit_programs 시간 컬럼은 UTC timezone-aware입니다. 서로 변환해 저장합니다. 확정 참여자는 기존 recruit_members의 JOINED에도 반영하므로 기존 내 모임 조회/봇에서 읽을 수 있습니다. 팀장과 개설자는 별도 개념입니다. 봇 실제 연결 및 처리 주체 합의가 끝났다는 의미는 아닙니다.

## 검증 방법

```powershell
# 프로젝트 루트, 기존 가상환경 사용
& .\.venv\Scripts\python.exe -m pytest backend/tests/recruit -q
```

기본은 메모리 SQLite·대역 기술 사전/정책·ASGI 테스트입니다. 실제 OAuth·공유 DB를 사용하지 않습니다. 전용 PostgreSQL URL을 명시하지 않으면 실제 행 잠금 테스트는 스킵합니다. SQLite 통과를 실제 PostgreSQL 동시성 검증으로 보지 않습니다.

전용 DB에서만 `RUN_RECRUIT_POSTGRES_TESTS=1`, `RECRUIT_TEST_DATABASE_URL`을 설정하면 UUID 테스트 스키마를 생성/삭제하는 테스트가 실행됩니다. 공유 운영 DB URL을 넣으면 안 됩니다. 기존 test_host.py/test_database.py 등의 전체 수집은 별도 확인 전 실행하지 않습니다.

마이그레이션: `database/sql/20261026_recruit_programs.sql`. 새 테이블 9개를 추가하는 검토용 파일이며 공유 DB에 적용하지 않았습니다. 기존 다른 팀 마이그레이션 번호와 충돌하지 않도록 날짜 이름을 사용했습니다. 실제 적용 이력 관리 방식도 팀 기준에 맞춰야 합니다.

후속 검증: 로컬 전용 PostgreSQL 16.15에서 해당 SQL 파일 실행과 동시 신청 검증 3개를 통과했습니다. 공유 DB에 적용한 것은 아닙니다. `docs/MEETUP_POSTGRES_VERIFICATION.md`에 검사 범위와 결과를 기록했습니다.
