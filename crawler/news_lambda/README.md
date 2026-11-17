# 뉴스 수집·전처리 Lambda (Issue #133)

```
EventBridge Scheduler → Collector Lambda(collector_handler.lambda_handler) → S3 raw/news/YYYY/MM/DD/<run_id>.json
    → S3 ObjectCreated(접두사 raw/news/, 접미사 .json) → Processor Lambda(processor_handler.lambda_handler)
    → S3 processed/news/YYYY/MM/DD/<run_id>.json
```

범위는 **Collector·Processor Lambda 코드 + 로컬 단위 테스트**입니다. EventBridge·S3 이벤트·IAM 등 AWS 리소스 생성과 DB 적재는 포함하지 않습니다.

## 파일

| 파일 | 역할 |
|---|---|
| `collector_handler.py` | Collector 진입점. 수집·raw 문서·S3 업로드 |
| `processor_handler.py` | Processor 진입점. S3 이벤트 → raw 검증 → 정규화·중복 제거 → processed 저장 |
| `tests/test_collector_handler.py`, `tests/test_processor_handler.py` | 인터넷·AWS·DB 없이 실행하는 단위 테스트 |

## 기존 코드 재사용 (수정하지 않음)

| 기존 코드 | 쓰는 방식 |
|---|---|
| `database/scripts/collect_career_news.py`의 `load_crawler` | 크롤러 폴더의 `config.py`·`src/rss_collector.py`를 검증하고 불러오며 8개 분야 코드를 검사 |
| 같은 파일의 `collect_all` | 분야·검색어별 수집, 검색어 사이 대기, 실패한 검색어 건너뛰기(부분 실패 정책 그대로) |
| 같은 파일의 `check_categories` | 분야 설정이 PlayMate 8개 분야와 다르면 수집 전에 중단 |
| `crawler/career_news_crawler/config.py`의 `CATEGORIES` | 분야·검색어·제목 키워드 |
| `crawler/career_news_crawler/src/rss_collector.py`의 `collect_google_news` | Google News RSS 요청, 제목 필터, 제외 출처, 기간 필터, 언론사 분리 |

부르지 않는 것: 크롤러 `main.py`·`src/database.py`(SQLite 저장), `import_career_news.import_articles`(PostgreSQL 적재).

`collect_all`은 결과를 (분야 코드, 기사) 행으로 합쳐 검색어 정보가 사라지므로, 수집 함수를 감싸는 `QueryRecorder`가 검색어별 결과·오류만 기록합니다. 결과와 예외는 그대로 `collect_all`에 돌려주므로 실패 처리 정책은 기존과 같습니다. 기록이 `collect_all`의 분야별 집계와 다르면 오류로 멈춥니다.

## raw JSON (임시 내부 규격 `0.1-draft`)

> **raw는 RSS XML 원문이 아닙니다.** 기존 크롤러가 제목 필터·제외 출처·기간 필터를 거쳐 돌려준 결과를 그대로 담습니다.
> 크롤러가 만들지 않는 기사 본문·원문 URL은 넣지 않습니다. 링크는 Google News RSS 링크 그대로이며(정규화하지 않음), 정규화·중복 제거는 Processor 단계 담당입니다.
> 팀 공통 JSON 형식이 확정되면 바뀔 수 있습니다.

| 필드 | 내용 |
|---|---|
| `schema_version` | `"0.1-draft"` |
| `run_id` | `<UTC 시각 YYYYMMDDTHHMMSSZ>-<식별자>` |
| `collected_at` | 수집 시작 시각, UTC ISO8601(`Z`) |
| `categories[]` | 분야별: `name`, `code`, `status`(`ok`/`partial`/`failed`), `succeeded_queries`, `failed_queries`, `article_count`, `queries[]` |
| `categories[].queries[]` | 검색어별: `query`, `status`(`ok`/`failed`), `error`(`{type, message}` 또는 `null`), `article_count`, `articles[]` |
| `articles[]` | 크롤러 반환값 그대로: `title`, `source`, `link`, `published`(UTC ISO8601 또는 `null`) |
| `collection_summary` | `status`, `data_kind`(`filtered_rss_results`), `days`, 분야·검색어·기사 수, `failed_categories`, `partial_categories`, `finished_at` |

`article_count`는 분야·검색어별 합계라 여러 분야에서 수집된 같은 기사는 중복으로 셉니다.

## 실행 결과 정책

| 상황 | `status` | S3 저장 | Lambda 결과 |
|---|---|---|---|
| 모든 검색어 성공, 기사 1건 이상 | `ok` | 저장 | 성공 |
| 일부 검색어 실패(분야 전체 실패 포함) | `partial` | 저장(실패 정보 포함) | 성공 |
| 모든 검색어 성공, 기사 0건 | `empty` | 저장 | 성공 |
| **모든 검색어 실패** | `failed` | **저장하지 않음** | `CollectionFailedError`로 실패 |
| S3 업로드 예외 또는 HTTP 200 미확인 | — | — | `RawUploadError`로 실패 |
| 환경변수·이벤트 값 오류 | — | 수집 시작 전 중단 | `ConfigError`로 실패 |

분야 상태는 기존 `collect_all`과 같은 기준입니다: 검색어가 하나도 성공하지 못한 분야만 `failed`.

로그·실패 기록: 전체 실패는 `ERROR` 로그와 예외 메시지에 `run_id`·실패 검색어 수·오류 종류별 개수를 남깁니다(비동기 호출 실패 기록에는 예외 메시지만 전달되기 때문). 일부 실패는 저장 후 성공으로 끝나므로 `WARNING` 로그로 실패 분야·오류 종류를 남깁니다. 검색어별 오류 상세는 기존 `collect_all`이 `INFO` 로그로 남깁니다.

## S3 키와 재시도

- 키: `<NEWS_RAW_PREFIX>YYYY/MM/DD/<run_id>.json` (기본 `raw/news/`). 날짜는 `run_id` 앞의 시각에서 정하므로 **같은 `run_id`는 항상 같은 키**입니다.
- `run_id` 결정 순서
  1. `event["run_id"]`: 수동 재실행용. 형식 검사(경로 문자 불가)
  2. `event["scheduled_time"]` 또는 `event["time"]`: `<예약 시각>-scheduled`. EventBridge Scheduler 입력에 `{"scheduled_time": "<aws.scheduler.scheduled-time>"}`을 넣으면 Lambda 자동 재시도도 같은 키를 씁니다.
  3. 그 외(콘솔 수동 실행): `<현재 시각>-<Lambda 요청 ID>`
- **raw는 불변(처음 저장 우선)**: `put_object(IfNoneMatch="*")` 조건부 쓰기로 이미 있는 키를 덮어쓰지 않습니다.

  | S3 응답 | 판단 | 결과 |
  |---|---|---|
  | 200 | 새로 저장 | `outcome = "created"` |
  | 412 `PreconditionFailed` + 기존 객체가 같은 `run_id`·`0.1-draft`·상태 `ok/partial/empty` | 정상 중복 실행(예약 재시도, 응답 유실 후 재시도) | `outcome = "already_exists"`, 이번 수집은 버리고 **기존 raw 요약**을 반환, 성공 |
  | 412 + 기존 객체가 다른 run_id·깨진 JSON·규격 위반 | 키 충돌 | `RawConflictError`(덮어쓰기·삭제 안 함, 사람이 확인) |
  | 412 + 기존 객체를 읽지 못함 | 확인 불가 | `RawUploadError`(재시도) |
  | 409 `ConditionalRequestConflict` | 같은 키 동시 쓰기 | `RawWriteConflictError`(일시적, 재시도) |
  | 그 밖의 오류·200 아님 | 저장 실패 | `RawUploadError` |

  같은 키에 다시 수집하려면 **새 `run_id`**로 실행합니다(예: `{"run_id": "20261117T120000Z-manual"}`). 412가 나도 RSS 수집은 이미 끝난 뒤이므로 요청 수는 줄지 않습니다(사전 `head_object` 확인은 추가하지 않음).
- `IfNoneMatch`는 2024년 8월 이후 boto3/botocore가 지원합니다. Lambda 런타임에 포함된 boto3가 이를 모르면 `put_object`가 파라미터 오류를 내고 `RawUploadError`로 실패합니다(조용히 덮어쓰지 않음). 배포 전 런타임 boto3 버전을 확인하거나 boto3를 묶음에 포함합니다.
- 412 확인을 위해 Collector에도 `s3:GetObject`(raw 접두사) 권한이 필요합니다.
- `NEWS_RAW_PREFIX`는 `raw/`로 시작해야 합니다. `processed/` 등에 쓰면 Processor 트리거와 섞일 수 있어 거부합니다.

## 환경변수

| 이름 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `NEWS_RAW_BUCKET` | 예 | — | 저장할 S3 버킷 이름 |
| `NEWS_RAW_PREFIX` | 아니오 | `raw/news/` | `raw/`로 시작 |
| `NEWS_DAYS` | 아니오 | `14` | 1~30 (기존 `collect_career_news.py` 범위) |
| `NEWS_PAUSE_SECONDS` | 아니오 | `1.0` | 검색어 사이 대기(0~10) |
| `NEWS_CRAWLER_DIR` | 아니오 | 저장소 크롤러 폴더 → 배포 묶음 폴더 | 크롤러 `config.py`·`src/`가 있는 폴더 |

자격증명은 코드나 환경변수에 두지 않고 Lambda 실행 역할을 사용합니다. 로그에는 환경변수 값을 남기지 않습니다.

## 실행 시간

- 검색어 28개(분야별 3~4개). 정상 시 요청 1~2초 + 대기 1초로 약 1~2분 예상.
- 최악: 28 × (요청 타임아웃 15초 + 대기 1초) ≈ 7.5분 → **Lambda 타임아웃 10분 권장**(최대 15분).
- 남은 실행 시간이 "요청 타임아웃 + 남은 검색어 대기 시간"보다 짧으면 요청하지 않고 `TimeBudgetExceeded`로 기록합니다. 업로드용으로 20초를 남깁니다. 남은 시간 판단은 Lambda `context.get_remaining_time_in_millis()`를 씁니다.
- 메모리 128~256MB 예상(실측 필요).

## 배포 ZIP (이번 단계에서 배포하지 않음)

`build_package.py`가 저장소 원본을 수정 없이 ZIP 최상위에 넣습니다(경로 구분자 `/`, 파일 순서·시각·권한 고정 → 같은 입력이면 같은 ZIP). 다운로드·설치는 하지 않습니다.

| 함수 | 핸들러 | ZIP 내용 | 외부 의존성 |
|---|---|---|---|
| Collector | `collector_handler.lambda_handler` | `collector_handler.py`, `collect_career_news.py`, `import_career_news.py`(← `database/scripts/`), `config.py`, `src/__init__.py`, `src/rss_collector.py`(← `crawler/career_news_crawler/`) | `feedparser`, `feedparser_sgmllib`, `requests`, `urllib3`, `idna`, `certifi`, `charset_normalizer` |
| Processor | `processor_handler.lambda_handler` | `processor_handler.py`, `collector_handler.py`, `import_career_news.py` | 없음(표준 라이브러리) |

1. Collector 의존성은 `requirements-collector.txt`(uv.lock과 같은 버전·해시)와 `requirements-collector-aws-sdk.txt`(boto3 등 6개)로 **Linux용 wheel만** `crawler/news_lambda/dist/collector-deps-sdk/`에 설치합니다. 명령은 [DEPLOYMENT.md](DEPLOYMENT.md) 7-1장. AWS 문서 권장대로 ZIP에 urllib3를 넣는 Collector는 boto3도 함께 넣습니다. Windows `.venv`의 `site-packages`를 쓰면 안 됩니다(`charset_normalizer/*.cp313-win_amd64.pyd`).
2. ZIP을 만들면 자동으로 검증합니다(`dist/`는 Git에서 제외됨). 이미 만든 ZIP은 `--verify <zip>`으로 검증만 할 수 있습니다(SDK 포함 ZIP은 `--with-aws-sdk`도 함께).

   ```powershell
   .venv\Scripts\python.exe crawler/news_lambda/build_package.py collector --with-aws-sdk --deps-dir crawler/news_lambda/dist/collector-deps-sdk --out crawler/news_lambda/dist/collector.zip
   .venv\Scripts\python.exe crawler/news_lambda/build_package.py processor --out crawler/news_lambda/dist/processor.zip
   ```

   빌드 거부: 필수 모듈 누락, `.pyd`·`.dll`·`.exe`·`win32`/`win_amd64` 파일, 다른 Python 버전·CPU용 `.so`, 프로젝트 파일(`config.py` 등)과 이름 겹침, Processor에 의존성 폴더 지정. `__pycache__`·`.pyc`는 넣지 않습니다.
   검증: 핸들러가 ZIP 최상위에 있는지, 소스가 저장소 원본과 같은지, 금지 파일·`../` 경로·boto3가 없는지 확인하고, 압축을 푼 폴더만 보이는 `python -I -S` 프로세스에서 import합니다.

Lambda 설정·IAM·S3 이벤트·Scheduler·실패 처리의 권장값은 [DEPLOYMENT.md](DEPLOYMENT.md)에 정리했습니다.

## 로컬 테스트

저장소 루트에서(인터넷·AWS·DB 접속 없음, socket 연결을 막고 시도 여부를 검사):

```powershell
.venv\Scripts\python.exe -I -m unittest discover -s crawler/news_lambda/tests -v
```

| 파일 | 내용 |
|---|---|
| `tests/test_collector_handler.py` | Collector 수집·raw·조건부 쓰기 |
| `tests/test_processor_handler.py` | Processor 이벤트·검증·정규화·멱등성 |
| `tests/test_pipeline_integration.py` | 가짜 RSS + 메모리 S3로 Collector → 이벤트 → Processor 전체 흐름 |
| `tests/test_build_package.py` | 배포 ZIP 구성·검증(변조·Windows 바이너리 거부, 격리 import)·요구사항 파일과 uv.lock 일치 |

## Processor Lambda

### 처리 흐름

1. `Records`를 순회합니다. `aws:s3`·`ObjectCreated:*`가 아니거나, 키가 `NEWS_RAW_PREFIX`(기본 `raw/news/`) 밖이거나 `.json`이 아니면 **읽지 않고 skip**합니다(트리거 설정이 잘못돼도 자기 출력으로 반복하지 않음).
2. 키는 S3 이벤트 규칙대로 URL 디코딩(`unquote_plus`)합니다.
3. 키에서 출력 키를 결정적으로 만듭니다: `raw/news/YYYY/MM/DD/<run_id>.json` → `processed/news/YYYY/MM/DD/<run_id>.json`. 날짜와 run_id 시각이 다르면 오류.
4. `get_object`로 **최신 객체**를 읽고(VersionId·ETag 기록), raw 규격(`0.1-draft`)과 집계 일관성을 검사합니다. 깨진 JSON·필드 누락·규격 위반은 **빈 결과로 저장하지 않고 오류**입니다.
5. 성공한 검색어의 기사만 `(분야 코드, 제목, 언론사, 링크, 발행일)` 행으로 만들어 기존 `import_career_news.build_articles`에 넘깁니다(정규화·`link_key`·중복 제거·분야 병합).
6. 저장 직전에 `head_object`로 raw가 그사이 바뀌지 않았는지 확인합니다. 바뀌었으면 `superseded`로 저장하지 않습니다(새 업로드의 이벤트가 처리).
7. `put_object`로 저장합니다. 레코드 하나라도 실패하면 나머지를 처리한 뒤 `ProcessingError`로 Lambda를 실패시킵니다.

### processed JSON (임시 내부 규격 `0.1-draft`)

| 영역 | 필드 |
|---|---|
| 실행 정보 | `schema_version`, `run_id`, `source_raw_key`, `source`{`bucket`, `version_id`, `etag`, `raw_schema_version`, `collected_at`} |
| 수집 결과(raw 그대로) | `collection.summary`(raw `collection_summary` 원본), `collection.categories`(분야별 상태·건수), `collection.query_failures`(실패 검색어와 raw 오류 원문) |
| 처리 결과 | `processing`{`status`(`ok`/`partial`/`empty`), `input_rows`, `article_count`, `multi_field_article_count`, `skipped`(사유별 건수)} |
| 기사 | `articles[]`: `link_key`, `link_url`, `link_type`, `title`, `source_name`, `published_at`, `field_codes`(정렬) — `NewsArticle`·`career_news` 컬럼과 같은 이름 |

- 처리 시각은 넣지 않습니다. 같은 입력이면 같은 바이트가 되어 재처리해도 결과가 바뀌지 않습니다(저장 시각은 S3 `LastModified`).
- `published_at`: `parse_published`가 돌려준 시간대 없는 UTC 시각에 `Z`를 붙인 ISO8601(초 단위). 이 값을 다시 `parse_published`에 넣으면 기존 DB 적재(`career_news.published_at`, UTC 기준 `TIMESTAMP`)와 같은 값이 됩니다.
- `processing.status`: raw가 `partial`이면 `partial`(기사 0건이어도), 아니면 기사 0건이면 `empty`, 그 외 `ok`.
- 링크 기준 중복만 제거합니다. "같은 언론사·제목, 3일 이내 다른 링크"를 같은 기사로 보는 규칙은 DB 적재(`import_articles`) 단계에 있어 여기서는 하지 않습니다.

### 상태별 처리

| 상황 | 결과 |
|---|---|
| 모든 검색어 성공 + 뉴스 있음 | `processing.status = ok`, 저장 |
| 모든 검색어 성공 + 뉴스 0건 | `empty`, 빈 `articles`로 저장 |
| 일부 실패 + 뉴스 있음 / 0건 | `partial`, 실패 정보 보존해 저장 |
| 잘못된 JSON·필드 누락·규격 위반·raw 상태 `failed` | 저장하지 않음, `RawValidationError` → Lambda 실패 |
| S3 읽기·상태 확인 실패 | 저장하지 않음, `RawReadError` → Lambda 실패 |
| S3 저장 실패·HTTP 200 미확인 | `ProcessedWriteError` → Lambda 실패 |
| raw가 처리 중 재업로드됨 | `superseded`, 저장하지 않음(성공으로 끝남) |

### 중복 이벤트·순서 역전

- 같은 raw는 항상 같은 processed 키와 같은 내용 → 중복 이벤트·Lambda 재시도는 같은 결과를 덮어씀(멱등).
- Collector는 raw를 조건부 쓰기로 한 번만 저장하므로(412 재시도는 이벤트를 만들지 않음), 정상 경로에서는 raw 키당 내용이 하나이고 `head_object` 확인은 항상 통과합니다. 최신 객체 확인 로직은 외부 재업로드에 대한 안전장치로 남겨 둡니다.
- 이벤트의 `versionId`가 아니라 **최신 객체**를 읽습니다. Collector 밖에서 같은 키를 다시 올리는 경우(수동 업로드 등)에도 최신 raw로 처리합니다. 이벤트 버전은 결과의 `event_version_id`로만 남깁니다.
- **S3는 Collector 밖의 조건 없는 덮어쓰기를 막지 않습니다.** 이 경우 processed도 새 내용으로 바뀝니다(`source.etag`로 추적 가능). 막으려면 버킷 정책으로 raw 접두사 쓰기를 Collector 역할로 제한하고, 이력이 필요하면 버전 관리를 켭니다.
  - 이벤트 버전을 정확히 읽는 방식(`VersionId` 지정)은 오래된 이벤트가 늦게 오면 오래된 결과로 덮어쓰므로 쓰지 않았습니다.
- **남은 위험**: `head_object` 확인과 `put_object` 사이에 raw가 다시 올라오고 그 처리가 먼저 끝나면, 늦게 끝난 쪽이 오래된 결과로 덮어쓸 수 있습니다(락 없이 완전히 막을 수 없음). 이 경우에도 processed의 `source.etag`/`version_id`로 어떤 raw에서 나왔는지 확인할 수 있습니다. 필요하면 processed에 조건부 쓰기(`IfMatch`)나 버킷 버전 관리를 검토합니다.
- 버킷 버전 관리가 없으면 `VersionId`는 `null`이고 ETag로만 비교합니다.

### 트리거 설정(문서화, 이번에 설정하지 않음)

- S3 이벤트 알림: 이벤트 `s3:ObjectCreated:*`, 접두사 `raw/news/`, 접미사 `.json`.
- `processed/`는 트리거에 포함하지 않습니다. 코드도 `NEWS_PROCESSED_PREFIX`가 `processed/`로 시작하지 않으면 거부하고, raw 접두사 밖의 키는 읽지 않습니다.

### 환경변수

| 이름 | 기본값 | 설명 |
|---|---|---|
| `NEWS_RAW_PREFIX` | `raw/news/` | Collector와 같은 값, `raw/`로 시작 |
| `NEWS_PROCESSED_PREFIX` | `processed/news/` | `processed/`로 시작 |
| `NEWS_PROCESSED_BUCKET` | (비움 → raw와 같은 버킷) | 다른 버킷에 저장할 때 |

최소 권한: `s3:GetObject`(raw 접두사, `head_object` 포함), `s3:PutObject`(processed 접두사), CloudWatch Logs. 버전 관리 버킷에서 특정 버전을 읽지 않으므로 `GetObjectVersion`은 필요 없습니다. 인터넷 접속이 필요 없으므로 VPC 밖에 두거나, VPC 안이면 S3 Gateway Endpoint를 씁니다.

### 배포 묶음

Processor 핸들러: `processor_handler.lambda_handler`. ZIP 구성은 위 "배포 ZIP" 표를 따릅니다(외부 패키지 없음). 타임아웃 1분이면 충분합니다.

## 미구현·팀 합의 필요

- 팀 공통 JSON 형식(현재 raw·processed 모두 `0.1-draft`), 날짜 표기 방식
- processed를 DB에 적재하는 담당자와의 계약: 실패 분야(`collection.summary.failed_categories`)의 기존 뉴스 유지 정책, 제목 기준 같은 기사 판별 위치, `empty`·`partial` 처리, `last_seen_at`에 쓸 시각(`source.collected_at` 권장)
- 버킷 이름·암호화·보관 기간, 실패 알림(DLQ/on-failure destination), 재시도 횟수
- 수집 주기와 Scheduler 입력(`scheduled_time`) 설정
- RSS XML 원문까지 보존할지(크롤러 함수 수정이 필요해 이번에는 하지 않음)
