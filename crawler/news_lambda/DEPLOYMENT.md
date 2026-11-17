# 뉴스 Lambda 배포 사양 (Issue #133)

> 이 문서는 **설정 제안서**입니다. AWS 리소스는 아직 만들지 않았고, 실제 값(버킷 이름·계정·역할 ARN 등)은 인프라 담당자와 정합니다.
> 표의 "근거"는 저장소 코드 기준입니다. "결정 필요"는 인프라 담당자가 정할 항목입니다.

```
EventBridge Scheduler ──(입력 {"scheduled_time": ...})──▶ playmate-news-collector (Lambda)
        ──PutObject(IfNoneMatch="*")──▶ s3://<버킷>/raw/news/YYYY/MM/DD/<run_id>.json
        ──ObjectCreated(raw/news/*.json)──▶ playmate-news-processor (Lambda)
        ──PutObject──▶ s3://<버킷 또는 processed 버킷>/processed/news/YYYY/MM/DD/<run_id>.json
```

## 1. Lambda 함수

| 항목 | Collector | Processor | 근거 |
|---|---|---|---|
| 함수 이름(예) | `playmate-news-collector` | `playmate-news-processor` | 결정 필요 |
| 핸들러 | `collector_handler.lambda_handler` | `processor_handler.lambda_handler` | `build_package.py`의 `HANDLERS` |
| 런타임 | `python3.13` | `python3.13` | 로컬·`uv.lock` 기준 Python 3.13(`pyproject.toml` `requires-python >=3.13`). 크롤러 자체는 3.12 이상 |
| 아키텍처 | `x86_64` | `x86_64` | `requirements-collector.txt`의 바이너리 해시가 manylinux x86_64용. arm64로 바꾸면 해시·빌드 옵션 변경 필요 |
| 배포 ZIP | `dist/collector.zip`(소스 6 + 의존성 7개 + **AWS SDK 6개, 권장**) | `dist/processor.zip`(소스 3개, 외부 의존성 없음 → 런타임 SDK 사용) | `build_package.py`, 7장 |
| 타임아웃 | **600초** | 60초 | Collector: 검색어 28개 × (요청 타임아웃 15초 + 대기 1초) ≈ 7.5분 최악. 기본 3초면 남은 시간 검사로 전체 실패. Processor: 수백 KB JSON 1개 읽기·쓰기 |
| 메모리 | 256MB | 256MB | feedparser 파싱·JSON 직렬화 수준. 첫 실행 후 CloudWatch `Max Memory Used`로 조정 |
| 동시 실행 제한(예약 동시성) | **1** | 2~5 | Collector는 같은 시각 실행이 겹칠 이유가 없음(겹쳐도 조건부 쓰기로 안전). Processor는 이벤트 수가 적음 |
| VPC | **연결하지 않음** | 연결하지 않음(권장) | Collector는 Google News(인터넷)에 접속. VPC에 넣으면 NAT 필요 |
| 임시 저장소(/tmp) | 기본 512MB | 기본 | 파일을 쓰지 않음 |

## 2. 환경변수

| Lambda | 이름 | 필수 | 기본값 | 설명 |
|---|---|---|---|---|
| Collector | `NEWS_RAW_BUCKET` | **예** | — | raw를 저장할 버킷. 없거나 형식이 틀리면 RSS 요청 전에 실패 |
| Collector | `NEWS_RAW_PREFIX` | 아니오 | `raw/news/` | `raw/`로 시작해야 함 |
| Collector | `NEWS_DAYS` | 아니오 | `14` | 1~30 |
| Collector | `NEWS_PAUSE_SECONDS` | 아니오 | `1.0` | 검색어 사이 대기(0~10) |
| Collector | `NEWS_CRAWLER_DIR` | 아니오 | (묶음 최상위) | 배포 ZIP에서는 설정하지 않음 |
| Processor | `NEWS_RAW_PREFIX` | 아니오 | `raw/news/` | Collector와 같은 값 |
| Processor | `NEWS_PROCESSED_PREFIX` | 아니오 | `processed/news/` | `processed/`로 시작해야 함 |
| Processor | `NEWS_PROCESSED_BUCKET` | 아니오 | (raw와 같은 버킷) | 다른 버킷에 저장할 때 |

비밀값은 없습니다. AWS 자격증명은 실행 역할을 씁니다.

## 3. IAM 최소 권한 (실행 역할별)

Collector 실행 역할:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid": "WriteAndVerifyRaw", "Effect": "Allow",
     "Action": ["s3:PutObject", "s3:GetObject"],
     "Resource": "arn:aws:s3:::<RAW_BUCKET>/raw/news/*"}
  ]
}
```

- `PutObject`: raw 저장(조건부 쓰기 `IfNoneMatch="*"`도 같은 권한).
- `GetObject`: 412(이미 있음)일 때 기존 raw의 `run_id`를 확인. 같은 run_id만 정상 중복 실행으로 처리.
- `ListBucket`은 주지 않습니다. 이 경우 없는 객체에 `GetObject`하면 S3가 404 대신 403을 줍니다. Collector는 412 직후에만 읽으므로 영향이 없습니다.

Processor 실행 역할:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid": "ReadRaw", "Effect": "Allow", "Action": "s3:GetObject",
     "Resource": "arn:aws:s3:::<RAW_BUCKET>/raw/news/*"},
    {"Sid": "WriteProcessed", "Effect": "Allow", "Action": "s3:PutObject",
     "Resource": "arn:aws:s3:::<PROCESSED_BUCKET>/processed/news/*"}
  ]
}
```

- `GetObject`는 `head_object`(최신 객체 확인)에도 쓰입니다. 특정 버전을 읽지 않으므로 `GetObjectVersion`은 필요 없습니다.
- 두 역할 모두 CloudWatch Logs 쓰기 권한(관리형 정책 `AWSLambdaBasicExecutionRole`)이 필요합니다.
- 실패 대상(SQS/SNS)을 쓰면 해당 `sqs:SendMessage`/`sns:Publish` 권한을 추가합니다.
- 버킷이 SSE-KMS면 Collector에 `kms:GenerateDataKey`·`kms:Decrypt`, Processor에 `kms:Decrypt`(raw)·`kms:GenerateDataKey`(processed)를 추가합니다.

## 4. S3

| 항목 | 값 | 비고 |
|---|---|---|
| raw 경로 | `raw/news/YYYY/MM/DD/<run_id>.json` | 날짜는 run_id 앞 시각(UTC) |
| processed 경로 | `processed/news/YYYY/MM/DD/<run_id>.json` | raw 키에서 결정적으로 생성 |
| 이벤트 알림 | 이벤트 `s3:ObjectCreated:*`, **접두사 `raw/news/`, 접미사 `.json`** → Processor | `processed/`는 넣지 않음(코드도 raw 접두사 밖은 읽지 않음) |
| Content-Type | `application/json; charset=utf-8` | 두 함수 모두 |
| 퍼블릭 액세스 차단 | 켬 | 결정 필요(기본 권장) |
| raw 쓰기 제한 | 버킷 정책으로 `raw/news/*` 쓰기를 Collector 역할만 허용 | **권장**. S3는 조건 없는 외부 덮어쓰기를 막지 않음 |
| 버전 관리 | 결정 필요 | Collector는 덮어쓰지 않으므로 필수는 아님. 외부 덮어쓰기·삭제 복구가 필요하면 켬 |
| 암호화 | 결정 필요(SSE-S3 기본 / SSE-KMS) | KMS면 3장의 권한 추가 |
| 수명 주기 | 결정 필요 | 예: raw 90일 후 저비용 클래스, processed는 DB 적재 정책에 맞춤 |

## 5. EventBridge Scheduler

| 항목 | 값 | 근거 |
|---|---|---|
| 대상 | Collector Lambda(비동기 호출) | — |
| 일정 | 결정 필요(예: 하루 1~2회, `Asia/Seoul` 시간대) | Google News 요청량 고려 |
| 입력(JSON) | `{"scheduled_time": "<aws.scheduler.scheduled-time>"}` | 같은 예약 실행의 재시도가 같은 `run_id`·키를 쓰게 함(`resolve_run_id`) |
| 재시도 정책 | Scheduler 재시도는 호출 실패(제한·권한)용. 함수 오류 재시도는 Lambda 비동기 설정을 따름 | — |
| 실행 역할 | `lambda:InvokeFunction`(Collector만) | — |
| 수동 재수집 | 새 run_id로 실행: `{"run_id": "20261117T120000Z-manual"}` | 같은 run_id는 기존 raw를 보존하고 끝남 |

## 6. 로그·실패 처리

| 항목 | Collector | Processor |
|---|---|---|
| 로그 그룹 보존 | 결정 필요(예: 30일) | 같음 |
| 비동기 최대 재시도 | 2(기본) | 2(기본) |
| 최대 이벤트 나이 | 예: 1시간 | 예: 6시간 |
| 실패 대상(on-failure destination) | SQS 또는 SNS(결정 필요) | 같음 |
| 실패로 끝나는 경우 | 설정 오류, **전체 검색어 실패**(raw 저장 안 함), 업로드 실패, 409 충돌(재시도로 해결), 다른 run_id 객체와 키 충돌 | 잘못된 raw, 읽기·쓰기 실패 |
| 성공이지만 주의 | `partial`(WARNING 로그), 412 정상 중복(`outcome=already_exists`) | `superseded`(WARNING 로그) |
| 경보 예 | `Errors > 0`, 로그 필터 `WARNING` | `Errors > 0` |

실패 대상에 전달되는 예외 메시지에는 run_id·실패 검색어 수·오류 종류가 들어 있습니다(비밀정보 없음).

## 7. Collector 의존성 준비 (다운로드 필요 — 승인 후 실행)

`requirements-collector.txt`는 `uv.lock`과 같은 버전·해시입니다(테스트로 검사).

| 배포 이름 | 버전 | import 이름 | wheel |
|---|---|---|---|
| feedparser | 6.0.14 | `feedparser` | 순수 Python |
| feedparser-sgmllib | 2.1.0 | `feedparser_sgmllib` | 순수 Python |
| requests | 2.34.2 | `requests` | 순수 Python |
| urllib3 | 2.8.0 | `urllib3` | 순수 Python |
| idna | 3.20 | `idna` | 순수 Python |
| certifi | 2026.7.22 | `certifi` | 순수 Python(`cacert.pem` 포함) |
| charset-normalizer | 3.5.2 | `charset_normalizer` | **cp313 manylinux2014 x86_64 바이너리**(순수 Python wheel 해시도 허용) |

실행 명령(저장소 루트, PyPI에서 wheel 7개를 내려받음. `.venv`·`uv.lock`은 바뀌지 않고 `crawler/news_lambda/dist/collector-deps/`만 생김 — `dist/`는 Git 제외):

```powershell
uv pip install --no-config --target crawler/news_lambda/dist/collector-deps `
  --python-platform x86_64-manylinux2014 --python-version 3.13 `
  --only-binary :all: --no-deps --require-hashes -r crawler/news_lambda/requirements-collector.txt
```

uv 0.12.2에서 실행 확인(2026-11-17): 7개 설치, 해시 검증 통과, `.venv`·`uv.lock` 변경 없음. `charset_normalizer`는 `cp313-manylinux2014_x86_64` 태그(`*.cpython-313-x86_64-linux-gnu.so`)로 설치되었습니다. Windows에서 실행하면 uv가 콘솔 실행 파일 `bin/idna.exe`·`bin/normalizer.exe`(Windows용)와 `.lock`을 함께 만드는데, `build_package.py`는 의존성 폴더 최상위의 `bin/`·`.lock`을 ZIP에서 제외합니다(그 밖의 `.exe`·`.pyd`는 계속 거부).

(Linux·WSL에서 pip를 쓰면: `python -m pip install --target … --platform manylinux_2_28_x86_64 --implementation cp --python-version 3.13 --abi cp313 --only-binary=:all: --no-deps --require-hashes -r …`)

참고: AWS 문서는 Python 3.12 이상 런타임에 `manylinux_2_28` 태그를 권장합니다. 위에서 설치한 `charset_normalizer 3.5.2` wheel은 `manylinux2014`·`manylinux_2_17`·`manylinux_2_28` 태그를 함께 가진 같은 파일(해시 `7218e8…`)이므로 결과는 같습니다. 이후 설치에는 `x86_64-manylinux_2_28`을 씁니다(7-1).

그다음 ZIP 생성(빌드 후 자동 검증):

```powershell
.venv\Scripts\python.exe crawler/news_lambda/build_package.py collector --deps-dir crawler/news_lambda/dist/collector-deps --out crawler/news_lambda/dist/collector.zip
.venv\Scripts\python.exe crawler/news_lambda/build_package.py processor --out crawler/news_lambda/dist/processor.zip
```

### 7-1. AWS SDK를 Collector ZIP에 함께 넣기 (권장, 추가 다운로드 승인 필요)

[AWS 문서(Python .zip 배포 패키지)](https://docs.aws.amazon.com/lambda/latest/dg/python-package.html)에 따르면 다음과 같습니다.

- Lambda는 `/var/task`(배포 ZIP)를 먼저 찾고, 그다음 레이어(`/opt/python`), 그다음 런타임 경로(`/var/runtime`, `/var/lang/lib/python3.x/site-packages`)를 찾습니다. ZIP에 넣은 라이브러리가 런타임 것보다 우선합니다.
- 배포 패키지에 SDK 의존성(예: urllib3)만 넣고 boto3는 넣지 않으면, 런타임 SDK가 갱신될 때 버전이 어긋나 함수가 실패할 수 있습니다. SDK 의존성을 넣으면 boto3도 함께 넣고, 런타임에 포함된 것이라도 모든 의존성을 패키지에 넣으라고 권장합니다.
- Python 3.12 이상 런타임은 Amazon Linux 2023(glibc 2.34) 기반이므로 `manylinux_2_28` 태그를 쓰라고 권장합니다.

Collector ZIP에는 requests 때문에 `urllib3 2.8.0`이 들어가므로 위 경고에 해당합니다. 그래서 Collector에는 SDK를 함께 넣습니다. Processor는 외부 의존성이 없어 런타임 SDK와 그 의존성을 그대로 쓰므로 해당하지 않습니다.

`requirements-collector-aws-sdk.txt`(6개). 기존 7개 버전을 고정한 채 `uv pip compile --python-platform x86_64-manylinux_2_28 --python-version 3.13 --only-binary :all:`로 해결했고, 기존 7개는 바뀌지 않았습니다. 이 6개는 프로젝트 `uv.lock`에 없으며, `uv.lock`은 변경하지 않습니다.

| 배포 이름 | 버전 | import 이름 | 필요한 이유 |
|---|---|---|---|
| boto3 | 1.44.4 | `boto3` | S3 클라이언트 |
| botocore | 1.44.4 | `botocore` | boto3 의존성. `urllib3`·`jmespath`·`python-dateutil` 사용 |
| s3transfer | 0.19.3 | `s3transfer` | boto3 의존성 |
| jmespath | 1.1.0 | `jmespath` | boto3·botocore 의존성 |
| python-dateutil | 2.9.0.post0 | `dateutil` | botocore 의존성 |
| six | 1.17.0 | `six` | python-dateutil 의존성 |

설치(승인 후 실행. 새로 내려받는 것은 위 6개 wheel이고, 기존 7개는 uv 캐시를 재사용할 수 있음):

```powershell
uv pip install --no-config --target crawler/news_lambda/dist/collector-deps-sdk `
  --python-platform x86_64-manylinux_2_28 --python-version 3.13 `
  --only-binary :all: --no-deps --require-hashes `
  -r crawler/news_lambda/requirements-collector.txt -r crawler/news_lambda/requirements-collector-aws-sdk.txt
```

ZIP 생성(SDK는 `--with-aws-sdk`로 명시했을 때만 허용):

```powershell
.venv\Scripts\python.exe crawler/news_lambda/build_package.py collector --with-aws-sdk --deps-dir crawler/news_lambda/dist/collector-deps-sdk --out crawler/news_lambda/dist/collector.zip
```

- SDK가 든 의존성 폴더를 플래그 없이 쓰면 거부합니다. SDK가 일부만 있어도 거부하고, Processor에는 SDK를 넣을 수 없습니다.
- 검증의 격리 import는 boto3·botocore·urllib3가 모두 ZIP에서 로드되는지 확인합니다. 또 ZIP 안 botocore의 서비스 모델(로컬 파일)로 `PutObject.IfNoneMatch` 지원 여부를 확인합니다.
- SDK 없이 만든 Collector ZIP은 검증 결과에 AWS 문서 경고가 붙습니다.
- 크기: botocore는 서비스 정의 파일이 많아 ZIP이 커집니다. 콘솔 직접 업로드 한도는 50MB(넘으면 S3 경유), 압축 해제 한도는 250MB입니다.

실행 결과(2026-11-17, uv 0.12.2, Windows 호스트 Python 3.13.15):

| 항목 | 결과 |
|---|---|
| 설치 | 13개, 해시 검증 통과, 요구사항과 버전 불일치 0건, 요구사항 밖 설치 0건. `.venv`·`uv.lock` 변경 없음 |
| 선언 의존 범위 | botocore `urllib3 !=2.2.0,<3,>=1.25.4` ← 2.8.0, boto3 `botocore <1.45.0,>=1.44.4` ← 1.44.4, `s3transfer <0.20.0,>=0.19.0` ← 0.19.3, `jmespath <2.0.0` ← 1.1.0, `python-dateutil <3.0.0,>=2.1` ← 2.9.0.post0, `six >=1.5` ← 1.17.0 |
| `dist/collector.zip` | 파일 2,360개, **16.92 MiB**(압축), **24.08 MiB**(해제), SHA-256 `C8E9728BD480DE9EC7D82962BD54FCF8E49EFF365246B638CBF54537FD6BFEB7`(재빌드 동일) |
| 격리 import | boto3 1.44.4·botocore 1.44.4·s3transfer 0.19.3·urllib3 2.8.0·requests 2.34.2 모두 ZIP에서 로드, 8개 분야 설정 로드 |
| 서비스 모델 | `PutObject.IfNoneMatch` 지원(ZIP의 botocore) |
| 요청 직렬화(네트워크 없음) | ZIP의 boto3로 클라이언트 생성(가짜 자격증명, 사용자 AWS 설정 차단), `before-send`에서 가로채 확인: `If-None-Match: *`, `Content-Type: application/json; charset=utf-8`, SigV4 서명, `https://<bucket>.s3.ap-northeast-2.amazonaws.com/raw/news/...` |
| 오류 처리(실제 botocore ClientError) | 200 → `created`, 412 `PreconditionFailed` → 기존 raw 1회 조회 후 `already_exists`, 409 `ConditionalRequestConflict` → `RawWriteConflictError`(botocore 기본 설정에서 재시도 0회) |

이 확인은 SDK 포함 ZIP을 빌드·검증할 때마다 자동으로 실행됩니다(`build_package.py`의 격리 import 검사).

## 8. 검증 단계

| 검증 | 방법 | 환경 |
|---|---|---|
| ZIP 구조: 핸들러 최상위, 소스가 저장소 원본과 동일, 의존성 7개, Windows 바이너리·캐시·`../` 경로·boto3 없음, Processor에 불필요한 파일 없음 | `build_package.py --verify` | 로컬(Windows 가능) |
| 재빌드 일관성 | 같은 입력 → 같은 바이트(파일 순서·시각·권한 고정) | 로컬 |
| ZIP만으로 import | 압축 해제 후 `python -I -S`(site-packages 없음)로 핸들러·크롤러 설정·의존성 import, 모든 모듈이 ZIP 안에서 로드되는지 확인 | 로컬. **Collector는 Windows에서 실행하면 Linux용 `.so` 대신 같은 패키지의 순수 Python 코드로 import되므로 부분 검증** |
| Linux 바이너리 실제 로드 | `public.ecr.aws/lambda/python:3.13`(x86_64) 컨테이너나 Lambda 콘솔 테스트로 import·핸들러 실행 | **Linux에서만 가능** |
| boto3 `IfNoneMatch` 지원 | SDK 포함 ZIP: 빌드 검증이 ZIP 안 botocore 서비스 모델로 확인(로컬). 실행 중에는 Collector가 클라이언트 생성 시 다시 확인하고 없으면 RSS 요청 전에 멈춤(`ensure_conditional_write_supported`). SDK 미포함 ZIP: 런타임 버전에 따름 | SDK 포함 시 로컬(설치 후), 미포함 시 **실제 런타임에서만 가능** |
| `urllib3`와 botocore | SDK 포함 ZIP: resolver(`uv pip compile`)가 `urllib3 2.8.0`이 `botocore 1.44.4` 요구 범위를 만족함을 확인. 격리 import에서 둘 다 ZIP에서 로드되는지 확인. SDK 미포함 ZIP: 런타임 botocore가 ZIP의 urllib3를 쓰므로 AWS 문서가 경고하는 구성 | 범위 확인은 로컬. **실제 S3 호출 동작은 실제 런타임에서만 가능** |
| 권한·이벤트 연결 | 테스트 버킷에서 수동 호출 1회 → raw·processed 생성, 같은 이벤트 재호출 → 동일 결과 | AWS(배포 후) |

## 9. 인프라 담당자 결정 사항

1. 버킷 이름·리전(서울 `ap-northeast-2` 예상), raw/processed 버킷 분리 여부
2. 암호화(SSE-S3/SSE-KMS), 버전 관리, 수명 주기, 퍼블릭 액세스 차단
3. raw 접두사 쓰기를 Collector 역할로 제한하는 버킷 정책
4. 실행 일정과 시간대, 실패 대상(SQS/SNS)과 알림 수신자, 로그 보존 기간
5. 아키텍처(x86_64 유지 또는 arm64 — arm64면 요구사항 해시·빌드 옵션 변경)
6. 배포 방식(콘솔 업로드/CLI/IaC)과 ZIP 보관 위치
