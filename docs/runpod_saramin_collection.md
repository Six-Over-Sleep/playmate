# RunPod 사람인 CSV 수집 및 EC2 적재

> 이전 사람인 작업의 보존 문서입니다. 현재 #156의 실행 경로는 RunPod을 사용하지 않는
> [IT 채용 레이더 로컬 수집](itchaeyong_local_collection.md)입니다.

## 현재 상태와 수집 권한 (2026-11-20 확인)

이 브랜치는 HTML 수집 파이프라인 구현과 오프라인 검증용이다. 실제 공고 500건을
확보했다는 뜻이 아니다. 운영 DB 접속, RunPod 유료 리소스 생성, 키 등록은 수행하지 않았다.

- [서비스 이용자 주의사항](https://oapi.saramin.co.kr/caution)은 일 공고 호출 수 최대
  500건으로 표현한다. [API 명세](https://oapi.saramin.co.kr/guide/job-search)는 오류 코드 4를
  일일 최대 요청 횟수 초과로 설명한다. 두 표현만으로 호출/반환 공고 단위를 확정할 수 없다.
  서비스 담당자에게 단위·중복 반환·타 실행 합산·일일 초기화 시간대를 확인해야 한다.
- 공식 API는 앱 등록 및 access-key 발급이 필요하다. 승인 상태/키 사용 가능 여부는 확인하지
  않았으며 비밀 파일을 읽지 않았다. API는 `start` 0 기반, `count` 기본 10/최대 110이며
  `job_mid_cd`와 직무 코드 검색, 게시일/급여를 지원한다. 승인 후 공식 API를 우선 검토한다.
  이 변경에는 API 클라이언트를 구현하지 않았다. HTML의 `page`와 API의 `start`를 혼용하지 않는다.
- API 권한이 HTML 목록·상세 수집 권한을 의미하지 않는다. HTML 자동수집, CSV 보관,
  통계 분석 및 보유 기간, 상세페이지 접근에 대한 허용 범위를 별도로 확인해야 한다.
  API 문서만으로 CSV 저장 및 통계 분석의 포괄적 허가를 확정하지 않았다.
- 이번 조사에서 robots.txt는 웹 조회 도구로 접근할 수 없었다. 실제 수집은 수행하지 않았다.
  런타임은 robots.txt를 직접 확인하고 실패/차단 시 중단한다. robots 허용만으로 약관 승인이 되지 않는다.
- `--permission-confirmed`는 사용자가 별도 허가를 확인했다는 명시적 표시이며 허가를 대신하지
  않는다. 권한을 확인하기 전에는 아래 실제 수집 명령을 실행하지 말고 오프라인 테스트만 실행한다.
- 401/403/429, 리디렉션, 네트워크 오류가 발생하면 전체 수집을 중단한다. 프록시·인증·CAPTCHA
  우회가 없다. 차단 후 재시작으로 제한을 회피하지 않는다.

## 기존 코드 분석

`config.py`의 HTML 카테고리 URL(`cat_mcls=2`) → `crawler.py`의 `page=1..max_pages`
요청 → `parser.py`의 카드/링크 추출·IT 분류 → `collect_saramin_jobs.py` →
`import_saramin_jobs.py` → `020_saramin_job_postings.sql` 테이블 순서다.
`apply_saramin_migration.py`는 기존 스키마 적용용이며 이번에는 실행하거나 변경하지 않았다.

약 30건의 직접적인 선택 제한은 별도 `collect_saramin_insights.py`의
`TARGETS=('데이터분석가','데이터엔지니어')`, `--per-role=15`이다.
일반 크롤러의 기본 `max_pages=3`도 요청 범위를 제한하지만 페이지당 수와 IT 필터에 따라
결과는 달라지므로 그 자체가 30건을 보장하지 않는다. 새 CSV 경로에는 직무별 할당 제한이 없다.
기존 insights 스크립트의 기능과 두 직무 기본값은 호환성을 위해 유지했다.

ID는 카드 속성 또는 `rec_idx`/`recruit_idx` 쿼리에서 추출한다. 직무 태그를 우선하고,
없으면 제목을 사용해 `title_estimate`로 표시한다. 불명확한 공고는 제외한다.
기존 사전에 DevOps·풀스택·AI·클라우드 직무 및 QA/시스템/보안 표현을 보완했다.
기술 스택은 실제 카드·상세 텍스트와 사전을 매칭하며 직무·전문분야와 구분한다.
우대사항은 인식 가능한 HTML 제목 주변 문단만 추출한다. iframe·이미지·로그인 뒤
내용은 가져오지 않으며 기술/자격증/우대사항을 추정해 채우지 않는다.

기존 상세 파서는 HTML 내 구조화 데이터와 넓은 본문을 검사할 수 있어 사이트 변경이나
추천 공고가 섞인 구조에서는 오탐 검토가 필요하다. 수집 결과는 원문과 표본 대조해야 한다.
현행 HTML에서 페이지 파라미터가 실제 다른 공고를 반환하는지는 권한 미확인으로 미검증이다.
새 코드는 전체 후보 ID 집합 반복을 감지하고 보고한다. IT 필터 탈락 수는 페이지별
`candidate_count`, `passed_count`, `filtered_count`에 실제 실행 결과로 기록한다.

## 1. Pod 생성과 터미널 접속

1. RunPod 계정에 로그인하고 **Pods → Deploy → CPU**를 선택한다.
2. 작은 CPU 인스턴스(권장 2 vCPU/4GB 메모리, 저장 공간 10GB 이상)를 선택한다.
   HTTP 요청만 사용하므로 GPU/CUDA는 필요 없다. CPU 상품 가용성과 비용은 콘솔에서 확인한다.
3. Python 3.13 이상을 설치할 수 있고 Bash/Git/curl이 있는 Linux 템플릿을 고른다.
   템플릿의 기본 Python이 낮아도 uv로 3.13을 별도 설치할 수 있다.
   장기 보관이 필요하면 `/workspace`에 영속 스토리지를 연결한다.
4. 비용을 확인한 뒤 사용자가 **Deploy On-Demand**를 클릭한다.
5. 생성한 Pod를 펼치고 **Connect → Start → Open Web Terminal**로 접속한다.
   오래 실행할 때는 Connect의 SSH 안내와 `tmux`를 사용한다.

UI 근거: [Pod 관리](https://docs.runpod.io/pods/manage-pods),
[접속 방법](https://docs.runpod.io/pods/connect-to-a-pod).

## 2. 코드 가져오기 및 Python 준비

현재 변경은 로컬 미커밋 상태다. 아래 원격 브랜치 체크아웃은 사용자가 변경을 검토하고
별도로 commit/push한 뒤에만 가능하다. 이 작업에서는 commit/push하지 않았다.
그 전에는 로컬 작업 파일을 안전한 SSH 전송으로 Pod에 옮겨야 한다(.env와 키 제외).

```bash
cd /workspace
git clone https://github.com/Six-Over-Sleep/playmate.git
cd playmate
git checkout feature/156-saramin-runpod-csv
# uv가 없다면 공식 설치 프로그램 내용을 검토한 후 설치
curl -LsSf https://astral.sh/uv/install.sh -o /tmp/install-uv.sh
sh /tmp/install-uv.sh
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.13
uv sync --frozen --python 3.13
uv run --frozen python --version
```

기존 `pyproject.toml`은 Python >=3.13, requests/BeautifulSoup/psycopg2 등을 포함한다.
GPU 라이브러리는 추가하지 않았다. lock 파일은 변경하지 않았으며 패키지 설치 시점의
가용성은 Pod에서 확인해야 한다. CSV 생성은 DB 모듈을 연결하거나 DB 환경변수를 요구하지 않는다.

## 3. 권한 확인 후 수집 실행

연락처는 실제 운영자 주소로 바꾼다. 브라우저 User-Agent를 사칭하지 않는다.
환경변수 기본값은 CLI로 재정의할 수 있다.

```bash
export SARAMIN_USER_AGENT='PlaymateResearchBot/1.0 (contact: YOUR_REAL_EMAIL)'
export SARAMIN_TARGET_COUNT=500
export SARAMIN_MAX_PAGES=50
export SARAMIN_MAX_REQUESTS=100
bash scripts/runpod/collect_saramin.sh --permission-confirmed --delay 3
```

자동 생성 경로:

```text
data/saramin/exports/saramin_jobs_<UTC시각>_<RunID>.csv
data/saramin/reports/saramin_collection_<UTC시각>_<RunID>.json
```

명시적 경로 예시(존재하는 파일은 거부):

```bash
bash scripts/runpod/collect_saramin.sh --permission-confirmed \
  --target-count 500 --max-pages 50 --max-requests 100 --delay 3 \
  --csv data/saramin/exports/my_run.csv \
  --report data/saramin/reports/my_run.json
```

상세 허가까지 별도로 확보했을 때만 `--details --details-permission-confirmed`를 추가한다.
robots 요청과 상세 요청도 최대 요청 수에 포함된다. 상세 모드 500건은 요청 예산에 걸릴 수 있다.
HTML 권한에서 허용한 상한보다 CLI 상한을 높이지 않는다. 공식 API의 일일 제한과 이 HTML
요청 상한은 별개이며, 이 프로그램은 API의 일일 사용량을 계산하지 않는다.

최대 500개 고유 ID에서 종료한다. 데이터 부족 시 실제 확보량만 저장한다.
보고서의 `target_reached`는 지정 목표 달성 여부이고, 500건 확보 여부는 `unique_count == 500`으로 확인한다.
정상 부분 완료는 유효 행이 있으면 종료 코드 0, 요청 차단/네트워크 중단 또는 0건이면 2다.
페이지 로그에서 후보·직무 통과·제외·누적 고유 건수를 확인할 수 있다.

기존 `--output` JSON, 명시적 `--apply` 적재 기능은 유지하지만 RunPod에서는 `--apply`를 사용하지 않는다.
기존 호출도 이제 권한 확인과 봇 식별자 옵션이 필요하다. Python `crawl(max_pages, details)` 호출은 유지된다.

## 4. 중간 저장과 재시작

새 공고 처리 후 CSV를 임시 파일에 쓰고 원자적으로 교체한다. Ctrl+C/네트워크 오류 때도
정상 목록 데이터와 최종 보고서를 저장한다. 강제 종료는 마지막 체크포인트까지 보장한다.
디스크 부족/권한 오류 때는 이전의 정상 CSV를 보존하나 최신 공고 저장은 보장할 수 없다.
보고서와 CSV는 각각 원자적이며 두 파일 전체가 하나의 트랜잭션은 아니다.

재시작은 이전 파일을 읽고 **새 Run ID 파일**에 저장한다. 이전 CSV와 보고서는 보존한다.
페이지 1부터 다시 읽되 기존 ID를 제외한다. 사이트의 현재 공고 순서가 바뀔 수 있으므로
동일 시점의 완전한 스냅샷 복원은 보장하지 않는다. 차단 중에는 재시작하지 않는다.

```bash
bash scripts/runpod/collect_saramin.sh --permission-confirmed \
  --resume data/saramin/exports/my_run.csv --target-count 500
```

CSV는 UTF-8-SIG, 21개 고정 컬럼, 배열은 JSON, 누락 문자열은 빈 셀(NULL 대응),
관측된 빈 배열은 `[]`이다. 분기/수집일은 새 수집의 경우 UTC 기준이며 DB의 기존 TIMESTAMP
스키마에 맞춰 UTC naive datetime으로 기록한다. 게시일과 급여는 현재 HTML 파서에서
신뢰할 수 있게 확보하지 못해 추가하지 않았다. 수집 분기를 게시 분기라고 해석하면 안 된다.

## 5. 파일과 500건 확인

```bash
export CSV_FILE=data/saramin/exports/my_run.csv
uv run --frozen python database/scripts/import_saramin_csv.py "$CSV_FILE"
uv run --frozen python - <<'PY'
import csv, hashlib, os
from pathlib import Path
p = Path(os.environ['CSV_FILE'])
with p.open(encoding='utf-8-sig', newline='') as f:
    rows = list(csv.DictReader(f))
ids = {r['source_id'] for r in rows}
with p.open('rb') as f:
    digest = hashlib.file_digest(f, 'sha256').hexdigest()
print('bytes:', p.stat().st_size, 'rows:', len(rows), 'unique:', len(ids))
print('500건 확보:', len(rows) == len(ids) == 500)
print('sha256:', digest)
assert len(rows) == len(ids) <= 500
PY
cat data/saramin/reports/my_run.json
```

기본 자동 파일명을 사용했다면 `ls -lt data/saramin/exports`에서 파일명을 확인해 위 변수를 바꾼다.
보고서에는 실행 ID, 목표/달성, 후보/필터/중복, 직무·기술 분포, 추출 성공/누락,
필수 항목 누락률, 페이지별 건수, 요청 수, 중단 사유, 소요 시간, CSV 행 수/크기/SHA256이 있다.
`collected_count`는 페이지에서 관측한 유효 후보 합계로 반복 후보도 포함하며,
`unique_count`는 재시작 파일을 포함한 최종 고유 행 수다. 직무별 합계는 다중 직무 때문에
전체 공고 수보다 클 수 있다. 페이지 필터 통과 수는 목표 도달 후 미저장 후보도 포함할 수 있다.

## 6. 다운로드와 백업

JupyterLab이 있는 템플릿이라면 **Connect → HTTP Services → Jupyter Lab**을 열고
파일 탐색기에서 `data/saramin`의 CSV/JSON 파일을 우클릭해 **Download**한다.
JupyterLab이 없다면 직접 TCP SSH가 구성된 Pod의 Connect 화면에서 호스트·포트·키를 확인하고
**로컬 컴퓨터 터미널**에서 실행한다(아래 값은 실제 접속 정보로 바꾼다).

```bash
scp -P YOUR_TCP_PORT -i YOUR_KEY root@YOUR_HOST:/workspace/playmate/data/saramin/exports/my_run.csv .
scp -P YOUR_TCP_PORT -i YOUR_KEY root@YOUR_HOST:/workspace/playmate/data/saramin/reports/my_run.json .
```

RunPod SSH 프록시 주소는 SCP를 지원하지 않을 수 있으므로 직접 TCP SSH를 사용한다.
다운로드 파일의 SHA256을 보고서 및 Pod 파일과 비교한다. Linux는 `sha256sum`, Windows
PowerShell은 `Get-FileHash .\my_run.csv -Algorithm SHA256`을 사용한다.
CSV 유효성 검사도 로컬에서 다시 실행한다. 생성 데이터는 Git ignore 대상이며 강제 추가하지 않는다.

## 7. 추후 EC2에서 PostgreSQL 적재

흐름은 RunPod → 다운로드/검증 → EC2 → Private Subnet RDS다. RunPod에서 RDS 연결을 열지 않는다.
이 작업에서는 운영 적재를 실행하지 않았다. 기존 020 스키마가 적용된 승인된 환경에서 사용한다.
`apply_saramin_migration.py`는 별도 관리 작업이며 수집/CSV 검증에 필요하지 않다.

```bash
# EC2에서: 기본 모드는 DB 연결도 변경도 없음
uv run --frozen python database/scripts/import_saramin_csv.py /secure/path/my_run.csv
# 별도 권한으로 DB를 읽어 예상 INSERT/UPDATE 확인 (쓰기 없음)
uv run --frozen python database/scripts/import_saramin_csv.py /secure/path/my_run.csv --preview-db
# 승인된 적재 시에만 실행
uv run --frozen python database/scripts/import_saramin_csv.py /secure/path/my_run.csv --apply
```

기본 모드에서는 실제 DB 존재 여부를 모르므로 예상 신규/갱신은 미확정으로 출력한다.
`--preview-db`는 읽기 전용 트랜잭션에서 실제 기존 키를 비교한다(적재 시점과의 차이 가능).
DB 연결 설정은 기존 backend 모듈의 `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`,
`DB_PASSWORD`, `DB_SSLMODE=require`를 환경변수로 공급한다. 키나 DB 비밀번호를 명령행,
코드, Git에 넣지 않는다. EC2에서만 비밀 저장소 등 승인된 방식으로 제공한다.

전체 CSV를 먼저 검증한 뒤 ID 중복을 제거한다. 날짜/분기, JSON 문자열 배열, 필수 헤더,
사람인 URL/ID를 검사한다. 기존 `(source,source_id)` UPSERT 및 advisory lock을 재사용한다.
배열은 기존 관측값과 합치고 NULL 스칼라는 기존 값을 유지한다. 상세 미수집/실패/빈
우대사항으로 기존 상세 정보를 지우지 않는다. 첫 수집일·분기를 유지하고 `last_seen_at`을 갱신한다.
보존 정책상 제거된 기술도 남을 수 있어 최신 상태만의 통계에는 별도 이력 설계가 필요하다.
하나의 트랜잭션으로 실행하고 결과 키가 존재하는지 확인하며 예외 시 전체 롤백한다.
DB 연결·SELECT·INSERT·UPDATE·시퀀스 권한 부족은 예외로 종료한다. 테이블 삭제/초기화는 없다.

## 8. 기존 통계 호환성과 후속 작업

현재 `/api/career/insights/*`는 `saramin_insight_jobs` 또는 기존 preview JSON을 사용한다.
CSV 적재 대상 `saramin_job_postings`와 다르므로 적재만으로 화면이 바뀌지 않는다.
배열/ID/분기 형태는 공통 집계 함수와 호환되지만 자격증 컬럼/연결은 별도 작업이 필요하다.

- 직무별 수는 공고 ID를 중복 제거한 뒤 직무 배열별로 집계한다.
- 스택 빈도·직무별 스택 분포는 관측된 배열만 펼쳐 집계한다.
- 신입/경력은 원문 `career`에 무관·혼합을 포함해 별도 분류 규칙을 정해야 한다.
- 현재 분기는 수집일 기준이다. 원본 게시일은 확보하지 못했으므로 게시 분기별 수요를 계산할 수 없다.
- 후속 작업: 승인된 API 도입, 게시일/급여 스키마, 자격증 근거 추출, 통계 테이블 또는 뷰 연결,
  경력 비율과 직무×스택 API, 화면 데이터 소스 전환. 프론트엔드는 이번에 변경하지 않았다.
- 이슈 #156 제목 1,000건 / 본문 300건 불일치는 수정하지 않았으며 이번 목표는 최대 500건이다.

## 9. 오프라인 테스트 및 Pod 종료

```bash
uv run --frozen --with pytest python -m pytest crawler/saramin_crawler/test -q
uv run --frozen python -m unittest backend.tests.test_career_insight_preview -q
```

신규 테스트 데이터는 명시적인 합성 HTML fixture이며 실제 수집 데이터로 배포하지 않는다.
테스트는 HTTP/DB를 모의 처리한다. 실사이트 페이지 이동, Linux Pod, 실제 PostgreSQL SQL 실행은
별도 승인 환경에서 검증해야 한다.

2026-11-20 Windows/Python 3.13.14 검증 결과: 크롤러 테스트 43개 PASS
(기존 7개 + 신규 36개), 기존 통계 미리보기 unittest 4개 PASS. 합계 47개다.
별도 `.testdeps-saramin`에 설치한 pytest/HTTP/파서/DB 드라이버로 실행했으며 기존 가상환경과
lock 파일을 변경하지 않았다. `compileall` 및 `git diff --check`도 통과했다.
처음 테스트 의존성 누락·드라이버 버전 불일치를 해결한 뒤 재검증한 결과다.
전체 backend 테스트/운영 통합 테스트 및 RunPod의 `uv sync --frozen` 실행은 수행하지 않았다.

수집 프로세스 종료 후 CSV와 JSON을 외부로 다운로드하고 해시/행 수를 확인한 다음,
Pods에서 Pod를 펼쳐 **Stop**으로 중지한다. 더 필요 없으면 **Terminate(휴지통)**를 선택한다.
중지 상태에서도 저장 공간 비용이 남을 수 있다. **Stop/Terminate/설정 변경 전에 반드시
외부 백업을 완료한다.** 볼륨 유지 여부를 확인하고 결과 파일이 Pod에만 남지 않게 한다.
