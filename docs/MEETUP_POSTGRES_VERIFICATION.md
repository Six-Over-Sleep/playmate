# 1단계 PostgreSQL 검증 결과

2026-10-26 / `feature/33-meetup-backend-function-fix`

**독립된 로컬 PostgreSQL 16.15에서 3개 검사를 모두 통과했습니다.**

## 검증 환경

- Docker의 로컬 전용 임시 컨테이너, PostgreSQL 16.15.
- 팀 공유 DB나 개인 `.env`를 사용하지 않았습니다.
- 실제 사용자 대신 가상 회원을 사용했습니다. 실제 OAuth 검증은 아닙니다.
- 테스트마다 UUID 스키마를 만들고 정리했습니다. 검증 후 잔여 테스트 스키마 0개를 확인했습니다.
- 기존 테이블의 빈 테스트 구조를 준비한 뒤, 신규 테이블은 `database/sql/20261026_recruit_programs.sql` 파일의 BEGIN/COMMIT을 포함해 그대로 실행했습니다.

## 통과한 검사

| 검사 | 확인한 결과 |
|---|---|
| 실제 마이그레이션 SQL 실행 | 신규 테이블 9개와 활성 신청 중복 방지 인덱스가 PostgreSQL에 생성됨 |
| 마지막 자리 동시 신청 | 별도 세션의 두 회원이 신청했을 때 ACCEPTED 1건, WAITING 1건. 정원 초과 없음 |
| 동일 회원 동시 중복 신청 | ACCEPTED 1건, HTTP 대응 업무 오류 409 1건. 확정 신청 기록 1개 |

실행 대상: `backend/tests/recruit/test_program_postgres.py`

```powershell
# 별도 테스트 DB를 준비한 경우에만 프로세스 환경에 설정합니다.
$env:RUN_RECRUIT_POSTGRES_TESTS = '1'
$env:RECRUIT_TEST_DATABASE_URL = '<전용 테스트 PostgreSQL 연결 URL>'
& .\.venv\Scripts\python.exe -m pytest backend/tests/recruit/test_program_postgres.py -v
```

실제 실행 결과: **3 passed**. 접속 비밀번호와 실제 개인 설정을 문서에 저장하지 않습니다.

## 다음 단계와 구분

1단계의 테이블 생성·마지막 자리 정원/대기·동일 회원 중복 신청 검증은 완료했습니다.
공유 DB 배포·운영 API 등록·실제 로그인·프론트 통합·예약 실행 연결까지 완료했다는 의미는 아닙니다.
커리큘럼 동시 저장이나 여러 모임의 동시 이탈 집계 등 모든 PostgreSQL 동시성 시나리오를 검증한 결과로 확대하지 않습니다.

임시 컨테이너는 검증 후 중지/자동 삭제합니다. 기존 Docker 컨테이너와 공유 DB는 유지합니다.
다음 순서는 **2. 기존 기능을 유지하면서 실제 API 연결**입니다.
