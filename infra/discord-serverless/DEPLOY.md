# Discord 서버리스 3안 — 취업·HOT·DM Worker 인프라 (AWS SAM)

3안: **PostgreSQL Outbox + Amazon SQS + AWS Lambda**. 이 스택은 그중 **발송 큐·결과 큐·Discord Worker Lambda**만 만든다.
DB 처리 계층과 EventBridge Scheduler는 **이 스택에서 만들지 않는다**. 기존 EC2 실행 계층은
[EC2 DB Runner 운영 문서](../discord-db-runner/DEPLOY.md)를 따른다. 실제 운영 DB·접속 경로 검증은 별도다.
취업 공유(1~13절)는 항상 만들고, HOT 공유와 댓글·대댓글 DM(15절)은 `DeployHotShare`/`DeployDmShare=true`일 때만 만든다.

> **이 문서의 어떤 단계도 아직 실제 AWS에서 실행·검증하지 않았다.** 로컬에서 확인한 것: 템플릿 정적 검증, 패키징, 핸들러 흐름
> (가짜 Discord·가짜 큐) 테스트 (`playmate-discord-bot/tests/test_serverless_infra.py`), SAM CLI 1.174.0 `sam validate --lint`·`sam build`
> (Issue #182, Docker 없이). `sam deploy`는 실행하지 않았다.

## 1. 만들어지는 리소스

이름 규칙: `playmate-<EnvironmentName>-<feature>-<role>` (`EnvironmentName` = `test` | `prod`, 다른 환경과 큐·함수를 공유하지 않는다).

```
(DB 처리 계층: 이 스택 밖, 미배포)
     │ SendMessage
     ▼
[playmate-<env>-career-share-send]  ──(5회 실패)──▶ [..-send-dlq]
     │ 이벤트 소스 매핑 (기본 비활성, 배치 1, 부분 실패 보고, 최대 동시성 2)
     ▼
playmate-<env>-career-share-worker  (Lambda, VPC 밖, 예약 동시성 2 = 최대 동시성, Python 3.13 arm64)
     │ secret_bootstrap.handler ─▶ 기존 career_share.worker_lambda.handler
     │ Discord REST (지정 채널 1개)
     │ SendMessage
     ▼
[playmate-<env>-career-share-result] ──(5회 실패)──▶ [..-result-dlq]
     │
     ▼
(DB 처리 계층이 소비해 이력 테이블에 반영: 이 스택 밖, 미배포)
```

| 논리 ID | 종류 | 역할 |
|---|---|---|
| `CareerShareSendQueue` / `CareerShareSendDLQ` | SQS 표준 | 발송 작업(`type=send`/`verify`). 가시성 540초, 보존 1일, 5회 실패 시 DLQ(보존 14일) |
| `CareerShareResultQueue` / `CareerShareResultDLQ` | SQS 표준 | Worker 결과. 보존 14일(소비자 배포 전 시험 결과 보존), 5회 실패 시 DLQ |
| `CareerShareWorkerFunction` | Lambda | 기존 Worker 로직. DB 접근 없음. 토큰은 시작 시 Secrets Manager에서 읽음 |
| `CareerShareWorkerSendQueueMapping` | 이벤트 소스 매핑 (명시적 리소스) | 발송 큐 → Worker. **기본 `Enabled=false`** |
| `CareerShareWorkerRole` | IAM 역할 | 아래 4절의 권한만 |
| `CareerShareWorkerLogGroup` | 로그 그룹 | `/aws/lambda/playmate-<env>-career-share-worker`, 보존 기본 30일 |
| 경보 7개 + 로그 지표 필터 1개 | CloudWatch | 7절 |

DLQ 보존 주의: 표준 큐는 DLQ로 옮겨도 **처음 넣은 시각 기준**으로 만료된다. 그래서 DLQ 보존(14일)을 원본(1일)보다 길게 둔다.
같은 계정·리전에 같은 `EnvironmentName` 스택을 두 개 만들면 큐·함수·경보 이름이 겹쳐 배포가 실패한다 (의도: 덮어쓰기 방지).

모든 큐는 SQS 관리형 서버 측 암호화(SSE-SQS)를 쓴다. 시크릿·SNS 토픽·VPC·NAT·Scheduler·DB 리소스는 만들지 않는다.

## 2. Worker 핸들러와 패키징

- 진입점 `secret_bootstrap.handler`(`infra/discord-serverless/src/secret_bootstrap.py`, 신규): 첫 호출에서 `WORKER_TARGET_HANDLER`
  (허용 목록: career/hot/dm `worker_lambda.handler`)를 정하고, 토큰을 Secrets Manager에서 **한 번** 읽어 프로세스 안의
  `DISCORD_BOT_TOKEN`에 넣은 뒤 기존 `career_share.worker_lambda.handler`에 그대로 위임한다. **기존 Worker·핸들러 코드는 바꾸지 않았다.**
- 패키지: `python infra/discord-serverless/build_package.py`가 `.build/career_worker/`에 아래만 복사한다 (Git 제외 폴더).
  - `career_share/`: `__init__, contract, messages, policy, queues, worker, worker_lambda`
  - `discord_rest/`: `__init__, client, errors, inactivity, permissions, transport` (`reuse.py` 제외: discord.py·config를 import함)
  - `secret_bootstrap.py`, 빈 `requirements.txt` (외부 패키지 없음. boto3는 Lambda 런타임 내장)
  - 복사한 파일이 `psycopg`, `discord`, `config`, `repositories`, `services`, DB 경로 모듈을 import하면 빌드가 실패한다.
- 런타임: Python 3.13 (코드는 3.10+ 문법 사용, 저장소 `requires-python >= 3.13`), arm64.

## 3. 동시성·재시도 정책

| 설정 | 값 | 이유 |
|---|---|---|
| 배치 크기 | 1 | 메시지 단위 실패 보고 |
| `ReportBatchItemFailures` | 켬 | `handle_records`가 `batchItemFailures`를 돌려준다. 실패한 메시지만 재전달 |
| 이벤트 소스 최대 동시성 | **2** | AWS 최솟값 (1은 설정 불가) |
| 예약 동시성 | **2** (= 최대 동시성) | AWS 권장(예약 >= 최대). 1이면 이벤트 소스가 2개까지 호출해 **스로틀이 상시 발생**한다 |
| Lambda 타임아웃 | 90초 | 마커 조회(최대 3페이지) + 전송 + 429 대기(최대 30초). 클라이언트는 남은 시간 - 5초 안에서 재시도를 멈춘다 |
| 발송 큐 가시성 타임아웃 | 540초 (= 90 x 6) | AWS 권장. 처리 중인 메시지가 다른 Worker에 다시 보이지 않게 한다 |
| `maxReceiveCount` | 발송 5 / 결과 5 | 구조적 스로틀이 없으므로 5회. 5회면 약 45분이라 TTL(10분)을 넘어 Worker가 UNKNOWN/EXPIRED로 끝낸다 |
| 보존 | 발송 1일 / 결과·DLQ 14일 | 작업 TTL(`not_after`)은 10분이라 오래된 작업은 보내지 않는다 |

**동시성 선택 근거 (1차 리뷰 반영)**

| 방안 | 결과 |
|---|---|
| A. 예약 1 + 최대 동시성 제거 | 이벤트 소스는 기본으로 여러 폴러(동시 호출)를 쓰므로 **스로틀이 오히려 늘어난다**. 스로틀된 메시지는 가시성 타임아웃(540초) 안에서 재시도되다 TTL(10분)을 넘길 수 있다 |
| **B. 예약 2 = 최대 동시성 2 (선택)** | 설정 충돌·구조적 스로틀 없음. 같은 메시지는 가시성 타임아웃(540초 > 함수 90초) 동안 다른 Worker에 보이지 않는다 |
| C. FIFO + MessageGroupId | 그룹별 직렬화와 5분 중복 제거가 되지만 **발행 코드(`career_share/queues.py`, DB 계층) 변경**이 필요하다 (이번 범위 밖) |

**동시성 1을 보장하지 않는다.** B에서는 서로 다른 두 작업이 동시에 처리될 수 있다. 서로 다른 작업은 마커가 달라 서로의 확인에 영향을 주지 않는다.
남는 위험은 SQS 표준 큐의 드문 **같은 메시지 동시 중복 전달**이다. 이때 두 Worker가 모두 마커를 못 찾고 보내 **중복 게시가 생길 수 있다**
(예약 1이었다면 순서대로 처리돼 두 번째가 마커를 찾았을 것). Discord `enforce_nonce`(nonce = 마커)가 문서대로 동작하면 막히지만 실제 검증 전이다.
`playmate-discord-bot/career_share/DEPLOY.md` 4절의 "예약 동시성 1"은 이 결정으로 바뀌었다 (그 문서는 이번 Issue 범위 밖이라 수정하지 않았다).
완전한 직렬화가 필요하다고 결정되면 C(FIFO, 발행 코드 변경 포함)로 간다.

재시도와 결과 (기존 Worker 코드 그대로, `test_serverless_infra.py`로 확인):

| 상황 | Worker 결과 | SQS 처리 |
|---|---|---|
| 429 (클라이언트 내부 대기·재시도 후에도) | `FAILED_RETRY` (실행 안 됨) | 메시지 삭제. **재시도 시각은 DB 계층이** 정해 다시 선점 |
| 5xx·타임아웃 (전송 여부 불명) | 마커 확인 → `SENT` 또는 `UNKNOWN` (자동 재발송 없음) | 삭제 |
| 마커 조회 실패 | 결과 없음, `batchItemFailures` | 540초 뒤 재전달. 그때 TTL이 지났으면 보내지 않고 `UNKNOWN` |
| 정상 발송 후 결과 큐 발행 실패 | `batchItemFailures` | 재전달 → 마커로 이미 게시됨을 확인 → `SENT`(재게시 없음) |
| 형식 오류 | `batchItemFailures` | 매번 실패 → 5회 뒤 DLQ |
| TTL(`not_after`) 경과 | `EXPIRED` (재전달이면 `UNKNOWN`) | 삭제 |
| 토큰 시크릿 조회 실패 | 호출 자체 실패 (`Errors` 경보) | 540초 뒤 재전달, 반복되면 DLQ |

**결과 큐에 소비자가 없을 때의 위험**: Worker를 켜면 결과가 결과 큐에 쌓이기만 한다. 14일 보존을 넘기면 결과가 사라지고, DB 계층은 그 글을
`SENT`로 기록하지 못한다 (나중에 복구 확인 작업이 마커로 찾을 수는 있다). 결과 DLQ는 **받는 쪽이 있어야** 이동하므로 소비자가 없으면 DLQ도 비어 있다.
`…-result-queue-stale` 경보(1시간)로 알린다. **운영에서는 DB 계층 소비자를 먼저 배포한 뒤에만 Worker를 켠다.**
- **중복을 완전히 막지는 못한다**: SQS 표준 큐는 최소 1회 전달이고, 동시 중복 전달·마커 조회 권한 문제·Discord nonce 동작(미검증)이 남는다
  (`playmate-discord-bot/career_share/DEPLOY.md` 5절).

## 4. IAM (Worker 역할)

| 권한 | 대상 |
|---|---|
| `logs:CreateLogStream`, `logs:PutLogEvents` | 이 Worker 로그 그룹만 |
| `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueAttributes` | 발송 큐만 |
| `sqs:SendMessage` | 결과 큐만 |
| `secretsmanager:GetSecretValue` | `DiscordBotTokenSecretArn` 하나만 |
| `kms:Decrypt` (선택) | `DiscordBotTokenSecretKmsKeyArn`을 넣은 경우에만, `kms:ViaService = secretsmanager.<region>.amazonaws.com` 조건 |

DB 자격 증명, VPC, EC2·RDS 관리, 다른 큐, 관리형 정책(`AWSLambdaBasicExecutionRole` 포함)은 주지 않는다. SSE-SQS는 KMS 권한이 필요 없다.

## 5. 파라미터와 배포 (초기 비활성)

| 파라미터 | 필수 | 설명 |
|---|---|---|
| `EnvironmentName` | | `test`(기본) / `prod` |
| `CareerShareChannelId` | **필수, 기본값 없음** | 발송 채널 ID. **처음에는 시험 채널** |
| `DiscordBotTokenSecretArn` | **필수, 기본값 없음** | 미리 만든 시크릿의 전체 ARN (이 스택은 시크릿을 만들지 않는다) |
| `DiscordBotTokenSecretJsonKey` | | 시크릿이 JSON이면 토큰 키 이름 (비우면 시크릿 문자열 = 토큰) |
| `DiscordBotTokenSecretKmsKeyArn` | | 고객 관리형 KMS 키를 쓸 때만 |
| `AlarmTopicArn` | | 경보 SNS 토픽. 비우면 경보는 만들어지지만 알림이 없다 |
| `CareerWorkerEventSourceEnabled` | | `false`(기본) / `true` |
| `LogRetentionInDays`, `ThrottleAlarmThreshold` | | 30일 / 5분에 1회 (예약 = 최대 동시성이라 스로틀은 이상 신호) |
| `DiscordBotTokenVersion` | | 기본 `1`. 토큰을 바꾼 뒤 올린다 (아래 토큰 교체 절차) |

**토큰 처리 방식 비교와 선택**

| 방식 | 코드 변경 | 보안 |
|---|---|---|
| ① 배포 때 환경변수로 주입 (CloudFormation 동적 참조 등) | 없음 | 토큰이 Lambda 설정에 평문으로 남아 `GetFunctionConfiguration` 권한자에게 보인다. 교체 시 재배포 |
| ② **런타임에 Secrets Manager 조회 (선택)** | 기존 코드 변경 없음 (`secret_bootstrap` 신규 1개) | 설정·템플릿·로그에 값이 없다. 역할에 시크릿 1개 읽기 권한만 |

**토큰 캐시와 교체·복구 절차**
- 토큰은 실행 환경(컨테이너)마다 **첫 호출에 한 번** 읽고 계속 쓴다 (`DiscordRestClient`도 그 토큰으로 만들어져 캐시된다).
- 시크릿만 바꾸면 이미 떠 있는 실행 환경은 **이전 토큰을 계속 쓴다**. Discord에서 토큰을 재발급하면 이전 토큰은 즉시 무효라,
  그 실행 환경의 발송은 401 → 기존 Worker가 `FAILED_PERMANENT`(자동 재시도 없음)로 보고한다. 그대로 두면 글이 공유되지 않는다.
- 시크릿 조회가 실패하면(Secrets Manager 장애·권한) 호출이 실패하고 실패는 캐시하지 않는다. 다음 호출에서 다시 읽는다.
- 오류 메시지에는 예외 이름만 남고 토큰·시크릿 ARN은 남지 않는다. Lambda 콘솔에 `DISCORD_BOT_TOKEN` 환경변수를 직접 넣으면 시크릿을 읽지 않으므로 넣지 않는다.

교체 순서:
1. 이벤트 소스 비활성 (`CareerWorkerEventSourceEnabled=false`) — 교체 중 발송 중단
2. Discord 개발자 포털에서 토큰 재발급 → Secrets Manager 시크릿 값 갱신 (Gateway Bot이 같은 토큰이면 Gateway 설정도 함께 갱신)
3. `DiscordBotTokenVersion`을 올려 배포 (예 `1` → `2`). 함수 설정이 바뀌어 이전 토큰을 캐시한 실행 환경이 새 환경으로 교체된다
4. 이벤트 소스 다시 활성화
5. 교체 사이에 `FAILED_PERMANENT`(401)가 된 글은 DB에서 사람이 재시도 가능 상태로 되돌린다 (`career_share/DEPLOY.md` 5절 "영구 오류")

**사전 준비 (사람이 직접, 이 문서는 값을 만들지 않는다)**
1. Secrets Manager에 봇 토큰 시크릿 생성 (콘솔 권장. 셸 기록·파일에 토큰을 남기지 않는다). 예 이름: `playmate/test/discord-bot-token`
2. 시험용 Discord 채널 준비: 봇 권한 `View Channel`, `Send Messages`, **`Read Message History`**(마커 확인 필수), `Embed Links`
3. (선택) 경보용 SNS 토픽과 구독
4. `aws lambda get-account-settings`로 계정 동시성 확인: 예약 동시성 2를 잡은 뒤에도 **예약되지 않은 동시성이 100 이상** 남아야 한다
   (새 계정은 한도가 낮아 예약 동시성 설정이 실패할 수 있다 → 한도 상향 요청)

**배포 (Scheduler·DB 계층 없이, 발송 비활성)**

순서가 중요하다: `build_package.py` → `sam build` → `sam deploy`. 빌드 스크립트를 빼먹으면 `.build/`가 없어 `sam build`가 실패하고,
코드를 바꾼 뒤 다시 돌리지 않으면 **예전 코드가 배포된다** (스크립트는 매번 폴더를 지우고 새로 만든다).
```powershell
python infra/discord-serverless/build_package.py
cd infra/discord-serverless
sam validate --lint
sam build
sam deploy --config-env test --parameter-overrides `
  EnvironmentName=test `
  CareerShareChannelId=<시험 채널 ID> `
  DiscordBotTokenSecretArn=<시크릿 ARN> `
  CareerWorkerEventSourceEnabled=false `
  AlarmTopicArn=<SNS ARN 또는 생략>
```
`samconfig.toml`에는 `parameter_overrides`를 두지 않는다 (명령줄 값이 통째로 대체해 `EnvironmentName`이 빠질 수 있음). 모든 값을 한 번에 넘긴다.

## 6. 시험 활성화 절차 (시험 채널, DB 계층 없이)

DB 계층이 없으므로 시험 작업은 사람이 넣는다. **실제 시험 채널에 메시지 1건이 게시된다.**
1. 스택 출력에서 `CareerShareSendQueueUrl`, `CareerShareResultQueueUrl`, `CareerShareWorkerEventSourceMappingId` 확인
2. 시험 작업 1건을 발송 큐에 넣는다. `not_after`는 지금부터 10분 이내, `marker`는 `ref:<unit_id>`, embed footer에 같은 마커가 있어야 한다
   (`career_share/contract.py` 형식. `unit_id`는 운영 글과 겹치지 않는 값, 예 `post-999999999`)
3. 이벤트 소스 활성화: `sam deploy ... CareerWorkerEventSourceEnabled=true` (또는 `aws lambda update-event-source-mapping --uuid <ID> --enabled`)
4. 확인: 시험 채널에 embed 1건, 로그 `job ... -> SENT`, 결과 큐에 `outcome=SENT` 메시지 1건
5. 같은 작업을 한 번 더 넣어 **두 번째 게시가 없고** 결과가 `SENT`(같은 message_id)인지 확인 (마커 중복 방지)
6. 다시 비활성화 (`CareerWorkerEventSourceEnabled=false`). 결과 큐의 시험 메시지는 DB 계층이 없으므로 확인 후 삭제한다
   (`receive-message` 후 `delete-message`, 또는 시험 환경에서만 `purge-queue`)

## 7. CloudWatch 경보

| 경보 | 조건 |
|---|---|
| `…-career-share-worker-errors` | Lambda `Errors` ≥ 1 / 5분 (토큰 시크릿 조회 실패 등 호출 단위 실패) |
| `…-career-share-worker-throttles` | Lambda `Throttles` ≥ `ThrottleAlarmThreshold`(기본 1) / 5분 |
| `…-career-share-worker-error-logs` | 로그 `[ERROR]` ≥ 1 / 5분 (메시지별 실패는 `batchItemFailures`로 처리되어 `Errors`에 안 잡힌다) |
| `…-career-share-send-dlq-not-empty` | 발송 DLQ 메시지 ≥ 1 |
| `…-career-share-result-dlq-not-empty` | 결과 DLQ 메시지 ≥ 1 |
| `…-career-share-send-queue-stale` | 발송 큐 가장 오래된 메시지 ≥ 600초 (작업 TTL 초과 = Worker 비활성·정체) |
| `…-career-share-result-queue-stale` | 결과 큐 가장 오래된 메시지 ≥ 1시간 (소비자 없음·정체. 소비자 배포 전 시험 결과를 남겨 두면 계속 ALARM) |

로그 필터 `"[ERROR]"`는 Python 런타임 **텍스트** 로그 형식(`[ERROR]\t시각\t요청ID\t메시지`, 처리되지 않은 예외는 `[ERROR] 예외명: …`)에 맞춘 것이다.
`LoggingConfig.LogFormat`을 JSON으로 바꾸면 필터도 `{ $.level = "ERROR" }`로 바꿔야 한다.

`AlarmTopicArn`을 넣으면 ALARM/OK 알림이 SNS로 간다. 기존 `playmate-cloudwatch-discord` EventBridge 규칙·API Destination은 건드리지 않는다
(그쪽으로 보내려면 별도 결정. 이 스택은 SNS ARN만 받는다).

## 8. 큐·DLQ 확인

```powershell
aws sqs get-queue-attributes --queue-url <URL> --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible ApproximateAgeOfOldestMessage
aws sqs receive-message --queue-url <DLQ URL> --max-number-of-messages 1 --visibility-timeout 30   # 내용 확인 (삭제 안 됨)
aws sqs start-message-move-task --source-arn <DLQ ARN> --destination-arn <원래 큐 ARN>               # 원인 해결 후 재처리
```
발송 DLQ의 작업은 TTL(10분)이 지났으면 재처리해도 보내지지 않는다 (`EXPIRED`/`UNKNOWN`). DB 계층의 복구 절차(마커 확인)로 처리하고 DLQ는 비운다.
결과 DLQ는 DB 계층이 정상화된 뒤 결과 큐로 되돌린다 (결과 반영은 멱등).

## 9. 예상 과금 항목 (무료라고 가정하지 않는다)

공식 요금을 이번 작업에서 조회하지 않았다. 아래는 **과금 가능 항목**이며 금액은 리전(ap-northeast-2) 요금표로 확인한다.
- Lambda: 요청 수 + 실행 시간(GB-초). 프리 티어 적용 여부는 계정에 따라 다르다
- SQS: 요청 수 (이벤트 소스가 **활성화되어 있으면 메시지가 없어도 long-poll 요청이 계속 발생**). 비활성이면 폴링하지 않는다
- CloudWatch: 경보 6개(경보당 월 요금), 사용자 지표 1개(로그 지표 필터), 로그 수집·저장
- Secrets Manager: 시크릿 월 요금 + API 호출 (시크릿은 스택 밖에서 만들지만 요금은 발생)
- KMS: 고객 관리형 키를 쓰면 키 월 요금 + 요청
- 데이터 전송: Discord로 나가는 트래픽 (소량)
- **NAT 요금 없음** (NAT를 만들지 않는다)

## 10. NAT가 필요 없는 이유

Worker는 **VPC에 연결하지 않는다**. VPC 밖 Lambda는 AWS 관리 네트워크에서 인터넷으로 바로 나가므로 Discord API, SQS 공개 엔드포인트,
Secrets Manager 공개 엔드포인트에 NAT 없이 닿는다. Worker는 DB에 접근하지 않으므로 Aiven 허용 목록·고정 IP도 필요 없다.

## 11. DB 처리 계층과의 연결 (다음 작업)

DB 계층(EC2 실행기 또는 DB Lambda, 미정)은 이 스택의 출력을 쓴다.
- `CAREER_SHARE_SEND_QUEUE_URL` = `CareerShareSendQueueUrl` (권한: `sqs:SendMessage`)
- 결과 소비: `CareerShareResultQueueUrl` (권한: `sqs:ReceiveMessage`, `DeleteMessage`, `GetQueueAttributes`, 필요 시 `ChangeMessageVisibility`).
  Lambda면 이벤트 소스 매핑(`ReportBatchItemFailures`), EC2면 long-poll 후 `career_share.db_lambda.handler({"Records": [...]})`가 돌려준
  `batchItemFailures`에 없는 메시지만 삭제
- 그 밖의 DB 계층 환경변수: `career_share/DEPLOY.md` 3절 (`CAREER_SHARE_CUTOVER_AT`, `PLAYMATE_WEB_BASE_URL`, `DB_*`)

## 12. 운영 배포 전 필수 확인

1. 운영 DB 확정과 `048` 적용 (격리 DB 검증은 끝남), DB 계층 방식(EC2 재사용/Lambda) 결정과 배포
2. 기존 Gateway 18:00 공지 끄기(`PLAYMATE_CAREER_NOTICE_ENABLED=false`)와 `baseline` 순서 (`career_share/DEPLOY.md` 6절)
3. 시험 채널에서 6절 통과 (마커 조회, embed 표시, 중복 전달 시 재게시 없음)
4. 운영 채널 ID는 운영 배포 때만 파라미터로 넣는다 (`EnvironmentName=prod`, 템플릿·설정 파일에 넣지 않는다)
5. 경보 SNS 연결과 수신 확인, 계정 동시성 한도(5절 사전 준비 4)
6. `build_package.py` → `sam validate --lint` → `sam build` (Issue #182에서 로컬 통과. 배포 직전에 다시 실행)
7. 결과 큐 소비자(DB 계층)를 **먼저** 배포한 뒤 운영 Worker를 켠다 (3절 "결과 큐에 소비자가 없을 때의 위험")
8. 동시성 2 결정과 남은 중복 위험(3절)을 팀이 수용했는지 확인 (아니면 FIFO 전환을 별도 Issue로)

## 13. 롤백

1. **즉시 중단**: 이벤트 소스 비활성 (`aws lambda update-event-source-mapping --uuid <ID> --no-enabled` 또는 `CareerWorkerEventSourceEnabled=false`로 재배포).
   발송 큐에 남은 작업은 그대로 두면 TTL(10분) 뒤 보내지지 않는다
2. 템플릿 변경 롤백: 이전 커밋으로 `sam build` + `sam deploy` (CloudFormation 변경 세트 확인)
3. 스택 삭제(`sam delete`)는 **큐와 그 안의 메시지·DLQ·로그 그룹을 함께 지운다**. 삭제 전 DLQ·결과 큐 내용을 확인한다. 시크릿·SNS는 스택 밖이라 남는다

## 14. HOT·DM 확장

Issue #182에서 구현했다 → 15절.

## 15. HOT 공유·댓글 DM Worker (Issue #182)

### 15.1 켜는 방법

| 파라미터 | 기본 | 설명 |
|---|---|---|
| `DeployHotShare` | `false` | `true`면 HOT 큐 4개·Worker·역할·로그 그룹·경보 4개를 만든다 |
| `HotShareChannelId` | `""` | `DeployHotShare=true`면 **필수** (템플릿 Rule이 배포 전에 막는다). 처음에는 시험 채널 |
| `HotWorkerEventSourceEnabled` | `false` | HOT 발송 큐 → Worker |
| `DeployDmShare` | `false` | `true`면 DM 큐 4개·Worker·역할·로그 그룹·경보 4개를 만든다. 채널 파라미터 없음 (작업의 `recipient_id`로 DM 채널을 연다) |
| `DmWorkerEventSourceEnabled` | `false` | DM 발송 큐 → Worker. **Gateway DM 폴링 전환 절차(`playmate-discord-bot/dm_share/DEPLOY.md` 5절)를 따른 뒤에만** 켠다 |
| `DmProdActivationApproved` | `false` | 운영(`prod`)에서 DM 이벤트 소스를 켤 때 필요한 7단계 승인 (15.10). 시험 환경에는 영향 없음 |

토큰은 취업과 **같은 시크릿**(`DiscordBotTokenSecretArn`)을 쓴다. 새 시크릿을 만들지 않는다. 각 Worker 역할에 그 시크릿 읽기 권한만 있다.
두 기능 모두 기본값이 `false`라 **취업만 배포하는 기존 명령은 그대로 동작한다** (5절).

```powershell
python infra/discord-serverless/build_package.py            # career_worker, hot_worker, dm_worker 세 패키지
cd infra/discord-serverless
sam validate --lint
sam build
sam deploy --config-env test --parameter-overrides `
  EnvironmentName=test CareerShareChannelId=<시험 채널> DiscordBotTokenSecretArn=<시크릿 ARN> `
  DeployHotShare=true HotShareChannelId=<HOT 시험 채널> HotWorkerEventSourceEnabled=false `
  DeployDmShare=true DmWorkerEventSourceEnabled=false `
  AlarmTopicArn=<SNS ARN 또는 생략>
```
명령줄 `--parameter-overrides`는 매번 **모든 값**을 다시 넣는다 (빠진 값이 기본값으로 돌아가면 그 기능이 스택에서 빠진다: 예 `DeployHotShare` 누락).
큐·DLQ는 Retain으로 남고, 스택 정책·변경 세트 검사로 그런 배포를 미리 막는다 → 15.9.

### 15.2 리소스 (기능당)

| 리소스 | HOT | DM |
|---|---|---|
| 발송 큐 | 표준, 가시성 540초, 보존 1일, 5회 → DLQ | **FIFO** (`…-dm-share-send.fifo`, 그룹 = 알림, 중복 제거 = job_id), 가시성 360초, **보존 1시간**, 5회 → DLQ |
| 발송 DLQ | 표준, 보존 14일 | **FIFO** (`…-dm-share-send-dlq.fifo`), **보존 7일** (받는 사람 ID 포함, 원본 넣은 시각 기준) |
| 결과 큐 / DLQ | 보존 14일, 5회 → DLQ | 같음 (결과에는 받는 사람 ID·본문이 없다) |
| Worker | `hot_share.worker_lambda.handler`, 90초, 예약 동시성 2 | `dm_share.worker_lambda.handler`, 60초, 예약 동시성 2 |
| 이벤트 소스 | 배치 1, 부분 실패 보고, 최대 동시성 2, 기본 비활성 | 같음 |
| 역할 | 자기 큐·로그 그룹·토큰 시크릿만 | 같음 |
| 경보 | 4개 (15.6) | 4개 |

모든 큐는 SSE-SQS. VPC·NAT·Scheduler·시크릿·DB 리소스는 만들지 않는다.

### 15.3 패키지와 DM 의존성 분리

| 패키지 | 내용 |
|---|---|
| `hot_worker` | 공통 Worker(`career_share` 발송 경로 7개) + `hot_share/{__init__, messages, policy, worker_lambda}` + `discord_rest` core |
| `dm_worker` | 공통 Worker + `dm_share/{__init__, units, worker_lambda}` + `services/{__init__, notification_policy}` + `discord_rest` core |

DM Worker는 원래 DB 저장소 모듈 `repositories.dm_delivery_repository`에서 순수 상수·함수(`DM_BLOCKED_CODE`, `USER_GONE_CODES`,
`notification_id_of`)를 가져왔다. 이 4개(+`dm_unit_id`)를 **`dm_share/units.py`(순수 모듈)로 옮기고**, 저장소 모듈은 같은 이름으로
다시 내보낸다 (Gateway·DB Lambda·테스트의 기존 import 경로와 값·동작 그대로). `services/notification_policy.py`는 이미 순수 모듈
(`typing`만 import)이라 **파일 단위로만** 허용한다. 빌드는 패키지 파일이 `psycopg`, `discord`(discord.py), `config`, `repositories`,
그 밖의 `services`, DB 경로 모듈(`*.repository`, `*.db_lambda`, `*.service`, `*.settings`, `dm_share.messages`), `bot`을 import하면 실패한다.

### 15.4 동시성과 중복 발송

| | HOT | DM |
|---|---|---|
| 발송 큐 | 표준 | **FIFO** (그룹 = `unit_id`, 중복 제거 = `job_id`) |
| 예약 동시성 / 이벤트 소스 최대 동시성 | **2 / 2** | **2 / 2** |

**HOT = 취업과 같은 근거(3절).** HOT 재선점은 재시도 간격이 `5분 x 시도 횟수`라, 이전 작업이 실행 중(최대 90초, TTL 3분)일 때 같은 글의
새 작업이 동시에 처리되는 일이 없다. 남는 위험은 SQS 표준 큐의 드문 **같은 메시지 동시 중복 전달**뿐이다 (두 Worker가 모두 마커를 못 찾으면 중복 게시).

**DM: FIFO 전환 (Issue #182 3차).** FIFO 전 구성(표준 큐, 예약 1, 최대 2)은 AWS 권장 "예약 >= 최대"와 충돌해 스로틀이 생겼고, 예약을 2로 올리면
R4 중복 방지 전제가 깨졌다. 이제 같은 알림의 직렬화를 예약 동시성 대신 **FIFO 메시지 그룹**이 맡고, 예약 2 = 최대 2로 충돌을 없앴다.

R4: DM은 실패(429 등) 후 **60초 만에 재선점**되고 TTL은 50초다. 이전 작업의 복사본이 TTL 안에 시작해 429 대기 중일 때 새 작업(새 `claim_token`·`job_id`,
같은 `unit_id`)이 동시에 처리되면 둘 다 마커를 못 찾고 **같은 DM을 두 번 보낼 수 있다**.

| 정책 | 값 | 근거 |
|---|---|---|
| `MessageGroupId` | `unit_id` = `dm-<알림 ID>` | 같은 알림의 모든 작업(이전·재선점·확인)을 SQS가 한 번에 하나씩 넣은 순서대로 준다. 앞 작업이 삭제(처리 완료)되거나 가시성 타임아웃이 지나야 다음이 나온다 → R4의 새 작업은 이전 작업이 끝난 뒤 처리되어 마커를 찾는다. 서로 다른 알림은 병렬 |
| `MessageDeduplicationId` | `job_id` (발송 `dm-<id>:<claim_token>`, 확인 `dm-<id>:<claim_token>:v<초>`) | 재선점마다 `claim_token`이 바뀌어 **정당한 재시도는 지워지지 않는다**. 같은 선점의 작업을 두 번 넣으면(발행 재시도 등) 5분 동안 하나로 본다. `unit_id` 같은 고정 값은 5분 안의 정당한 재선점 작업까지 버리므로 쓰지 않는다. 본문 기반 중복 제거는 끈다 |
| 결과 큐 | **표준 유지** | DB 반영이 `claim_token` 일치·상태 전이표·`last_absent_job_id`로 멱등이라 순서·중복 제거가 필요 없다. FIFO로 바꾸면 비용·처리량 제약만 늘어난다 |
| 단일 그룹 대안 | 쓰지 않음 | 한 메시지가 실패하면 그룹 전체가 가시성 타임아웃(360초) 동안 멈춰 뒤의 모든 DM이 TTL을 넘긴다 |

구현: `dm_share/fifo.py`(`DmFifoPublisher`)가 DM DB 계층의 발행(상속한 `_publish_claims`의 발송 작업, `recover`의 확인 작업)만 감싸 그룹·중복 제거 ID를
붙인다. DM 작업이 아니거나 `job_id`가 `unit_id`와 맞지 않으면 발행을 거부한다. `career_share/queues.SqsPublisher.send`에는 키워드 전용
`group_id`·`dedup_id`(기본 `None`)만 추가했다 → 취업·HOT 발행과 모든 Worker의 결과 발행은 그대로. `load_dm_settings`는 발송 큐 URL이 `.fifo`가 아니면
시작하지 않는다. 표준 큐 예외는 `PLAYMATE_ENVIRONMENT`가 `local`·`test`이고 **동시에** `DM_SHARE_ALLOW_STANDARD_QUEUE=1`일 때만이다
(`prod`·`production`·값 없음·빈 값·알 수 없는 값이면 플래그가 있어도 거부, `dm_share/settings.py` `standard_queue_allowed`).
**향후 DM DB Lambda를 배포할 때 `PLAYMATE_ENVIRONMENT`를 반드시 설정한다** (`prod`/`test`, 이 스택의 `EnvironmentName`과 같은 값).
DM DB 계층은 이 스택 밖이라 값이 자동으로 들어가지 않는다. 비어 있으면 표준 큐 우회만 막히고 FIFO 발행은 정상이다 (`playmate-discord-bot/dm_share/DEPLOY.md` 5절).

검증 (로컬, `tests/test_dm_fifo.py`): SQS FIFO 그룹 규칙을 흉내 낸 큐 + 실제 `DmShareWorker` + 스레드 2개로
- 시나리오 C(429 대기 중 재선점): FIFO면 두 번째 Worker가 새 작업을 받지 못하고, 이전 작업 뒤에 처리되어 마커로 `SENT`(DM 1회). 새 작업 TTL이 지났으면 `EXPIRED`(DM 1회)
- 같은 조건을 표준 큐 + 동시성 2로 돌리면 **DM 2회** (전환 전 위험 재현)
- 같은 알림 중복 메시지·서로 다른 알림 병렬·결과 발행 실패 후 같은 그룹 맨 앞에서 재전달(재게시 없음)

**AWS가 보장하는 것과 로컬에서 확인한 것을 구분한다**: 그룹 직렬화·5분 중복 제거는 SQS FIFO와 Lambda 이벤트 소스의 동작이며 로컬 흉내로는 증명되지 않는다
(실제 AWS 시험 필요). **남는 위험**: (1) 5분 창 밖의 중복은 막지 않는다. (2) 앞 작업이 Lambda 타임아웃으로 끝났는데 Discord가 요청을 그보다 늦게 저장하면,
다음 작업의 마커 조회가 그 메시지를 못 볼 수 있다 (UNKNOWN 경로·16분 인수 제한이 기존과 같이 완화). (3) Discord 마커 조회·`enforce_nonce`는 실제 검증 전.
FIFO는 **Discord 전송의 exactly-once를 보장하지 않는다**.

| 지난 대안 | 결과 |
|---|---|
| A. 표준 큐 + 예약 1 + 운영 차단 (2차 임시안) | FIFO로 대체. 운영 차단은 15.10 단계 승인으로 유지 |
| C. Worker 중복 방지 강화 + 동시성 2 | Worker는 다른 Worker의 진행 중 요청을 알 수 없어 증명 불가. 채택하지 않음 |

**Gateway 버전 구분과 전환 조건 (Worker 쪽 변경 없음)**

| Gateway | 053 테이블 | DM Lambda와 동시 실행 |
|---|---|---|
| **공동 선점 버전** (#172 이후 develop, `services.notification_service`가 `DmDeliveryRepository.claim("GATEWAY")`로 선점) | 사용 | **가능**: 같은 알림은 053 PK 선점으로 한 곳만 보낸다. Gateway는 `sender=LAMBDA`인 FAILED 행을 Lambda 선점 후 **16분**(DB 시각) 뒤에만 이어받는다 |
| **구버전** (#172 이전, 053을 모름, 잠금 없는 `claim_pending`) | 무시 | **불가**: `notifications`가 PENDING인 알림을 그대로 보내 Lambda와 중복된다. DM 이벤트 소스를 켜기 전에 운영 Gateway가 공동 선점 버전인지 확인한다 |

16분 근거는 "진행 중인 Lambda 요청은 Worker 실행이 끝나면 끝나고 실행 상한은 15분"이며, DM Worker 타임아웃 60초는 그 안이다.
공동 선점 버전이어도 Gateway 배포는 단일 프로세스·재시작형으로 한다 (무중단 배포로 구버전과 겹치지 않게). 전환·롤백 순서: `dm_share/DEPLOY.md` 5절.

### 15.5 DM 개인정보

- 큐 메시지에는 받는 사람 Discord ID와 게시글 제목(embed)이 들어간다 → SSE-SQS, 발송 큐 보존 1시간, 발송 DLQ 7일
- Worker 로그에는 `unit_id`(`dm-<알림 ID>`)·결과·오류 종류만 남는다. 받는 사람 ID·제목·토큰이 로그에 없는 것을 테스트로 확인했다
  (`test_dm_logs_contain_no_recipient_title_or_token`: 성공·401·50007·조회 실패·잘못된 작업 경로)
- DLQ 메시지를 조회할 때는 개인정보로 다룬다 (화면 공유·복사 금지, 확인 후 삭제)

### 15.6 경보 (기능당 4개, 취업 7개를 복제하지 않음)

| 경보 | HOT | DM |
|---|---|---|
| `…-worker-failures` (지표 수학) | Lambda `Errors` + `Throttles` + `[ERROR]` 로그 ≥ 1 | `Errors` + `Throttles` + `[ERROR]`·`DiscordAuthError` 로그 ≥ 1 (FIFO 전환 후 예약 = 최대라 스로틀도 이상 신호) |
| `…-dlq-not-empty` (지표 수학) | 발송 DLQ + 결과 DLQ ≥ 1 | 같음 |
| `…-send-queue-stale` | 가장 오래된 작업 ≥ 180초 (TTL 3분) | ≥ 300초 (지속 스로틀·Worker 정지 감지) |
| `…-result-queue-stale` | 가장 오래된 결과 ≥ 1시간 | 같음 |

`Errors`에는 타임아웃도 포함된다. **DM POST 401은 Worker가 ERROR 로그 없이 정상 결과(`FAILED_RETRY`, `auth_error`)로 돌려준다**
(Lambda `Errors`에도 안 잡힘). 남는 로그는 `discord_rest`의 WARNING `Discord 요청 실패 …: DiscordAuthError`뿐이라, DM 로그 필터는
`?"[ERROR]" ?"DiscordAuthError"`로 그 경고도 센다 (실제 클라이언트·가짜 transport로 재현: `test_post_401_is_a_normal_result_but_matches_dm_filter`).
DM 채널 열기·마커 조회의 401은 Worker가 ERROR 로그를 남긴다. HOT의 401은 `CareerShareWorker`가 ERROR 로그를 남기므로 `"[ERROR]"`로 충분하다.
지표 수학 경보는 경보 1개 안에 여러 지표를 쓴다. **CloudWatch 요금은 경보 안 지표 수 기준일 수 있다** (요금표 확인 필요) — 개수는 줄지만 비용이 같을 수 있다.

### 15.7 과금 항목과 수량 (두 기능을 모두 만들 때 추가분, 금액은 요금표로 확인)

| 항목 | 추가 수량 | 비고 |
|---|---|---|
| Lambda | 2 | 호출·실행 시간 과금. 이벤트 소스 비활성이면 호출 없음 |
| SQS 큐 | 8 (작업 2, 결과 2, DLQ 4. 그중 DM 발송 큐·DLQ 2개는 FIFO) | 큐 자체는 무료, 요청 과금. **이벤트 소스가 켜져 있으면 메시지가 없어도 long-poll 요청이 계속 발생**. FIFO 요청은 표준 요청과 단가가 다르다 (요금표 확인, 이 문서에 금액을 적지 않는다) |
| CloudWatch 경보 | 8 (지표 수학 4개 포함. 지표 수 기준이면 HOT 7 + DM 7 = 경보 지표 14개) | |
| 사용자 지표 | 2 (로그 지표 필터) | |
| 로그 그룹 | 2 | 수집·저장 과금, 보존 `LogRetentionInDays` |
| Secrets Manager | **0** (기존 시크릿 재사용) | 조회 API 호출만 증가 (콜드 스타트마다 1회) |
| NAT·EC2·RDS·Scheduler | **0** | |

### 15.8 시험 활성화와 롤백

- 시험: 6절과 같다 (작업 1건을 사람이 넣고 이벤트 소스를 잠깐 켠다). HOT은 HOT 시험 채널에 게시된다. **DM 시험은 실제 사용자에게 DM이 가므로**
  `recipient_id`를 팀원의 시험 계정으로만 쓴다 (봇과 서버를 공유해야 DM이 열린다)
- 중단: 해당 이벤트 소스 비활성 (`aws lambda update-event-source-mapping --uuid <HotShare/DmShareWorkerEventSourceMappingId> --no-enabled`)
- 기능 제거: `DeployHotShare=false` / `DeployDmShare=false`로 배포하면 Worker·이벤트 소스·경보·역할·로그 그룹은 지워지고,
  **큐 8개는 `DeletionPolicy: Retain`으로 계정에 남는다** (스택에서만 빠짐). 스택 정책을 걸었다면 배포 자체가 거부된다 (15.9)
- DM 롤백은 Gateway 폴링 복구 순서(`dm_share/DEPLOY.md` 5절 롤백)를 따른다

### 15.9 HOT·DM 큐 삭제 방지 (문서 경고만으로는 막히지 않는다)

**위험**: HOT·DM 리소스는 조건(`CreateHotShare`/`CreateDmShare`)으로 만든다. `true`로 배포한 뒤 다음 배포에서 `DeployHotShare`/`DeployDmShare`가
`false`가 되면(명령줄 `--parameter-overrides`에서 빠뜨려 기본값으로 돌아간 경우 포함) CloudFormation은 그 리소스를 **삭제**한다.
템플릿 Rules는 이전 파라미터 값을 볼 수 없어 이 전환을 막지 못한다.

적용한 보호 장치 (세 겹):

| 장치 | 무엇을 막나 | 한계 |
|---|---|---|
| 1. **`DeletionPolicy: Retain` + `UpdateReplacePolicy: Retain`** (HOT·DM 큐·DLQ 8개, 템플릿) | 조건이 꺼지거나 스택을 지우거나 교체가 필요한 변경이 와도 **큐와 메시지가 계정에 남는다** | 스택에서는 빠진다 (Worker·이벤트 소스·경보는 지워짐). 남은 큐는 직접 관리·삭제해야 한다 |
| 2. **스택 정책** `stack-policy.json` (배포 후 한 번 적용) | 위 8개 큐의 `Update:Delete`·`Update:Replace`를 **거부** → 실수로 `false`가 들어간 업데이트 자체가 실패한다 | `sam deploy`에는 스택 정책 옵션이 없어 CLI로 한 번 건다. 의도한 제거 때는 잠시 풀어야 한다. 스택 삭제는 막지 않는다 (1이 보호) |
| 3. **변경 세트 사전 검사** `check_changeset.py` | 실행 전에 SQS 큐의 `Remove`·`Replacement(True/Conditional)`를 찾아 멈춘다 | 사람이 순서를 지켜야 한다 |

```powershell
# 2. 스택 정책 적용 (HOT·DM을 처음 만든 배포 직후 한 번)
aws cloudformation set-stack-policy --stack-name playmate-test-discord-serverless --stack-policy-body file://infra/discord-serverless/stack-policy.json

# 3. 매 배포: 변경 세트만 만들고 검사한 뒤 실행
sam deploy --config-env test --no-execute-changeset --parameter-overrides <모든 값>
aws cloudformation describe-change-set --stack-name playmate-test-discord-serverless --change-set-name <출력된 이름> --output json > changeset.json
python infra/discord-serverless/check_changeset.py changeset.json      # 0 = 큐 삭제·교체 없음
aws cloudformation execute-change-set --stack-name playmate-test-discord-serverless --change-set-name <이름>
```
`samconfig.toml`의 `confirm_changeset = true`도 실행 전에 변경 목록을 보여 준다 (`Remove`/`Replacement` 열 확인).

**이전 파라미터 유지**: 명령줄 `--parameter-overrides`에 모든 값을 다시 넣는다. 빠진 파라미터가 이전 값으로 유지되는지 기본값으로 돌아가는지는
SAM CLI 동작에 따라 다를 수 있어 **이 문서에서 보장하지 않는다**. 그래서 위 2·3을 둔다.

**Retain과 고정 큐 이름의 충돌 (실제 AWS 미검증)**: 큐 이름이 고정(`playmate-<env>-hot-share-send` 등)이라, Retain으로 남은 큐가 있는 상태에서
다시 `Deploy*=true`로 배포하면 같은 이름의 큐를 새로 만들려 한다. SQS는 같은 이름·같은 속성이면 기존 큐를 돌려주고, 속성이 다르면 오류를 낸다.
CloudFormation이 이를 어떻게 처리하는지는 실제로 확인하지 않았다. 다시 켜기 전에:
1. 남은 큐·DLQ의 메시지를 확인한다 (8절. DM 큐는 개인정보로 다룬다)
2. 필요 없으면 큐를 직접 삭제하고 60초 이상 기다린 뒤 배포한다 (SQS는 같은 이름 재생성에 대기 시간이 있다), 또는
3. 남은 큐를 CloudFormation **리소스 가져오기(import)**로 스택에 다시 넣는다

**의도적으로 HOT·DM을 없앨 때**: 이벤트 소스 비활성 → 큐·DLQ가 비었는지 확인 → 스택 정책에서 해당 큐 거부를 잠시 제거 → `Deploy*=false` 배포 →
남은 큐 직접 삭제 → 스택 정책 복원.

**DM 표준 → FIFO 전환과 교체**: `FifoQueue`·`QueueName` 변경은 CloudFormation **교체(Replacement)** 다. 지금까지 DM 큐를 배포한 적은 없지만,
표준 DM 큐로 배포한 스택(이번 변경 이전 코드)에 이 템플릿을 적용하면 변경 세트에 `DmShareSendQueue`·`DmShareSendDLQ`의 `Replacement=True`가 나온다.
- `check_changeset.py`가 이 교체를 잡아 멈추고, 스택 정책을 걸었다면 `Update:Replace` 거부로 실패한다 (의도한 전환이면 그 두 큐만 잠시 허용)
- 이름이 바뀌므로(`…-dm-share-send` → `…-dm-share-send.fifo`) 새 FIFO 큐와 이름 충돌은 없다. `UpdateReplacePolicy: Retain`으로 **이전 표준 큐는 계정에 남는다**
  → 남은 메시지를 확인하고(개인정보) 직접 삭제한다
- 전환 순서: DM 이벤트 소스 비활성 → DM DB 계층이 새 `.fifo` URL을 쓰도록 먼저 바꾸지 말고(아직 큐 없음) 스택 업데이트로 FIFO 큐 생성 →
  DB 계층 `DM_SHARE_SEND_QUEUE_URL`을 `.fifo` URL로 변경 → 이전 표준 큐 비었는지 확인 후 삭제

### 15.10 운영 DM 활성화 단계 (Rule `DmWorkerProdRequiresApproval`)

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | FIFO 코드 구현 (발행기·큐·동시성) | **완료** (Issue #182) |
| 2 | 로컬 중복·재시도 테스트 통과 | **완료** (`test_dm_fifo.py`, `test_serverless_infra.py`) |
| 3 | AWS 시험 환경 배포·검증 (FIFO 그룹 직렬화, 5분 중복 제거, 이벤트 소스 동시성 2, DLQ·경보) | 미완료 |
| 4 | Discord 실환경 검증 (DM 채널 마커 조회, `enforce_nonce`, 401·50007 응답) | 미완료 |
| 5 | DM 결과 큐 소비자·DB 계층 배포(`DM_SHARE_SEND_QUEUE_URL`=`.fifo` URL, `PLAYMATE_ENVIRONMENT` 설정, `DM_SHARE_ALLOW_STANDARD_QUEUE` 미설정), 053 적용 | 미완료 |
| 6 | Gateway 전환 절차 검증 (공동 선점 버전 확인, 폴링 끄기·롤백) | 미완료 |
| 7 | 운영 DM Worker 활성화 승인 → `DmProdActivationApproved=true`로 배포 | 미완료 |

`EnvironmentName=prod`에서 `DmWorkerEventSourceEnabled=true`이면 `DmProdActivationApproved=true`가 아닐 때 Rule이 **배포를 거부**한다 (기본 `false`).
시험 환경(`test`)은 3~4단계 검증을 위해 켤 수 있다. **이 Rule은 CloudFormation 배포만 막는다**: 콘솔·CLI(`update-event-source-mapping --enabled`)로
이벤트 소스를 직접 켜는 것은 막지 못하므로, 운영 계정의 IAM 권한과 변경 절차로 관리한다.
