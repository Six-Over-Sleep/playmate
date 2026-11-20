# IT 채용 레이더 로컬 CSV 수집과 PostgreSQL 적재

현재 HTTP 헤더·10초 타임아웃·최소 4초 간격·조건부 GET 및 안전한 헤더 진단 명령은
[HTTP 요청 설정과 검증](itchaeyong_http_requests.md)을 참고한다. 아래 과거 재점검 표의
20초/단순 HTML Accept는 당시 비교 결과이며 현재 기본값이 아니다.

## 현재 작업 상태

- 브랜치: `feature/156-itchaeyong-local-csv` (기존 `feature/156-saramin-runpod-csv` 이름 변경).
  이전 미커밋 파일을 보존했다. commit/push/PR/merge/reset/rebase는 수행하지 않았다.
- Windows + PowerShell + Python >=3.13 + uv에서 실행한다. RunPod/GPU/Playwright는 필요 없다.
- 기존 사람인 크롤러와 RunPod 스크립트/문서는 삭제하지 않았다. 이전 경로로 표시해 분리했다.
- 실제 공고 500건 확보는 미완료다. 현재 HTTP 클라이언트의 robots 요청이 403으로 차단되어
  추가 요청을 중단했다. 사이트 원본 HTML 선택자 및 상세 파서는 합성 fixture 기준으로 검증한 상태다.

## 접근 확인 및 실제 실행 제한

### 403 재점검: 2026-11-20 12:08 KST

동일 실행 환경에서 robots.txt 첫 응답만 최대 2회 비교했다. 기본 `requests.get()`은
HTTP 200/text/plain, 수정 전 크롤러의 `load_robots()`는 HTTP 403/접근 제한 HTML을 받았다.
따라서 Python requests 자체가 일괄 차단된다는 해석은 부정확하다. 403 후 추가 사이트 요청은 하지 않았다.
실제 상세 원인은 User-Agent/Accept 중 어느 차이인지 또는 다른 서버 상태인지 아직 확정하지 못했다.

| 설정 | 기본 직접 GET | 수정 전 크롤러 |
|---|---|---|
| URL | `https://itchaeyong.com/robots.txt` | 동일 |
| User-Agent | `python-requests/2.34.2` | `PlaymateResearchBot/1.0 (public HTML compatibility inspection)` |
| Accept | `*/*` | `text/html` |
| Accept-Encoding/Connection | `gzip, deflate` / `keep-alive` | 동일 |
| 리다이렉트 | 비교 시 명시적으로 False | False |
| 세션/환경 | 기본 Session, trust_env=True | 동일 |
| 프록시/인증/쿠키 | 적용 프록시 없음, 인증 헤더 없음, 쿠키 0개 | 동일 |
| timeout | 비교 시 20초 | 20초 |
| 응답 | 200, 접근 제한 화면 아님 | 403, 접근 제한 화면 |

일반 requests.get의 기본 리다이렉트는 True지만 이번 비교는 첫 응답을 분리하기 위해
둘 다 False로 고정했다. 직접 GET이 첫 응답부터 200이므로 리다이렉트 차이는 이번 결과를 설명하지 않는다.
기본 어댑터 retry=0, TLS 인증서 검증 기본값을 유지했다. 프록시/CA/NETRC/ITCHAEYONG_USER_AGENT
관련 환경변수는 이번 셸에서 설정되어 있지 않았다. 비밀값은 출력하지 않았다.
크롤러는 `.env`를 자동 로드하지 않으며 봇 식별자는 CLI 또는 현재 셸의
`ITCHAEYONG_USER_AGENT`에서 온다. DB 모듈은 수집 단계에서 연결하지 않는다.

서버 Date 헤더 기준 응답 시각은 직접 GET 12:08:29 KST, 수정 전 크롤러 12:08:33 KST다.
클라이언트 확인 시각과 원본 응답 메타데이터는 아래 로컬 보고서에 기록했다.
`data/itchaeyong/reports/robots_recheck_20261120T030836640336Z.json`
이전 `access_check_20261120.json`의 `recorded_at`은 진단 파일 작성 시각이며 실제 요청 시각이 아니다.
이전 403은 단발 requests 확인 결과였으므로 크롤러 실행 전체에 대한 검증으로 취급해서는 안 된다.

코드는 robots 요청에만 `Accept: text/plain`을 적용하도록 좁게 수정했다. HTML 요청의
`Accept: text/html`, 실제 봇 User-Agent, 세션·프록시·리다이렉트 설정은 그대로다.
이는 robots의 실제 응답 형식과 다른 Accept를 보내던 부정합 수정이며 **403 해결 검증이 아니다**.
수정 후 실사이트 재요청은 하지 않았다. 특정 봇 식별자에 대한 서버 정책이 원인이면
헤더 변경/기본 requests 식별자로 위장해 우회하지 말고 사이트 운영자의 허용 확인이 필요하다.
새 HTTP 응답 로그는 URL·상태·클라이언트/서버 시각·Accept·Content-Type·접근 제한 여부를
보고서의 `http_responses`에 보존한다. 쿠키/인증/프록시 주소/전체 응답 본문은 저장하지 않는다.

재점검 후 기존 오프라인 테스트 89개와 신규 헤더/403 진단 테스트 2개가 모두 통과했다.
pytest 87개 + 기존 통계 unittest 4개 = 총 91개이며 구문 검사와 `git diff --check`도 통과했다.

접근 및 보관 권한을 확인한 뒤 사용자가 수행할 최소 검증(robots + 목록 최대 2요청):

```powershell
Set-Location 'C:\Users\Playdata\Desktop\playmate\playmate'
$env:ITCHAEYONG_USER_AGENT = 'PlaymateResearchBot/1.0 (contact: YOUR_REAL_EMAIL)'
uv run --frozen python database/scripts/collect_itchaeyong_jobs.py `
  --permission-confirmed --target-count 1 --max-pages 1 --max-requests 2 --list-only --delay 4
```

403/429이면 그 실행으로 중단하며 헤더를 바꾸어 반복하지 않는다. 수집 보고서의
`http_responses`, `status`, `stop_reason`을 확인한다. 이 재점검에서는 `/jobs/dev`와
500건 수집을 실행하지 않았다. 대량 실행 전에는 실제 봇 접근 허용, 수집·보관·재사용 범위,
소규모 HTML 파싱/원문 대조 및 페이지 간 고유 ID 변화 검증이 필요하다.

2026-11-20 공개 [개발 목록](https://itchaeyong.com/jobs/dev)과
[2페이지](https://itchaeyong.com/jobs/dev?page=2)를 웹 조회 도구로 살펴본 결과,
첫 페이지에 50건 및 다음 페이지 링크가 표시되었다. 목록 메타데이터에 회사, 직무,
경력, 지역, 고용 형태와 일부 기술 스택이 보였다. 페이지별 고유 ID 대조와 상세 HTML은 검증하지 못했다.

이어서 로컬 requests 클라이언트가 `https://itchaeyong.com/robots.txt`를 1회 조회했으나
HTTP 403/접근 제한 화면을 받았다. 이 응답 이후 사이트에 추가 요청하지 않았다.
사전 제공된 robots 규칙은 Allow `/`, Disallow `/api/`, `_rsc`, `.rsc`이지만 런타임에 재검증한다.
실행기의 URL 허용 목록은 이 규칙보다 좁게 `/robots.txt`, `/jobs/dev[?page=N]`,
`/jobs/{ID}`만 허용한다. 원본 기업 URL은 저장만 하고 따라가지 않는다.
내부 API 호출·Next.js Flight/RSC 스크립트 해석·브라우저 위장·우회 기능은 없다.

사용자는 수집·보관·재사용 권한을 확인했다고 답변했다. 구체적인 약관/허용 범위 문구는
이 대화에서 제공되지 않았으므로 독립적으로 확인된 권한 문서로 취급하지 않는다.
robots 허용은 데이터 재사용 허가가 아니다. 목록/상세 접근, CSV 보관 기간, DB 적재와 통계
공개 범위를 확인한 경우에만 `--permission-confirmed`를 사용한다. 현재 403이 해결되기 전에는
반복 실행하지 않는다. 관리자에게 접근 허용을 요청하되 제한을 우회하지 않는다.

## 기존 코드 분석과 재사용

기존 사람인 경로는 `config.py` 카테고리 URL → `crawler.py` 페이지 요청 → `parser.py`
카드/직무 추출 → `collect_saramin_jobs.py` → CSV 또는 `saramin_job_postings` UPSERT이다.
별도 `collect_saramin_insights.py`는 데이터 직무 두 개를 각각 15건 선택하고,
`saramin_insight_jobs`에 저장한다. 기존 통계 API도 이 별도 테이블/preview JSON을 사용한다.

이전 작업의 최대 500건, ID 중복 제거, 반복 페이지 탐지, 체크포인트, 원자적 파일 교체,
UTF-8-SIG, JSON 배열, 출력 파일 예약 및 보고서 저장 방식을 재사용했다.
`saramin_csv.py`에 선택적 스키마 인자를 추가했으며 기본 인자는 그대로여서 사람인 호환성을 유지한다.
사람인 전용 ID/도메인·직무 사전·HTML 선택자를 재사용하면 잘못된 분류가 생기므로 새 사이트
파서와 CSV 계약(`itchaeyong_csv.py`)을 분리했다. 신규 수집기는 DB import 옵션 자체가 없다.

## 1. PowerShell에서 작업 폴더 및 의존성 준비

```powershell
Set-Location 'C:\Users\Playdata\Desktop\playmate\playmate'
git branch --show-current
uv --version
uv python install 3.13
uv sync --frozen --python 3.13
$env:PYTHONIOENCODING = 'utf-8'
uv run --frozen python --version
```

Python 3.13 이상이 이미 있으면 `uv python install`은 생략할 수 있다.
`requests`, `beautifulsoup4`, DB 드라이버는 기존 pyproject/lock에 있으며 새 패키지는 추가하지 않았다.
uv가 없다면 공식 [uv 설치 안내](https://docs.astral.sh/uv/getting-started/installation/)에 따라 설치한다.
기존 미커밋 코드이므로 다른 PC에서 clone만 하면 이 변경이 내려오지 않는다.

## 2. 권한과 접근 차단 해소 후 소규모 검증

아래 봇 연락처를 실제 운영자 이메일로 바꾼다. User-Agent는 신원을 숨기기 위한 값이 아니다.

```powershell
$env:ITCHAEYONG_USER_AGENT = 'PlaymateResearchBot/1.0 (contact: YOUR_REAL_EMAIL)'
uv run --frozen python database/scripts/collect_itchaeyong_jobs.py `
  --permission-confirmed --target-count 5 --max-pages 2 --delay 4
```

기본은 공개 상세 HTML도 확인한다. 목록만 허용받았다면 `--list-only`를 지정한다.
소규모 CSV 원문/링크를 눈으로 대조하고, 회사·직무·스택이 다른 공고나 필터 패널에서
유입되지 않았는지 확인한다. 공개 HTML에서 목록이 제공되지 않으면 loading shell로 중단하며,
이 때 API나 RSC로 전환하지 않는다. 마크업이 다르면 실제 허용된 HTML 샘플로 파서를 수정해야 한다.

## 3. 최대 500건 수집

```powershell
uv run --frozen python database/scripts/collect_itchaeyong_jobs.py `
  --permission-confirmed --target-count 500 --max-pages 50 --max-requests 650 --delay 4
```

`--csv`와 `--report`로 출력 경로를 지정할 수 있다. 기존 파일은 거부한다.
기본 결과 파일은 프로젝트 루트 기준 아래에 생성되고 종료 시 **절대경로**를 출력한다.

```text
data/itchaeyong/exports/itchaeyong_jobs_<UTC시각>_<RunID>.csv
data/itchaeyong/reports/collection_report_<UTC시각>_<RunID>.json
```

- 순차 요청, 기본 4초 간격이다. robots의 더 긴 Crawl-delay/Request-rate도 반영한다.
- 기본 요청 예산 650은 500개 상세 + 최대 50개 목록 + robots 1회를 포함할 수 있다.
  상세 모드의 대략적인 실행 시간은 35~45분이나 네트워크/robots 지연에 따라 더 길 수 있다.
- `source_job_id`를 기준으로 중복 제거하고 최대 500개에서 종료한다. 다중 직무는 배열로 보존한다.
- 공개 다음 페이지 링크가 있는 경우에만 순서대로 이동한다. 마지막·빈·반복 페이지에서 종료한다.
- 200 이외 응답/접근 제한 화면/네트워크 오류 시 즉시 중단한다. 429는 재시도하지 않고
  `Retry-After`를 보고서에 남긴다. 표시된 시간 이전 재요청을 하지 않는다.
- 데이터가 부족하면 있는 만큼만 저장한다. `status`, `stop_reason`, `unique_count`,
  `target_reached`와 `achieved_500`을 확인한다. 지정 목표 달성과 500건 달성은 별개다.
- 종료 코드 0은 유효 행이 있는 정상/부분 완료, 2는 요청 중단 또는 0건이다.

## 4. 중단 후 재시작

새 목록 공고를 상세 요청 전에 저장하고, 상세 파싱 후 다시 체크포인트를 저장한다.
임시 파일을 fsync한 후 원자 교체하므로 저장 실패 시 이전 정상 CSV가 남는다.
Ctrl+C/네트워크 중단 시 확보한 공고와 보고서를 마무리한다. 강제 종료/디스크 장애에서는
마지막 성공 체크포인트까지만 보장한다. CSV와 JSON은 각각 원자적이며 한 트랜잭션은 아니다.

```powershell
# 기본 exports 폴더에서 최신 자동 이름 CSV 선택
uv run --frozen python database/scripts/collect_itchaeyong_jobs.py `
  --permission-confirmed --target-count 500 --resume

# 파일을 명시하면 잘못된 실행 결과를 선택할 위험을 줄일 수 있음
uv run --frozen python database/scripts/collect_itchaeyong_jobs.py `
  --permission-confirmed --target-count 500 `
  --resume 'data/itchaeyong/exports/itchaeyong_jobs_PREVIOUS_RUN.csv'
```

이전 CSV 유효성과 고유 ID 수를 확인한 뒤 새 Run ID 파일에 저장한다. 이전 파일은 보존한다.
목록 1페이지부터 다시 읽으면서 이미 확보한 ID를 건너뛴다. 과거 실행의 요청 예산은 별도로
고려해야 하며 제한 회피를 위한 재시작을 해서는 안 된다. 재시작은 미확보 공고를 추가하며
이미 확보한 공고의 실패한 상세를 자동 재시도하지 않는다. 완료된 상세 재보강은 별도 작업이다.

## 5. CSV 확인·검증·복사

```powershell
$csv = Get-ChildItem 'data/itchaeyong/exports/itchaeyong_jobs_*.csv' |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
$csv.FullName
Get-Item -LiteralPath $csv.FullName | Select-Object FullName, Length
uv run --frozen python database/scripts/import_itchaeyong_csv.py $csv.FullName
$rows = @(Import-Csv -LiteralPath $csv.FullName -Encoding UTF8)
$unique = @($rows.source_job_id | Sort-Object -Unique)
"행 수: $($rows.Count) / 고유 ID: $($unique.Count) / 500건 달성: $($rows.Count -eq 500 -and $unique.Count -eq 500)"
Get-FileHash -LiteralPath $csv.FullName -Algorithm SHA256
Invoke-Item 'data/itchaeyong/exports'
```

탐색기에서 CSV를 열거나 다른 폴더로 복사하면 된다. UTF-8-SIG로 Excel 한글 표시를 지원한다.
배열은 JSON 문자열이므로 Python 검증기가 문자열 배열·날짜·ID·출처·NULL을 복원한다.
CSV의 빈 셀은 NULL, 관측된 빈 배열은 `[]`이다. CSV/보고서는 Git ignore 대상이다.

보고서는 직무·기술·회사별 분포, 페이지별 후보/추가/누적 수, 필수 및 주요 컬럼 누락률,
오류 페이지/단계, 시작·종료, 요청 수, SHA256/크기를 포함한다. `collected_count`는 반복을
포함한 목록 후보 수이고 `unique_count`는 재시작 파일을 포함한 최종 고유 행 수다.
분포의 다중 직무 합계는 공고 수보다 클 수 있다. `Retry-After`가 있으면 별도로 확인한다.

## 6. CSV 컬럼 및 DB 매핑

CSV와 신규 DB 테이블은 동일 컬럼명을 사용한다. `id`, `first_seen_at`, `last_seen_at`은 DB 관리용이다.

| CSV/DB 컬럼 | 의미/형식 | 통계 어댑터 |
|---|---|---|
| source | 고정 `itchaeyong` | source |
| source_job_id | 공개 상세 URL에서 확인한 ID | source_id |
| job_url | 정규화된 IT 채용 레이더 상세 URL | 원본 출처 유지 |
| original_url | HTML에 명시된 기업 공식 공고 URL, 미확보 시 NULL | 별도 보존 |
| company_name | 카드/상세에 표시된 회사 | company |
| job_title | 실제 제목 | 별도 보존 |
| job_category | 요청 출처 `dev` | specialties=`[dev]`, categories |
| job_role | 실제 카드 직무 메타데이터, JSON 배열 → TEXT[] | job_roles |
| experience | 실제 경력 원문 | career |
| employment_type | 고용형태 원문 | 별도 보존 |
| location | 지역 원문 | location |
| tech_stack | 명시된 스택만, JSON 배열 → TEXT[] | tech_stacks |
| requirements | 자격요건 문단, JSON 배열 → TEXT[] | 별도 보존 |
| preferred_qualifications | 우대사항 문단, JSON 배열 → TEXT[] | preferences |
| posted_at | 절대 게시일이 확인될 때만 TIMESTAMPTZ | posting_trend |
| deadline_at | 절대 마감일이 확인될 때만 TIMESTAMPTZ | 별도 보존 |
| collected_at | 실제 관측 시각(UTC), TIMESTAMPTZ | 수집 스냅샷 분기 |
| detail_status | 미요청/실패/파싱/메타데이터 없음 | 별도 보존 |

제목에서 기술/직무를 추측하지 않는다. 직무가 없으면 `[]`로 두되 `/jobs/dev`에서 얻은
범위 정보만 보존한다. `N일 전`, `D-N`으로 게시일/마감일을 만들어내지 않는다.
명시된 날짜에 시간대가 없으면 한국 서비스 문맥에 맞춰 KST로 해석 후 UTC로 변환한다.
원문 자격증·급여가 확인되지 않았으므로 별도 값은 생성하지 않는다. 상세 JSON-LD의
JobPosting과 보이는 자격요건/우대사항 문단만 파싱한다. iframe·이미지·로그인 뒤 정보는 추출하지 않는다.

## 7. 향후 PostgreSQL 준비와 Preview

별도 `itchaeyong_job_postings` 테이블을 사용하며 사람인 두 테이블과 데이터는 변경하지 않는다.
SQL 파일 `database/sql/037_itchaeyong_job_postings.sql`은 기존 프로젝트의 명시적 SQL 적용 방식이다.
운영 RDS는 Private Subnet이므로 로컬에서 직접 연결을 전제로 하지 않는다.
CSV를 승인된 방법으로 EC2에 복사한 뒤 EC2에서 아래 작업을 수행한다.

DB 설정은 기존 backend의 `.env` 또는 `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`,
`DB_PASSWORD`, `DB_SSLMODE=require` 환경변수를 사용한다. 비밀값은 이 문서/명령행/Git에 넣지 않는다.
CSV 검증에는 DB 설정이 필요 없다. 테이블 준비 및 실제 적재는 운영 승인 이후에만 실행한다.

```powershell
# 승인된 DB 환경에서 별도로 스키마 준비 (이번에는 미실행)
uv run --frozen python database/scripts/apply_itchaeyong_migration.py
# 검증만: DB 연결 없음
uv run --frozen python database/scripts/import_itchaeyong_csv.py $csv.FullName
# 준비된 테이블에서 읽기 전용 예상 신규/갱신/중복 제외 확인
uv run --frozen python database/scripts/import_itchaeyong_csv.py $csv.FullName --preview-db
# 운영 적재 승인 이후에만
uv run --frozen python database/scripts/import_itchaeyong_csv.py $csv.FullName --apply
```

기본 모드는 DB를 읽지 않으므로 신규/갱신은 미확정이다. `--preview-db`는
REPEATABLE READ READ ONLY 트랜잭션에서 키를 비교하며 쓰기/커밋은 없다. `--apply`와 동시 지정은 금지한다.
CSV 전체를 검증한 뒤 `(source,source_job_id)` 중복을 제거하고 파라미터 바인딩 UPSERT를 수행한다.
NULL 메타데이터는 기존 값을 유지하고 배열은 합집합으로 보존한다. 첫 관측 `collected_at`을 유지하고
`last_seen_at`을 갱신한다. 더 풍부한 상세 상태를 실패 상태로 덮어쓰지 않는다.
보존 정책상 과거 기술이 남을 수 있어 최신 유효 상태만 필요하면 별도 이력/만료 정책이 필요하다.
advisory lock으로 적재끼리 직렬화하며 결과 키 검증까지 같은 트랜잭션이다. 오류 시 전체 롤백한다.
테이블 삭제/초기화는 없다. 실제 운영 DB 연결/Preview/마이그레이션/적재는 이번에 실행하지 않았다.

## 8. 기존 통계 API 연결

- 새 출처 명시: `/api/career/insights/itchaeyong/filters`, `/api/career/insights/itchaeyong/summary`.
- 기존 `/db/*` 및 `/summary`, `/filters` 경로는 기본적으로 사람인 테이블을 그대로 사용한다.
- 새 테이블이 준비되고 데이터가 적재된 후 backend 환경변수
  `CAREER_INSIGHTS_DB_SOURCE=itchaeyong`으로 기존 DB 경로의 데이터 출처를 전환할 수 있다.
  이 변수는 허용된 두 출처만 선택하며 SQL 테이블명을 입력으로 받지 않는다.
- 기존 roles/fields/skills/coverage/trend 구조를 보존하고 companies/categories/experience/locations,
  role_skills/data_sources를 추가했다. 집계는 출처+공고 ID 중복을 제거한다.
- `trend`는 항상 `trend_basis=collection_snapshot`으로 명시한다. 단일 시점 500건을 과거 수요로
  설명하지 않는다. 실제 `posted_at`이 있는 공고만 별도 `posting_trend`에 집계하고
  `posted_at_coverage`를 함께 제공한다. 기존 quarter 필터는 계속 수집 분기 기준이다.
  게시 분기는 KST(`posting_trend_timezone=Asia/Seoul`)를 기준으로 계산해 날짜만 제공된
  한국 공고의 분기 경계가 UTC 변환 때문에 이전 분기로 바뀌지 않도록 한다.
- 기존 프론트엔드 디자인은 변경하지 않았다. 사용자에게 보이는 추세 이름과 새 분포 표시,
  게시 분기 필터 UX는 필요 시 별도 후속 작업으로 진행한다.

## 9. 오프라인 검증

```powershell
uv run --frozen --with pytest python -m pytest crawler/itchaeyong_crawler/test crawler/saramin_crawler/test -q
uv run --frozen python -m unittest backend.tests.test_career_insight_preview -q
git diff --check
```

모든 신규 테스트는 합성 HTML 또는 가짜 HTTP/DB 응답을 사용한다. 합성 데이터를 실수집 CSV로
만들어 배포하지 않는다. 실제 사이트 HTML/페이지 간 ID 차이/실제 PostgreSQL SQL 실행은
현재 차단 상태로 미검증이다. 권한과 접근 문제가 해결된 후 소규모 표본부터 검증해야 한다.

2026-11-20 Windows/Python 3.13.14에서 신규 테스트 42개 + 사람인 테스트 43개 = pytest 85개,
기존 통계 미리보기 unittest 4개가 통과했다(총 89개). 구문 검사와 `git diff --check`도 통과했다.
테스트 의존성은 기존 별도 `.testdeps-saramin` 폴더를 사용했고 pyproject/uv.lock은 변경하지 않았다.
위 `uv sync --frozen`은 사용자 로컬 환경 준비 명령이며 이번 작업에서 재실행하지 않았다.
전체 backend 테스트나 실제 DB SQL 실행을 검증한 결과는 아니다.

이번 실제 접근 확인 보고서는 `data/itchaeyong/reports/access_check_20261120.json`이다.
이 파일은 robots 403 진단이며 수집 보고서/실제 공고 CSV를 대신하지 않는다. 실제 수집 CSV,
CSV SHA256 및 실제 데이터 누락률은 아직 없다.

이번 전환의 신규/수정 파일:

- 신규 사이트 모듈: `crawler/itchaeyong_crawler/{__init__,crawler,parser}.py`, `test/test_pipeline.py`
- 로컬 CLI/CSV/적재: `database/scripts/collect_itchaeyong_jobs.py`, `itchaeyong_csv.py`,
  `import_itchaeyong_csv.py`, `apply_itchaeyong_migration.py`
- 공통 저장 재사용: `database/scripts/saramin_csv.py` (기존 기본 계약 유지)
- 신규 스키마: `database/sql/037_itchaeyong_job_postings.sql`
- 통계 연결: `backend/app/routers/career_insights.py`, `backend/app/services/career_insight_stats.py`
- 문서/실행 분리: 이 문서, `crawler/README.md`, `docs/runpod_saramin_collection.md`,
  `scripts/runpod/collect_saramin.sh`, `.gitignore`
- 이전 사람인 크롤러·수집/적재 스크립트·테스트의 미커밋 변경은 그대로 보존했다.

## 10. 챌린지 판정 개선과 실제 응답 진단 (2026-11-20 12:42 KST)

### 판정 로직 변경

- 기존: 응답 전체 문자열에서 `cf-chl-`, `/cdn-cgi/challenge`, `<title>Just a moment` 정규식 검색.
  HTML 주석이나 Cloudflare가 **정상 페이지에도 삽입하는 수동 스크립트**
  (`/cdn-cgi/challenge-platform/scripts/jsd/main.js`)만 있어도 차단으로 오판할 수 있었다.
- 변경: `crawler/itchaeyong_crawler/page_check.py`의 `classify_page()`가 DOM으로 판정한다.
  주석 제거 후 `<title>`, 챌린지 요소 id(`challenge-form`, `challenge-running`, `challenge-error-text` 등),
  `__cf_chl` form action, `_cf_chl_opt`/`challenge-platform/h/` orchestrate 스크립트, Turnstile 위젯을
  강한 근거로, jsd 수동 스크립트는 약한 근거(기록만)로 분류하고 `/jobs/{ID}` 링크 수를 함께 본다.
  - `CHALLENGE_PAGE`: 강한 근거 있음 + 채용 콘텐츠 없음 → 기존처럼 즉시 중단(우회·재시도 없음)
  - `NORMAL_PAGE`: 강한 근거 없음 + 공고 링크(목록) 또는 JobPosting JSON-LD/`main h1`(상세)
  - `UNKNOWN_PAGE`: 둘 다 없거나 둘 다 있음 → 정상/차단 어느 쪽으로도 확정하지 않고 `UNKNOWN_PAGE` 사유로 중단
- 목록이 NORMAL인데 파서가 0건이면 `파서 불일치: 공고 링크 N개, 추출 0건`으로 중단한다(로딩 셸로 오표기하지 않음).
- 상세가 NORMAL이 아니면 목록 행을 유지하고 `detail_status=unverified_page`로 저장, 상세 값은 병합하지 않는다.
- `http_responses`에 `page_verdict`, `page_reason`, `html_title`, `body_bytes`, `job_link_count`,
  `challenge_evidence`, `passive_evidence`를 추가했다. 기존 `challenge_html`은 `page_verdict == CHALLENGE_PAGE`.

### 진단 도구

- `database/scripts/diagnose_itchaeyong_html.py`: 기본은 `data/itchaeyong/debug/`의 최신 저장 HTML을
  **네트워크 요청 없이** 재분석한다. 저장본이 없으면 요청하지 않고 종료한다.
  `--fetch --permission-confirmed --user-agent`일 때만 robots.txt + `/jobs/dev` 최대 2요청.
- 수집 CLI `--debug-html`: 각 응답 본문을 `data/itchaeyong/debug/<run_id>/`에 저장한다.
  응답 헤더/쿠키는 저장하지 않고 `__CF$cv$params`, `_cf_chl_opt`, `__cf_chl_*`, `ray=`, nonce,
  csrf/token/session 입력값을 마스킹한다. `data/itchaeyong/`은 `.gitignore` 대상이다.

### 0건 처리

- 0건이면 `CSV 저장 완료` 대신 `수집 실패: 실제 채용공고 0건 / CSV 데이터 없음 / 실패 원인: ...`을 출력하고
  종료 코드 2를 반환한다. 헤더만 있는 파일은 `itchaeyong_EMPTY_<run_id>.csv`로 이름을 바꿔
  `--resume latest`와 구분하며 보고서에 `csv_kind=empty_diagnostic`을 기록한다.
- `import_itchaeyong_csv.py`는 유효 0건 CSV를 `--preview-db`/`--apply` 포함 모든 모드에서 DB 연결 전에 거부(코드 2)한다.
- 이전 실행에서 남은 `itchaeyong_jobs_20261120T03*.csv` 3개(헤더만)는 사용자 파일이므로 이름을 바꾸지 않았다.
  DB 적재기는 이 파일들도 거부한다.

### 실제 응답 결과(실측)

정직한 봇 UA `PlaymateResearchBot/1.0 (student project; public HTML, low rate)`로 1회 요청:

| URL | 상태 | Content-Type | title | 판정 근거 | 판정 |
|---|---|---|---|---|---|
| `/robots.txt` | 403 | text/html | `Just a moment...` | title, `#challenge-error-text`, orchestrate 스크립트, 공고 링크 0 | CHALLENGE_PAGE |

- 첫 요청에서 중단(요청 1회). `/jobs/dev`, 상세, 1건/5건 수집은 실행하지 않았다.
- 저장본: `data/itchaeyong/debug/diag_20261120T034246068377Z/001_robots_txt_403.html`(마스킹),
  보고서: `data/itchaeyong/reports/html_diagnosis_20261120T034324303654Z.json`.
- 이전 `UA=TEST` 실행의 `/jobs/dev` 200 응답 본문은 저장되지 않아 당시 판정이 오탐이었는지는 확정할 수 없다.
  다만 구 정규식은 정상 페이지에 삽입되는 jsd 스크립트만으로도 참이 되므로 오탐 가능성이 높다.
- 봇 식별 UA에는 Cloudflare 챌린지가, 비식별 UA(`TEST`)에는 200이 반환된 것은 사이트(또는 Cloudflare 봇 정책)가
  자동화 클라이언트를 제한한다는 신호다. UA를 바꾸어 통과하는 것은 접근통제 우회이므로 하지 않는다.
  운영자에게 봇 허용(허용 UA/IP, 요청 빈도)이나 데이터 제공 경로(제휴/피드/API 키)를 문의해야 한다.

### 검증

pytest 106개(신규 19 + 기존 itchaeyong 44 + 사람인 43) + 통계 unittest 4개 = 110개 통과, `git diff --check` 통과.
신규 테스트의 HTML은 구조를 본뜬 **합성 fixture**이며 실제 사이트 응답 검증은 위 표의 1건뿐이다.
