# Issue #31 Phase 1 PostgreSQL 통합 검증 보고 — 2026-10-25

## 1. 최종 결론

**PASS — 요청한 7개 검증 항목을 실제 실행으로 확인했다.**
이 판정은 Phase 1 DB 검증 및 기존 인증 실패 원인 확인에 대한 것이다.
기존 인증 테스트 자체와 기존 테스트 전체가 통과한 것은 아니다.
운영용 정규화·repository·마이그레이션 오류는 발견되지 않았다.
통합 테스트가 가짜 saramin 레코드를 커밋하는 문제 1건을 재현하고 해당 테스트만 최소 수정했다.

## 2. Docker/PostgreSQL 환경

| 항목 | 실제 확인 결과 |
|---|---|
| Docker | 서버 29.6.2, Linux 엔진 연결 성공 |
| PostgreSQL | 16.15 (Debian 16.15-1.pgdg13+2) |
| 기존 컨테이너 | postgres-db, postgres:16, 호스트 5432. 조회만 수행 |
| 새 컨테이너 | playmate-job-insights-phase1-20261025 |
| 새 이미지 다운로드 | 없음. 기존 postgres:16 이미지에 --pull never 적용 |
| 접속 | 127.0.0.1:49339 → 컨테이너 5432, 임의 생성 비밀번호는 출력·파일 저장하지 않음 |
| 주 검증 DB | job_insights_test_phase1 |
| 수정 전 재현 DB | job_insights_test_phase1_integration |
| 수정 후 검증 DB | job_insights_test_phase1_verified |
| 새 볼륨 | ef9c1b05ecedee9eaf9c9092a64b93e41cf96f2ff9210bb1d4b71a7825d019f0 |

새 컨테이너에는 기존 볼륨을 마운트하지 않았다. postgres 이미지가 새 익명 볼륨을 생성했다.
주 DB의 current_database()를 조회했으며 사용자 테이블 0개/public 테이블 0개에서 시작했다.
나머지 두 DB는 이 새 컨테이너에서 createdb로 각각 새로 생성했다.
서버 포트와 Docker 포트 매핑을 함께 확인했으므로 원격 팀 DB가 아니다.
기존 Docker 설정/Compose 파일/컨테이너/볼륨은 변경하지 않았다.

연결 우선순위: db_connect.py는 load_dotenv의 기본 override=False를 사용하고
DB_HOST/PORT/USER/PASSWORD/NAME/SSLMODE에서 직접 psycopg2 연결을 구성한다.
프로세스 환경변수를 전부 명시했고 DATABASE_URL은 이 연결을 덮어쓰지 않는다.
core/database.py의 SQLAlchemy URL 역시 config의 DB_*로 생성된다.
RealDictCursor와 execute_values(fetch=True)의 반환 형태가 실제 실행에서 호환됨을 확인했다.

## 3. 검증 체크리스트

| 항목 | 판정 | 실제 실행 근거 |
|---|---|---|
| 격리 PostgreSQL의 7개 테이블 | PASS | pg_tables 7개, PK 7/FK 6/UNIQUE 5/CHECK 9, 인덱스 17 |
| 목업 467건 적재 | PASS | 기존 load_job_trends.py 실행, source=mock COUNT=467 |
| 재적재 467건 유지 | PASS | success=467/duplicate=467, 관계 561/259도 동일 |
| 2026-Q3 84건 | PASS | 서울 기준 SQL 집계 84, 7분기 전체 목표 일치 |
| mock/saramin 분리 | PASS | 같은 ID 5개를 다른 source로 저장 가능, 트랜잭션 내부 467/5, 롤백 후 467/0 |
| JSONB/FK/대표 유일성/롤백 | PASS | 원본 467개 전부 일치, 제약 위반 SQLSTATE 확인, 실제 FK 오류 후 전체 상태 동일 |
| 기존 인증 2건 실패 원인 | PASS (원인 확인) | 기본 환경 timeout/503, Docker 연결에서는 members 부재/503. 테스트 자체는 FAIL |

실제 실행한 적재 명령(격리된 프로세스 DB 환경변수 주입 후):

```powershell
python database/scripts/load_job_trends.py --isolated-local --migrate --input database/fixtures/job_trends_sample.json
python database/scripts/load_job_trends.py --isolated-local --input database/fixtures/job_trends_full.json
python database/scripts/load_job_trends.py --isolated-local --input database/fixtures/job_trends_full.json
```

마이그레이션 및 seed_catalog를 다시 실행해도 아래 모든 테이블 건수가 같았다.
대표 직무 인덱스 실제 정의:

```sql
CREATE UNIQUE INDEX posting_one_primary_idx
ON job_insights.posting_roles USING btree (posting_id) WHERE is_primary;

SELECT COUNT(*) FROM job_insights.postings WHERE source = 'mock'; -- 467

SELECT to_char(posted_at AT TIME ZONE 'Asia/Seoul', 'YYYY-"Q"Q') AS quarter,
       COUNT(*) AS n
FROM job_insights.postings WHERE source='mock'
GROUP BY 1 ORDER BY 1;
```

제약조건 확인에 사용한 SQL은 위 목록 조회와 함께 다음과 같다.

```sql
SELECT contype, COUNT(*)
FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace
WHERE n.nspname='job_insights' GROUP BY contype;
SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='job_insights';
SELECT COUNT(*)-COUNT(DISTINCT (source,source_job_id)) FROM job_insights.postings; -- 0
```

JSONB 원본을 전체 fixture와 비교하고 extract(epoch FROM posted_at)을 원본 timestamp와 비교했다.
각 사례는 새 테스트 DB에서만 실행했고 제약 위반 시 롤백했다.

| 실행한 제약 위반·갱신 | 실제 결과 |
|---|---|
| raw_payload에 JSON 배열 INSERT | CHECK 23514로 거부 |
| mock/90000000 중복 INSERT | UNIQUE 23505로 거부 |
| posting_id=-1 관계 INSERT | FK 23503으로 거부 |
| role_id=-1 관계 INSERT | FK 23503으로 거부 |
| 복수 직무의 is_primary를 동시에 TRUE로 갱신 | UNIQUE 23505로 거부 |
| 일반적인 복수 직무 | 561개 관계 저장 성공 |
| manual/대표 직무 설정 후 467건 UPSERT | manual/TRUE 유지, inserted=0/existing=467 |
| 저장 후 실제 FK 위반 발생 | LoadReport success=0/failed=5, 원본·전체 직무 관계·전체 키워드 관계가 이전과 동일 |

원본 비교는 ID/제목/복수 job_code를 포함한 JSON 객체 전체의 의미상 동일성 검사다.
시간은 467건 모두 Unix 초와 일치했고 날짜형은 마이그레이션의 TIMESTAMPTZ로 저장했다.
롤백 시 PostgreSQL identity sequence의 소모 값은 되돌아가지 않으며 데이터 중복/손상은 아니다.

## 4. 실제 DB 적재 결과

주 DB 최종 상태:

| 항목 | 건수 |
|---|---:|
| 전체 공고/mock | 467 |
| saramin | 0 |
| 분야/직무 | 8 / 30 |
| 키워드/별칭 | 2 / 2 |
| 공고-직무 관계 | 561 |
| 공고-키워드 관계 | 259 |
| source+원본 ID 중복 | 0 |
| 회사명/키워드/급여 코드 NULL | 36 / 43 / 67 |

| 분기 | 실제 SQL 결과 |
|---|---:|
| 2025-Q1 | 51 |
| 2025-Q2 | 57 |
| 2025-Q3 | 63 |
| 2025-Q4 | 64 |
| 2026-Q1 | 71 |
| 2026-Q2 | 77 |
| 2026-Q3 | 84 |

| 단계 | success | failed | duplicate | skipped | 공고/직무관계/키워드관계 |
|---|---:|---:|---:|---:|---|
| 샘플 적재 | 5 | 0 | 0 | 0 | 5 / 7 / 4 |
| 전체 적재 | 467 | 0 | 5 | 0 | 467 / 561 / 259 |
| 전체 재적재 | 467 | 0 | 467 | 0 | 467 / 561 / 259 |
| 마이그레이션·시드 재실행 | 해당 없음 | 0 | 해당 없음 | 해당 없음 | 467 / 561 / 259 |

duplicate는 success의 부분집합일 수 있다. 전체 적재 첫 실행의 duplicate=5는 먼저 넣은 샘플이다.
급여 수치 min/max는 전부 NULL이며 자격요건/우대사항 원문을 생성하지 않았다.
단일 입력 내 중복 ID 마지막 값 우선 정책은 신규 단위 테스트에서 계속 통과했다.

## 5. 테스트 결과

기존 파일과 의존성 설정은 바꾸지 않고 기존 .alltestdeps 및 .venv의 설치 패키지를 사용했다.
아래 결과는 각각 별개 실행이며 중복 테스트 결과를 더해 전체 통과 건수로 표현하지 않는다.

| 실행 | 결과 | 비고 |
|---|---|---|
| Issue31 단위 | 12 passed | 55 warnings |
| 수정 전 Issue31 PostgreSQL 통합 | 1 passed | 종료 후 synthetic saramin 5건 잔존 문제 재현 |
| 수정 후 Issue31 PostgreSQL 통합 | 1 passed | 새 빈 verified DB, 최종 mock=467만 존재 |
| 기존+신규 전체(test_host만 제외) | 119 passed, 2 failed, 2 skipped | 56 warnings, 인증 테스트 포함 |
| 기존 인증 2건(Docker 연결) | 2 failed | members 테이블 부재, 503 |
| 기존 test_host(Docker 연결) | collection ERROR 1 | posts 테이블 부재 |

전체 실행의 skip 2건은 RUN_POSTGRES_INTEGRATION=0인 회귀 실행에서의 기존 게시판/신규 취업 통합 테스트다.
신규 통합 테스트는 별도로 RUN_POSTGRES_INTEGRATION=1에서 성공했다.
기존 게시판 통합 테스트는 필요한 기존 public 스키마가 없어 미검증이다.
기존 host 스크립트는 수집 시 실제 DB를 사용하므로 별도 안전 DB에서만 실행해 원인을 확인했다.
따라서 **기존 전체 테스트 통과가 아니며 기존 public 기반 통합 시나리오는 UNVERIFIED**다.

```powershell
# 기존 설치 패키지 사용
$env:PYTHONPATH="$PWD/.alltestdeps;$PWD/.venv/Lib/site-packages;$PWD/backend;$PWD"
python -m pytest backend/tests/test_job_trends.py -q --disable-warnings
python -m pytest backend/tests/integration/test_postgres_job_trends.py -q --disable-warnings
python -m pytest backend/tests --ignore=backend/tests/test_host.py -q --disable-warnings --tb=short
python -m pytest backend/tests/test_auth_flow.py -q --disable-warnings --tb=short
python -m pytest backend/tests/test_host.py -q --disable-warnings --tb=short
```

단위/회귀는 RUN_POSTGRES_INTEGRATION=0, 신규 통합/인증 Docker 확인은 1이며
DB_*는 새 컨테이너와 각 전용 DB로 지정했다. 전용 DB 인증 확인은 더미 OAuth 설정만 사용했다.
통합 테스트는 빈 전용 DB가 필요하며 이미 적재된 DB를 다시 초기화하지 않는다.
임시 검증 스크립트와 테스트 로그는 사용자 TEMP의 job31_*.py/log에 남겼다.
비밀번호는 docker inspect 결과에서 메모리로만 읽어 자식 프로세스에 전달했고 출력하지 않았다.

## 6. 발견된 문제

### Issue31 통합 테스트 — 수정 완료

- 파일: backend/tests/integration/test_postgres_job_trends.py 마지막 출처 분리 구간.
- 원인: load_response(..., 'saramin')은 commit=True이므로 가짜 5건이 테스트 후에도 저장됨.
- 재현: 수정 전 테스트 1 passed 후 GROUP BY source 결과 mock=467/saramin=5.
- 영향: 테스트 전용 DB의 데이터 해석 혼동. 운영 적재 SQL 오류는 아님.
- 수정: 기존 db_cursor() 기본 롤백 문맥에서 parser/repository로 검증하고 문맥 밖 mock=467만 확인.
- 재검증: 새 verified DB에서 1 passed, saramin=0. 기존 재현 DB는 삭제/정리하지 않고 보존.

### 기존 인증 테스트 — 수정 금지 범위, 미수정

- 파일: backend/tests/test_auth_flow.py의 _login_callback, app/routers/auth.py의 /auth/me.
- 원인: get_member patch는 callback 요청까지만 적용되며 /auth/me 요청은 patch 문맥 밖.
- 기본 conftest는 RUN_POSTGRES_INTEGRATION!=1이면 127.0.0.1:1/test로 접속을 강제함.
- 실제 결과: ConnectionTimeout → 503, 두 테스트 모두 expected 200과 불일치.
- Docker 연결 후 결과: 연결 자체는 성공하지만 public.members가 없어 UndefinedTable → 503.
- Docker 실행만으로 해결되지 않는다. 회원 테이블/고정 데이터 또는 /auth/me까지 확장한
  fixture가 필요하지만 기존 인증/테스트 수정은 범위 밖이므로 변경하지 않았다.
- 이 두 테스트만 독립 실행해도 실패하므로 Issue31 새 모듈과 무관한 기존 테스트 격리 문제다.
- 공유 DB 우회는 하지 않았다.

### 기존 host/게시판 통합 환경 — 미수정

test_host.py는 수집 단계에 ORM으로 public.posts와 기존 회원을 요구한다.
새 테스트 DB에는 이 스키마가 없으므로 UndefinedTable 오류가 재현됐다.
기존 스키마/데이터를 복사하거나 신규 구축하는 것은 이번 범위 밖이므로 하지 않았다.

## 7. 수정 파일 목록

이번 후속 실행에서 수정한 파일은 3개다.

1. backend/tests/integration/test_postgres_job_trends.py — 가짜 saramin 영구 저장 문제 최소 수정.
2. docs/design/job_trends_phase1_report.md — 실제 DB 검증 결과, 실패 원인, 보호 결과 반영.
3. docs/design/job_trends_phase1.md — 미검증 상태를 최신 검증 결과로 갱신.

정규화/service/repository/DDL/시드/fixture/생성기/적재 CLI의 코드 수정은 없다.
기존 API 계약서도 수정하지 않았다. 임시 실행 스크립트는 TEMP에만 작성했다.

## 8. 데이터 보호 결과

- 기존 public 스키마 변경 없음. 새 주 DB/verified DB의 public 테이블은 검증 전후 0개.
- 기존 PlayMate DB에는 마이그레이션/적재/정리 SQL을 실행하지 않았다.
- 기존 Docker 볼륨 변경 없음. 이번 컨테이너가 만든 새 익명 볼륨만 사용했다.
- 새 컨테이너 1개, 새 전용 DB 3개를 모두 남겨두었다. DROP/TRUNCATE/컨테이너 삭제/볼륨 삭제 없음.
- 주 DB: mock=467/saramin=0. verified DB: mock=467/saramin=0.
- 수정 전 재현 DB인 integration에는 mock=467/가짜 saramin=5를 보존했다.
  DB COMMENT에 synthetic saramin fixtures이며 실제 수집 데이터가 아님을 명시했다.
- 기존 게시판/인증/모임/공통 연결/프론트엔드/.env/Compose/의존성/공통 테스트 변경 없음.
- DB 쓰기 작업은 모두 이번에 생성한 컨테이너의 새 DB에서만 수행했다.
  기존 repository의 관계 DELETE는 이 테스트 DB의 UPSERT 대상 관계만 갱신했으며
  기존 프로젝트 DB의 데이터 정리/삭제는 수행하지 않았다.

## 9. Git 상태

브랜치 feature/31-job-trends-backend 유지, origin도 지정 저장소와 일치한다.
기존 Phase1의 13개 파일은 여전히 untracked 상태이며 모두 보존했다.
그중 이번 내용 변경은 위 3개 파일이다. git diff --check 성공, 추적 파일 diff 없음.
Commit/Push/PR/Merge/브랜치 생성·전환을 수행하지 않았다.

## 10. 사용자에게 필요한 후속 조치

Issue31 Phase 1 DB 검증 완료. 승인 후 Phase 2 API 개발을 진행할 수 있다.
이번 실행에서는 Phase 2 구현을 하지 않았다.
기존 인증 fixture와 public 스키마를 필요로 하는 통합 환경 문제는 별도 담당자가 해결해야 한다.
후속 작업에서 목업 시연·검증에 사용할 로컬 DB는 job_insights_test_phase1이며
재현용 integration DB의 가짜 saramin 레코드는 실제 수집 데이터로 사용하면 안 된다.

---

# 최초 실행 기록 (아래 미검증 표기는 후속 검증 이전의 이력)

## 1. 기존 프로젝트 분석

- 현재 브랜치: feature/31-job-trends-backend.
- origin: https://github.com/Six-Over-Sleep/playmate.git.
- 원격 최신 develop과 시작 HEAD는 15d7795b68247e2837f643216b08825c4bb3c38c로 일치.
- 시작 시 작업 트리는 깨끗했다. 기존 파일은 수정하지 않았다.
- FastAPI main → routers/services/repositories, 게시판 psycopg2 풀의 db_cursor 재사용.
- snake_case, 한국어 docstring, 바인딩 SQL, 기존 네 칸 들여쓰기 적용.
- 분석·설계 상세는 [Phase 1 문서](job_trends_phase1.md)에 기록했다.

## 2. 신규·수정 파일 목록

모든 파일은 신규다. 기존 파일 수정은 없다.

| 경로 | 구현 내용·생성 이유 |
|---|---|
| database/sql/004_job_insights.sql | 독립 스키마/7개 테이블/제약조건/인덱스 DDL |
| backend/app/services/job_trends_catalog.py | 분야 8개/직무 30개/최소 키워드 시드 정의 |
| backend/app/services/job_trends_service.py | 공식 JSON 공통 정규화/분류/출처/트랜잭션/건수 보고 |
| backend/app/repositories/job_trends_repository.py | 시드/배치 UPSERT/관계 갱신 SQL, 공고당 쿼리 방지 |
| database/scripts/generate_job_trends_mock.py | 시드 고정 목업 생성 CLI |
| database/scripts/load_job_trends.py | 기존 연결 재사용, 전용 로컬 DB 확인 후 마이그레이션/적재 CLI |
| database/fixtures/job_trends_sample.json | 대표 5건 공식 구조 fixture |
| database/fixtures/job_trends_full.json | 가상 467건 오프라인 통합 fixture |
| backend/tests/test_job_trends.py | 12개 단위 테스트 |
| backend/tests/integration/test_postgres_job_trends.py | 전용 PostgreSQL 마이그레이션/적재/재실행/제약/롤백/source 분리 테스트 |
| docs/design/job_trends_phase1.md | 분석, ERD, 컬럼 명세, 재현 명령, 선아 인수인계 |
| docs/design/job_trends_api_contract.md | 다음 날 구현할 API 계약과 우선순위 |
| docs/design/job_trends_phase1_report.md | 이 실행의 결과·제약 보고 |

## 3. PostgreSQL DB 구현 결과

DDL 작성: job_insights.fields/roles/postings/posting_roles/keywords/keyword_aliases/posting_keywords.
실제 생성한 테이블은 **없다**. PostgreSQL 격리 환경 미확보로 실행하지 않았다.
PK/FK/UNIQUE/CHECK/대표 직무 partial UNIQUE 및 조회 인덱스를 작성했으나 DB 실행 검증은 미완료다.
기존 public 스키마·데이터 변경은 없다. ERD/컬럼 명세는 Phase 1 문서를 참조한다.

## 4. 사람인 목업 데이터 결과

공식 가이드/코드표/사용안내를 직접 확인했고 API 호출은 하지 않았다.
jobs/job 배열과 중첩 company.detail/position, salary, 문자열 timestamp, 숫자 active 구조를 사용했다.
대표 5건 단위 검증 후 전체 467건 파일을 생성했다.
분기별 생성 건수: 51/57/63/64/71/77/84. PostgreSQL 적재 건수는 미검증이다.
정규화 NULL: 회사 36, 키워드 43, 급여 코드 67, 연봉 수치 각 467.
생성 ID 중복 0, 입력 중복 처리 단위 검증 통과. DB 재적재 결과는 아직 없다.
실제 승인 후 필드·에러·과거 조회 가능 범위를 확인하고 입력만 공통 파서에 연결한다.
467건 단일 fixture는 오프라인 테스트용이며 실제 API 페이지 최대 110건과 구별한다.

## 5. 테스트 결과

현재 로컬 .venv에 pytest가 없어 기존 작업공간의 테스트 의존성 디렉터리를 사용했다.
설치된 조합의 경고 56건이 출력되므로 uv.lock과 정확히 동일한 환경 검증으로 간주하지 않는다.

```powershell
$env:PYTHONPATH="$PWD/.alltestdeps;$PWD/.venv/Lib/site-packages;$PWD/backend;$PWD"
python -m pytest backend/tests/test_job_trends.py -q --disable-warnings
python -m pytest backend/tests --ignore=backend/tests/test_host.py -q --disable-warnings
python -m pytest backend/tests --ignore=backend/tests/test_host.py --ignore=backend/tests/test_auth_flow.py -q --disable-warnings
git diff --check
```

- 신규 단위: 12 passed.
- test_host 제외 전체: 119 passed, 2 failed, 2 skipped, 56 warnings.
- test_host와 test_auth_flow 제외 최종 실행: **119 passed, 2 skipped**, 56 warnings.
- 실패: test_new_member_login/test_existing_member_login. /auth/me 호출은
  get_member mock 문맥 밖에서 실행되어 실제 테스트 DB 조회를 시도하고 timeout/503을 반환했다.
  기존 인증 코드를 변경하거나 테스트를 수정하지 않았다.
- test_host 포함 시 수집 단계 DB 연결 오류로 중단된다. 테스트 DB는 기본 conftest에서
  127.0.0.1:1로 격리되므로 공유 DB 접속은 없다.
- skipped: 기존 게시판 PostgreSQL 통합 테스트 1건 및 신규 PostgreSQL 통합 테스트 1건.
- 일부 sandbox 실행은 스레드 기반 테스트에서 진행이 멈춰 중단했다. 최종 회귀 결과는
  일반 로컬 실행으로 얻었다.
- compileall 및 git diff --check 성공. 신규 파일 문법도 확인했다.
- Docker API 연결 실패, PATH/표준 설치 위치에 PostgreSQL 실행 환경 미확보.
  실제 마이그레이션/JSONB/FK/partial UNIQUE/467건 적재/재적재/롤백은 **미검증**이다.

## 6. 선아에게 전달할 내용

FIELDS/ROLES로 내부 코드 공유. 원본 job_code는 별도 보존한다.
keywords/keyword_aliases/posting_keywords 및 keyword_mentions 인터페이스를 제공한다.
최소 Python/Java만 구현했으며 전체 사전·자격증 사전은 구축하지 않았다.
공고 원본과 출처는 keyword_text/raw_payload/mention_source에서 확인한다.
api_keyword/title만 현재 분석에 사용하고 requirement/preference는 실제 원문 확보 전 사용하지 않는다.
조회 SQL과 중복 집계·결측 주의사항은 Phase 1 문서, API 연결은 계약 문서를 참조한다.

## 7. 10월 26일 작업 계획

1. 격리 PostgreSQL을 확보하고 준비된 통합 테스트를 실행하여 Phase 1 미검증 항목 완료.
2. 프론트엔드 담당자와 API 계약 확정.
3. filters 구현 및 동일 source의 분기/분야/직무 조회.
4. DISTINCT 집계·서울 분기·전분기 비교·다중/대표 분류 정책 구현.
5. dashboard 응답, 근거 없는 통계 unavailable, API·회귀 테스트.

## 8. Git 상태

feature/31-job-trends-backend에서 위 13개 신규 파일만 추가했다.
기존 파일은 수정하지 않았으며 브랜치 생성·변경도 하지 않았다.
Commit·Push·PR 생성·Merge·Issue 종료·Project 상태 변경은 수행하지 않았다.

**완료 판정: 코드·fixture·단위/일부 회귀 검증·문서 작성 완료.
사용자 완료 기준 중 실제 PostgreSQL 적재 및 재현 검증은 환경 제약으로 미완료.**
