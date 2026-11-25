# 댓글·대댓글 DM Lambda 전환: 배포·운영 문서 (초안)

> Issue #184: DB 실행 계층의 [기존 EC2 Runner](../../infra/discord-db-runner/DEPLOY.md)는 sender=LAMBDA와 기존 정책을 유지한다.
> EC2 방식에서는 DB Lambda/Scheduler를 만들지 않으며 롤백은 DM_MODE=recover로 실행한다.
> 최신 Worker 동시성은 2이고 DM 발송 FIFO 그룹 직렬화를 사용한다. 아래 과거 동시성 1 설명은 최신 SAM/FIFO 정책으로 대체된다.

Issue #171. **AWS 리소스는 하나도 만들지 않았고 운영 배포는 이 Issue 범위가 아니다.** AWS 동작 설명은 #163 `career_share/DEPLOY.md`와
같은 "문서 기준"이며 실제로 확인하지 않았다. **`053_notification_dm_deliveries.sql`은 잠정 번호다 (052 HOT도 잠정).**
DB 담당자가 번호를 확정하기 전에는 적용하지 않는다. #165(HOT) 브랜치를 기준으로 작업했다 (`contract._UNIT`, `CareerShareWorker.UNIT_PREFIXES` 의존).

## 1. 구성

```
backend 댓글 → notifications(PENDING)                                  ← 기존 그대로 (구조·CHECK 무변경)
                     │
       ┌─────────────┴───────────────────────────┐
 Gateway Bot (텍스트 DM, 10초)                DM DB Lambda (EventBridge 1분, {"action":"dm_relay"})
 PLAYMATE_DM_POLL_ENABLED                      Gateway 만료 마감 → 공동 선점 → [DM 발송 SQS] (TTL 50초)
 보내기 전에 공동 선점 (sender=GATEWAY)                 ↓
       │                                       DM Worker (VPC 밖, DB 없음, 예약 동시성 1, dm- 작업만)
       │                                         DM 채널 열기 → 마커 확인 → embed 전송 → [DM 결과 SQS]
       │                                                ↓
       └──── notification_dm_deliveries (notification_id PK, FK CASCADE) ──── DM DB Lambda (결과 기록·복구)
```

| Lambda | 핸들러 | 트리거 |
|---|---|---|
| DM DB Lambda | `dm_share.db_lambda.handler` | Scheduler(1분) + DM 결과 큐 + 수동 `{"action":"dm_summary"}` |
| DM Worker Lambda | `dm_share.worker_lambda.handler` | DM 발송 큐 |

재사용: `discord_rest.DiscordRestClient`(#161: `create_dm_channel`, `send_message`, `get_recent_messages`, `get_channel`),
`career_share`의 contract/state/queues, `CareerShareService`(발행·결과 반영), `CareerShareWorker`(마커 확인·발송·결과 불명 처리),
`handle_records`/`handle_results`, `services.notification_policy`(기존 문구·건너뜀 규칙을 config·discord.py 없이 분리), `web_links`.

## 2. 공동 선점 (중복 발송 방지의 핵심)

`repositories/dm_delivery_repository.py` 하나를 Gateway와 Lambda가 함께 쓴다.

1. `notifications`를 `FOR UPDATE OF n SKIP LOCKED`로 잡는다 → 두 선점자가 같은 행을 동시에 보지 않는다. 탈퇴 DELETE는 이 짧은 트랜잭션을 기다린다.
2. 행마다 **선점 시점의 최신 값**으로 건너뛸 대상을 판단한다 (알림 OFF, 탈퇴 = discord_id `w<id>`, 대상 삭제, 본인, 미지원 종류) → SKIPPED.
3. `INSERT … ON CONFLICT (notification_id) DO UPDATE … WHERE status='FAILED' AND next_retry_at <= now RETURNING`:
   행이 없거나 재시도 가능한 FAILED일 때만 성공한다. 재선점마다 `claim_token`이 바뀌고, 결과는 토큰이 같을 때만 반영된다.
   PENDING(다른 쪽이 보내는 중)·SENT·UNKNOWN·자동 재시도 없는 FAILED는 다시 선점되지 않는다 (테스트로 상태별 확인).
4. 행마다 savepoint: 그 사이 알림이 삭제되어 FK 위반이 나면 그 알림만 빼고 배치는 계속한다 (경고 로그).

그래서 **Gateway와 Lambda가 동시에 켜져 있어도 같은 알림은 한 번만 보낸다** (동시 선점·동시 실행 테스트로 확인).
**단, 공동 선점 코드가 없는 구버전 Gateway는 이 표를 모르므로 Lambda와 함께 실행하면 안 된다** (5절 순서).
053이 없으면 Gateway는 기존 방식(잠금 없는 claim_pending)으로 동작한다.

## 3. 상태 전이와 재시도

`notifications.retry_count`가 **유일한 실패 횟수**다. 실패할 때마다 +1, 3회째 `notifications.status = FAILED`. 재시도 간격은 기존과 같은 60초.
전송 행(`notification_dm_deliveries`)은 진행 상태만 가진다.

| 상황 | 전송 행 | notifications | 자동 재발송 |
|---|---|---|---|
| 건너뛸 대상 (선점·재선점 시 판단) | 없음 (기존 FAILED 행은 그대로) | SKIPPED | 없음 |
| 전송 성공 | SENT (+message_id) | SENT | — |
| Lambda: 429, 그 밖의 4xx(401 제외), 전송 전 실패, EXPIRED(TTL 경과·POST 직전 만료) | FAILED, next_retry = +60초 | retry_count+1, 3회째 FAILED | 60초 뒤 Lambda 재선점 (조건 재검사). **Gateway는 Lambda 선점 후 16분 뒤부터** |
| Lambda: 401 (인증 오류, 8절) | FAILED, 인증 표시 | **변경 없음** (retry_count 불변) | 차단기가 풀린 뒤 재선점 |
| Lambda: 403 code 50007 (DM 차단) | FAILED (재시도 없음) | **즉시 FAILED**, "DM 수신 차단 (403)" | 없음 |
| Lambda: code 10013/50033 (사용자 없음) | FAILED (재시도 없음) | SKIPPED "Discord 사용자 없음" | 없음 |
| Lambda: 5xx·타임아웃 (결과 불명) | 즉시 마커 확인 → 찾으면 SENT, 아니면 UNKNOWN | PENDING 유지 | **없음** |
| UNKNOWN 정착 대기(30분) 후 마커 확인 | 찾으면 SENT / 범위 초과·확인 불가면 그대로 (absent_count 0으로) | 찾으면 SENT | 없음 |
| 서로 다른 확인 2회에서 "미전송 증명" | FAILED, next_retry = +60초 | retry_count+1 | 조건 재검사 후 재선점 |
| 확인 한도(6회) 초과 | UNKNOWN 유지 | **FAILED** "확인 한도 초과, 재발송 안 함" (+1) | 없음 (경고 로그) |
| Lambda 선점 후 결과 없음 (10분) | UNKNOWN → 마커 확인 | — | 없음 |
| Gateway: 403·404·그 밖의 4xx·사용자 조회 실패 (미전송 확실) | FAILED, next_retry = +60초 | 기존 정책 그대로 retry_count+1, 3회째 FAILED | 60초 뒤 (Gateway 또는 Lambda 모두 가능) |
| Gateway: 5xx·타임아웃·연결 오류 (결과 불명) | FAILED (재시도 없음) | FAILED (+1) | **없음** (중복 대신 누락 가능, 경고 로그) |
| Gateway: fetch_user NotFound | FAILED (재시도 없음) | SKIPPED "Discord 사용자 없음" | 없음 |
| Gateway 선점 후 결과 없음 (10분, 프로세스 종료 등) | FAILED (재시도 없음) | FAILED (+1) | **없음** (경고 로그) |
| 결과 도착 시 선점 행 없음 | — | — | 원본 알림이 없으면 경고 `missing_notification`, 있으면 `ignored`(토큰 불일치) |

기존 Gateway 경로(053 없음)의 동작과 다른 점: 결과 불명 실패를 재시도하지 않는다 (기존은 재시도 → 중복 가능). Lambda는 50007을 즉시 FAILED로 끝낸다.

**nonce와 자동 재시도 (PR #172 리뷰 ③)**
- Gateway(discord.py 2.7.1): POST가 500/502/504/524를 받으면 **라이브러리 안에서 최대 5회 자동 재시도한다** (위 표의 "재발송 없음"은 라이브러리가
  예외를 올린 뒤의 이야기다). 대신 `Messageable.send`는 nonce를 주지 않아도 **호출마다 임의 nonce를 만들고 `enforce_nonce=true`를 붙이며**,
  본문을 한 번만 직렬화해 재시도마다 같은 값을 보낸다 (라이브러리 코드와 로컬 가짜 서버로 확인, `DiscordPyRetryNonce` 테스트). 그래서 Gateway는
  nonce를 따로 넘기지 않는다. 이 보호는 **한 번의 `user.send` 호출 안의 재시도에만** 적용된다 (Gateway의 다음 시도는 다른 nonce지만, 다음 시도는
  "미전송이 확실한 실패" 뒤에만 일어난다).
- Lambda Worker(`discord_rest`): POST는 5xx·타임아웃에 자동 재시도하지 않고(결과 불명 → 마커 확인), nonce `ref:dm-<id>`(25자 이내)와
  `enforce_nonce=true`를 보낸다. 같은 알림의 SQS 복사본은 같은 nonce를 쓴다.
- Gateway와 Lambda의 nonce는 다르다 (공동 선점으로 같은 알림을 두 경로가 함께 보내지 않으므로 맞출 필요가 없다).
- **보장 범위**: "최근 몇 분 안의 같은 작성자·같은 nonce 메시지를 새로 만들지 않는다"는 Discord 공식 문서 기준이며 실제 Discord에서 확인하지 않았다.
  "몇 분"의 길이도 문서에 없다. Discord가 이를 지키지 않으면 discord.py 내부 재시도로 Gateway 중복 DM이 생길 수 있다.

## 4. DM 형식 (Lambda)

embed 카드 1개. 제목 `💬 내 게시글에 새 댓글이 달렸어요.` / `↪️ 내 댓글에 새 답글이 달렸어요.`, 본문 `게시글: {제목}` +
`[🔗 PlayMate에서 보기](링크)`, footer **`ref:dm-{notification_id}`**(사용자에게 작은 회색 글씨로 보인다. 중복 확인 마커).
작성자·댓글 본문은 넣지 않는다 (기존 텍스트 DM과 같은 정보). 링크를 만들 수 없으면 링크 없이 보낸다 (기존과 같음).
Gateway는 기존 텍스트 형식을 유지하므로 **전환 기간에는 같은 사용자가 두 형식을 받을 수 있다.**

## 5. 환경변수와 전환·롤백

DM DB Lambda: `DB_*`, `DM_SHARE_SEND_QUEUE_URL`(필수, **FIFO 큐 `.fifo`여야 시작**(Issue #182, 아래 표준 큐 예외), 취업·HOT 발송 큐와 같으면 시작하지 않음),
**`PLAYMATE_ENVIRONMENT`(배포 시 반드시 설정: `prod` 또는 `test`)**, `PLAYMATE_WEB_BASE_URL`(선택),
선택: `DM_SHARE_RELAY_LIMIT`(20) `_JOB_TTL_SECONDS`(50, `_RETRY_SECONDS`보다 짧아야 시작) `_CLAIM_STALE_MINUTES`(10) `_RETRY_SECONDS`(60) `_MAX_ATTEMPTS`(3)
`_VERIFY_INTERVAL_MINUTES`(10) `_VERIFY_SETTLE_MINUTES`(30) `_ABSENT_REQUIRED`(2) `_MAX_VERIFIES`(6).
DM Worker: `DISCORD_BOT_TOKEN`, `DM_SHARE_RESULT_QUEUE_URL`. 채널은 작업의 받는 사람 DM 채널이다 (채널 ID 환경변수 없음).
Gateway: `PLAYMATE_DM_POLL_ENABLED` (없거나 비면 true, false/0/no/off면 DM 폴링만 끈다, true/false/1/0/yes/no/on/off 외의 값이면 Gateway가 시작하지 않는다. `/알림설정`은 계속 Gateway가 처리).
AWS 요구사항(VPC 엔드포인트, Worker 예약 동시성 1·배치 크기 1·ReportBatchItemFailures, DLQ, IAM 분리)은 #163 문서 4절과 같다.
SQS 작업에 받는 사람의 Discord ID가 들어가므로 큐 암호화(SSE)를 켠다. DB 권한은 053 하단 주석.

**표준 큐 예외 (Issue #182, `dm_share/settings.py` `standard_queue_allowed`)**: DM 발송 큐는 FIFO여야 한다. 표준 큐는 아래 **두 조건을 모두** 만족할 때만 허용한다.
- `PLAYMATE_ENVIRONMENT`가 `local` 또는 `test` (앞뒤 공백·대소문자 무시)
- `DM_SHARE_ALLOW_STANDARD_QUEUE=1` (정확히 `1`. `true` 등은 거부)

`prod`·`production`, 값 없음, 빈 값, 그 밖의 값(`dev`, `staging` 등)이면 플래그가 있어도 **시작하지 않는다** (`SettingsError`).
FIFO 큐(`.fifo`)는 환경과 플래그에 관계없이 그대로 허용된다.
**DM DB Lambda를 배포할 때 `PLAYMATE_ENVIRONMENT`를 반드시 설정한다** (`prod` 또는 `test`, SAM의 `EnvironmentName`과 같은 값).
DM DB 계층은 SAM 템플릿 밖이라 이 값을 자동으로 넣어 주는 곳이 없다. 비워 두면 표준 큐 우회는 막히고(안전한 기본값) FIFO 발행은 정상 동작한다.

**전환**
1. 053 적용 (번호 확정 후, DB 담당자)
2. **이 브랜치의 Gateway를 먼저 배포** (플래그 기본 true). `dm_summary` 또는 DB에서 `sender=GATEWAY`, `status=SENT` 행이 쌓이는지 확인
3. DM Worker·결과 큐 이벤트 소스 활성화 → DM DB Lambda Scheduler(1분) 활성화. 이때 둘 다 켜져 있어도 PK가 중복을 막는다
4. Gateway에 `PLAYMATE_DM_POLL_ENABLED=false` 설정 후 재시작
5. 확인: 최근 행의 sender가 LAMBDA, `LAMBDA:UNKNOWN`·DLQ가 0에 가까움

**롤백**
1. Gateway `PLAYMATE_DM_POLL_ENABLED=true`로 재시작 (공동 선점 버전이어야 한다)
2. DM DB Lambda의 `dm_relay` Scheduler를 끄고, 대신 `{"action":"dm_recover"}` Scheduler(10분)를 켠다.
   `dm_recover`는 **신규 선점 없이** 진행 중 건의 마커 확인과 한도 초과 마감만 한다. 결과 큐 처리와 Worker는 계속 켜 둔다
3. `LAMBDA:PENDING`/`LAMBDA:UNKNOWN`이 마감될 때까지 기다린다 (`dm_summary`로 확인. 최대: 선점 만료 10분 + 정착 30분 + 확인 6회 x 10분)
4. 그 뒤 Worker와 결과 처리를 끈다. 전송 행은 지우지 않는다. Gateway는 Lambda의 진행 중·불명 건을 보내지 않고, 미전송이 확실한 FAILED만 이어받는다 (테스트로 확인)
5. **구버전 Gateway(공동 선점 없음)로 되돌리는 것은 금지**. 구버전은 이 표를 보지 않으므로 `notifications`가 아직 PENDING인 알림
   (Lambda UNKNOWN 건, Gateway 결과 대기 건 포함)을 다시 보낸다. 다른 이유로 봇 코드를 되돌려야 하면 Lambda를 모두 끄고 3단계가 끝난 뒤에도
   중복 가능성이 남는다는 것을 받아들이고 진행한다 (가능하면 공동 선점 코드만 남긴 수정 버전으로 되돌린다).

**배포 중 주의**
- Gateway는 한 프로세스만 실행한다 (무중단 배포로 신·구 Gateway가 겹치면 구버전이 공동 선점을 모른다). 재시작형 배포를 쓴다.
- 053 적용과 신버전 Gateway 배포 사이에는 Lambda를 켜지 않는다 (구버전 Gateway + Lambda = 중복). 053만 먼저 적용하는 것은 안전하다 (구버전은 표를 무시).
- `PLAYMATE_DM_POLL_ENABLED` 값을 잘못 적으면(예: `fasle`) Gateway가 설정 오류로 시작하지 않는다 (Issue #190. 예전에는 폴링이 켜진 채로 남았다).
  EC2에서는 `runtime/start_gateway.py --check`로 먼저 검사한다.

**PR #174 (compatibility View removal)**: Gateway, Lambda, notification, content and career notice repositories read the consolidated `career` table directly. The legacy View removal must be deployed only after the updated consumers have been verified.


## 6. 남은 위험 (코드로 없앨 수 없음)

- **알림 OFF·탈퇴 후 발송**: 선점 시점에는 확인하지만, 이미 SQS에 들어간 작업은 Worker가 DB를 보지 않으므로 **TTL(50초) 안에 시작된 전송은 완료될 수 있다** (429 재시도가 길어지면 TTL 뒤에 끝날 수도 있음).
  탈퇴의 경우 알림 행이 지워져 결과는 `missing_notification` 경고로만 남는다. 보낸 DM은 회수하지 않는다 (메시지 삭제 기능 없음).
- Worker 예약 동시성 1 설정에 의존한다 (두 Worker가 같은 작업을 동시에 처리하면 둘 다 마커를 못 찾고 보낼 수 있음).
- Gateway 결과 불명·만료는 재발송하지 않으므로 **DM이 누락될 수 있다** (실제로는 전송됐을 수도 있음).
- "미전송 증명" 2회 뒤 원래 메시지가 아주 늦게 저장되면 중복이 생길 수 있다 (확률 매우 낮음).
- 확인 한도 초과로 FAILED 마감된 건은 실제로 전송됐을 수도 있다.
- 구버전 Gateway와 Lambda의 동시 실행은 운영 순서로만 막을 수 있다.
- **R4 잔여 위험**: 16분 제한은 "클라이언트 요청이 Worker 실행 안에서 끝난다"까지만 보장한다. 클라이언트가 포기(타임아웃)한 뒤 Discord가
  메시지를 16분 넘게 늦게 저장하면 Gateway 인수와 중복될 수 있다 (이론적, 0이 아님).
- 인증 표시가 붙은 Lambda 행을 Gateway가 이어받아 표시가 모두 사라지면, 다음 Lambda 선점이 정상 모드로 돌아가 최대 `relay_limit`건이
  다시 401을 받을 수 있다 (재시도 횟수는 소모하지 않고 즉시 다시 차단된다).
- DM 지연: Gateway 10초 → Lambda 1분 주기 (평균 약 30초 증가).

## 7. R4: 교차 재선점 제한과 TTL 50초

> **Issue #182 (FIFO 전환)**: 아래의 "Lambda→Lambda는 예약 동시성 1과 마커로 막힌다"는 이제 **FIFO 메시지 그룹(= `dm-<알림 ID>`) 직렬화와 마커**로 막는다.
> 발송 큐는 FIFO, `MessageDeduplicationId = job_id`, Worker 예약 동시성 2 = 이벤트 소스 최대 동시성 2 (`dm_share/fifo.py`,
> `infra/discord-serverless/DEPLOY.md` 15.4). Gateway의 16분 인수 제한, TTL 50초 < 재시도 60초 검증, POST 직전 만료 확인은 그대로다.

**왜 바꿨나**: Lambda 작업이 429로 실패(FAILED_RETRY)한 뒤 60초가 지나 Gateway가 이어받아 텍스트 DM을 보냈는데, 같은 Lambda 작업의
SQS 중복 복사본이 TTL(90초) 안에 도착해 embed DM을 한 번 더 보냈다 (Gateway DM에는 마커가 없어 Worker가 확인할 수 없다).
TTL만 50초로 줄여도 **이미 시작된 POST**는 막지 못했다: 만료 1초 전에 시작한 POST가 429를 받아 클라이언트가 기다렸다 재시도하면
(`max_retries=3`, `max_retry_after=30초`) 재선점 뒤에 성공한다 (테스트로 재현).

**적용한 것**
- Gateway가 `sender=LAMBDA`인 FAILED 행을 이어받으려면 **그 Lambda 선점(`claimed_at`) 후 16분이 지나야 한다.** 후보 SQL과 UPSERT 조건 양쪽에서
  DB 시각(`CURRENT_TIMESTAMP`)으로 판정한다. 근거: 진행 중인 Lambda HTTP 요청은 Worker 실행이 끝나면 끝나고 AWS Lambda 실행 상한은 15분이다.
- 그 밖의 재선점(Lambda→Lambda, Gateway→Gateway, Gateway→Lambda)은 **60초 그대로**다. Lambda→Lambda는 예약 동시성 1과 마커로 막힌다
  (B가 끝난 뒤 새 작업이 마커를 찾는다, 테스트로 확인). Gateway→Lambda는 Gateway가 전송을 끝낸 뒤에만 실패를 기록하므로 진행 중 요청이 없다.
- TTL 50초 + `job_ttl_seconds < retry_seconds` 검증 (어기면 DB Lambda가 시작하지 않음): 재선점 시점에는 이전 작업 복사본이 모두 만료라 새로 시작하지 않는다.
- Worker가 POST 직전에 `not_after`를 다시 확인한다 (사전 조회가 오래 걸려 만료됐으면 보내지 않고 EXPIRED).
- `claimed_at`은 선점자 시계로 기록되고 판정은 DB 시각이다. 16분 여유에 비해 시계 차이(NTP 수 초)는 무시할 수 있다.

**지연**: 전환·롤백 중 Lambda가 실패한 알림은 Lambda가 켜져 있으면 60초 뒤 Lambda가 다시 보내고, Lambda를 끈 상태(롤백)에서는
Gateway가 **최대 16분 뒤**에 이어받는다.

## 8. R5: Discord 401 인증 차단기

401은 토큰 문제라 알림마다 다시 보내도 같다. 실패 횟수로 세면 토큰 장애 2~3분 만에 대기 알림이 모두 영구 FAILED가 됐다 (재현됨). 이제는:
- Worker는 401을 `auth_error=True` 결과로 보낸다. POST 401과 첫 전달의 사전 조회·DM 채널 401은 "전송되지 않음"(FAILED_RETRY),
  **재전달 작업의 사전 조회 401은 "전송 여부 불명"(UNKNOWN)**, 확인 작업의 401은 판단 보류(INCONCLUSIVE)로 구분한다.
- DB는 `notifications.retry_count`를 올리지 않고, 전송 행 `error_message`에 `DISCORD_AUTH_401…`을 DB 시각과 함께 남긴다 (차단기 상태).
- **차단기** (기존 컬럼 + advisory lock): 모든 Lambda 선점은 `pg_advisory_xact_lock(610171001)`으로 직렬화되고, 그 안에서 상태를 판정한다.
  - 최근 10분 안에 401이 있었거나 시험 발송이 진행 중이면 **선점 0건** (신규 알림 포함)
  - 마지막 401에서 10분이 지났으면 **1건만 시험 선점** (`DISCORD_AUTH_PROBE` 표시). 동시에 여러 Lambda가 실행돼도 1건 (테스트로 확인)
  - 시험이 401이면 다시 10분 차단. 401이 아닌 응답(성공 포함)을 받으면 토큰은 정상이므로 표시를 모두 지우고 정상 처리를 재개한다
  - 시험 결과가 유실되면 선점 만료 때 인증 표시를 유지한 채 UNKNOWN이 되고 다시 10분 차단된다
- **UNKNOWN 보존**: 인증 표시가 있는 동안 마커 확인과 확인 한도 마감을 멈춘다 (`paused_auth`). 확인 작업의 401은 UNKNOWN·`absent_count`를 그대로 두고
  발행 때 올린 `verify_count`만 되돌린다 (같은 결과가 중복 도착해도 한 번만). 인증이 복구되면 확인을 이어서 하며, 미전송이 증명되기 전에는 재발송하지 않는다.
- **24시간**: 인증 표시가 24시간 넘게 남아 있으면 매 실행마다 `인증 장애가 24시간 이상 지속` ERROR 로그를 남긴다. **자동 FAILED·삭제는 하지 않는다.**
- 첫 401 직전 배치(최대 `relay_limit`건)는 이미 발송 시도된 뒤라 모두 401을 받을 수 있다 (재시도 횟수 미소모).

**경보**: CloudWatch Logs 지표 필터로 `DISCORD_AUTH_401`(즉시 경보)과 `24시간 이상 지속`(강화 경보)을 건다. 401 결과는 정상 결과로 반영되므로
DLQ로 가지 않는다. DLQ에는 형식 오류와 반복된 일시 오류(조회 실패 등)가 간다: DLQ 메시지 수 > 0 경보를 따로 둔다.

**인증 장애 대응 순서**
1. 경보 확인 → `{"action":"dm_summary"}`에서 `auth_blocked=true` 확인
2. Worker Lambda의 `DISCORD_BOT_TOKEN`(시크릿) 확인·교체. Gateway가 같은 토큰을 쓰면 Gateway 로그도 확인
3. 아무것도 지우지 않는다. 다음 시험 발송(마지막 401 후 10분)이 성공하면 자동으로 정상 재개된다
4. `dm_summary`에서 `auth_blocked=false`, `LAMBDA:FAILED`가 줄고 `LAMBDA:SENT`가 느는지 확인. UNKNOWN은 마커 확인 후에만 정리된다
5. Gateway로 롤백해야 하면 5절 순서대로 (Gateway는 차단기와 무관하게 자기 토큰으로 보낸다. 인증 표시가 붙은 Lambda 행도 16분 뒤 이어받는다)

**DLQ 복구 순서**: 원인(형식 오류·권한·조회 실패)을 고친 뒤 발송 DLQ는 **재처리하지 않고 버린다** (작업은 TTL 50초라 어차피 만료이고, 해당 행은
선점 만료 → UNKNOWN → 마커 확인으로 복구된다). 결과 DLQ는 DB Lambda가 정상화된 뒤 결과 큐로 되돌려 재처리한다 (결과 반영은 멱등이다).

## 9. 실제 환경에서 확인해야 할 것 (미검증)

- 봇이 DM 채널 메시지 목록을 조회할 수 있는지, embed footer가 그대로 오는지, DM 채널의 `last_message_id` (마커 확인 전체가 여기에 의존. 가짜 서버로만 확인)
- 10013/50033/50007의 실제 HTTP 상태와 응답, DM 채널을 연속으로 열 때의 제한
- 운영 DB에서 backend·Gateway·Lambda 계정의 세션 TimeZone (notifications의 `last_attempt_at` 60초 비교가 같은 의미여야 함. 코드상 Gateway·Lambda는 모두 Asia/Seoul)
- AWS: Scheduler, VPC 엔드포인트, 이벤트 소스 매핑, 예약 동시성, DLQ, SSE
- 운영 DM 발생량 대비 Worker 예약 동시성 1의 처리량
- Discord가 잘못된 토큰에 401을 주는지와 응답 본문, 401 이후 rate limit/IP 차단 동작 (차단기는 401을 전제로 한다)
- Worker Lambda 실행 시간 설정이 15분 상한 안에 있는지 (16분 교차 인수 제한의 전제)
- Discord가 클라이언트 타임아웃 뒤 메시지를 얼마나 늦게 저장할 수 있는지 (아래 남은 위험)
