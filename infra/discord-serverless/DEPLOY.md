# Discord 서버리스 3안 — 취업 공유 Worker 인프라 (AWS SAM)

3안: **PostgreSQL Outbox + Amazon SQS + AWS Lambda**. 이 스택은 그중 **발송 큐·결과 큐·Discord Worker Lambda**만 만든다.
DB 처리 계층(DB Lambda 또는 기존 EC2 실행기)과 EventBridge Scheduler는 **만들지 않는다** (운영 DB·접속 경로 미확정).

> **이 문서의 어떤 단계도 아직 실제 AWS에서 실행·검증하지 않았다.** 로컬에서 확인한 것은 템플릿 정적 검증, 패키징, 핸들러 흐름
> (가짜 Discord·가짜 큐) 테스트뿐이다 (`playmate-discord-bot/tests/test_serverless_infra.py`). SAM CLI로 `sam validate`/`sam build`도 아직 돌리지 않았다.

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
6. `sam validate --lint`, `sam build`를 실제 SAM CLI로 실행 (이번 로컬 작업에서는 SKIP)
7. 결과 큐 소비자(DB 계층)를 **먼저** 배포한 뒤 운영 Worker를 켠다 (3절 "결과 큐에 소비자가 없을 때의 위험")
8. 동시성 2 결정과 남은 중복 위험(3절)을 팀이 수용했는지 확인 (아니면 FIFO 전환을 별도 Issue로)

## 13. 롤백

1. **즉시 중단**: 이벤트 소스 비활성 (`aws lambda update-event-source-mapping --uuid <ID> --no-enabled` 또는 `CareerWorkerEventSourceEnabled=false`로 재배포).
   발송 큐에 남은 작업은 그대로 두면 TTL(10분) 뒤 보내지지 않는다
2. 템플릿 변경 롤백: 이전 커밋으로 `sam build` + `sam deploy` (CloudFormation 변경 세트 확인)
3. 스택 삭제(`sam delete`)는 **큐와 그 안의 메시지·DLQ·로그 그룹을 함께 지운다**. 삭제 전 DLQ·결과 큐 내용을 확인한다. 시크릿·SNS는 스택 밖이라 남는다

## 14. HOT·DM 확장 (같은 패턴)

`hot-share`, `dm-share`로 같은 4개 큐 + Worker + 역할 + 로그 그룹 + 경보를 추가하고 `build_package.py`의 `PACKAGES`에 `hot_worker`/`dm_worker`를 넣는다.
- HOT Worker: `HOT_SHARE_CHANNEL_ID`, `HOT_SHARE_RESULT_QUEUE_URL`, `WORKER_TARGET_HANDLER=hot_share.worker_lambda.handler` (패키지에 `hot_share/` 추가)
- DM Worker: 채널 환경변수 없음(받는 사람 DM 채널), `DM_SHARE_RESULT_QUEUE_URL`, `dm_share.worker_lambda.handler`. DM Worker는
  `repositories.dm_delivery_repository`(상수·함수)와 `services.notification_policy`를 import하므로 패키지 규칙을 따로 검토한다. DM 큐는 받는 사람 Discord ID가 들어가므로 SSE 유지
- 세 Worker가 같은 봇 토큰 시크릿을 쓰면 시크릿 읽기 권한만 각 역할에 준다
