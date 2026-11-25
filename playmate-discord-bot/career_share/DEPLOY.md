# 취업 게시글 Discord 자동 공유: 배포·운영 문서 (초안)

> Issue #184: DB 실행 계층은 [기존 EC2 Runner](../../infra/discord-db-runner/DEPLOY.md)로도 운영한다.
> 아래 DB Lambda/Scheduler 설명은 기존 인터페이스 참고이며 EC2 방식에서는 해당 리소스를 만들지 않는다.
> 최신 Worker 동시성은 SAM template.yaml 기준 2다. 과거 예약 동시성 1 설명과 구분한다.

Issue #163. **이 문서는 초안이며 AWS 리소스는 하나도 만들지 않았다.** 아래 AWS 동작 중 "문서 기준"은 AWS 공식 문서의 일반 동작을
적은 것이고 이 프로젝트에서 실제로 확인한 것이 아니다 (실제 AWS 테스트 필요 항목은 맨 아래).

## 1. 구성

```
EventBridge Scheduler(1분)            ─▶ DB Lambda {"action":"relay"} ─┐
EventBridge Scheduler(매일 20:00 KST) ─▶ DB Lambda {"action":"digest"} ┤  (VPC 안, PostgreSQL)
                                                                       ▼ 선점 + 메시지 생성
                                                              [발송 SQS 표준 큐] ─▶ DLQ(발송)
                                                                       ▼
                                          Discord Worker Lambda (VPC 밖, DB 없음) ─▶ Discord REST API
                                                                       ▼
                                                              [결과 SQS 표준 큐] ─▶ DLQ(결과)
                                                                       ▼
                                                      DB Lambda (SQS 이벤트 소스, 결과 기록)
```

| Lambda | 핸들러 | 트리거 | 하는 일 |
|---|---|---|---|
| DB Lambda | `career_share.db_lambda.handler` | Scheduler 2개 + 결과 큐 | relay(신규 후기 선점→큐), digest(20시 묶음 선점→큐), recover(만료/불명 건 확인 작업 발행), 결과 반영, baseline/summary(수동) |
| Worker Lambda | `career_share.worker_lambda.handler` | 발송 큐 | 마커 확인 → Discord 전송 → 결과 큐 발행. **DB에 접근하지 않는다** |

코드 재사용: `discord_rest.DiscordRestClient`(#161, 재시도/오류 분류/멘션 기본 차단), `services.web_links.career_post_url`(링크),
`repositories.db.Database`(연결/트랜잭션 헬퍼). 기존 `config.py`, discord.py, Gateway 코드는 import하지 않는다.

## 2. 이벤트 계약

`contract.py` 상단 주석이 기준이다. 요약: 작업(`send`/`verify`)에는 `unit_id`(`post-<id>` 또는 `digest-YYYY-MM-DD`), `claim_token`
(DB 선점 소유권), `claimed_at`, `not_after`(이후에는 Worker가 보내지 않음), `marker`(`ref:<unit_id>`)가 있다. 결과의 `outcome`:
`SENT / FAILED_RETRY / FAILED_PERMANENT / EXPIRED / UNKNOWN / ABSENT_PROVEN / INCONCLUSIVE`.

**SQS 표준 큐는 최소 1회 전달이다. exactly-once가 아니다.** 같은 작업/결과가 두 번 올 수 있으므로 (1) 결과 반영은 `claim_token`과
상태 전이 표(`state.py`)로 멱등이고 (2) Worker는 보내기 전에 채널에서 마커를 확인한다. 이 확인은 중복을 크게 줄이지만 **완전히 없애지는
못한다** (아래 5절의 남은 위험).

## 3. 환경변수

DB Lambda (VPC 안)
| 이름 | 설명 |
|---|---|
| `DB_HOST DB_PORT DB_USER DB_PASSWORD DB_NAME DB_SSLMODE` | 기존 Bot과 같은 이름. 시크릿 매니저에서 주입 권장 |
| `CAREER_SHARE_SEND_QUEUE_URL` | 발송 큐 URL (필수) |
| `PLAYMATE_WEB_BASE_URL` | 링크 기준 주소. 비었거나 localhost면 **아무것도 선점/전송하지 않는다** |
| `CAREER_SHARE_CUTOVER_AT` | **필수.** 예 `2026-12-01T00:00:00+09:00` (시간대 필수). 이 시각 이후에 만든 글만 공유 |
| `CAREER_SHARE_RELAY_LIMIT`(20) `_MAX_ATTEMPTS`(3) `_RETRY_BASE_MINUTES`(5) `_JOB_TTL_MINUTES`(10) `_CLAIM_STALE_MINUTES`(30) `_VERIFY_INTERVAL_MINUTES`(10) `_VERIFY_SETTLE_MINUTES`(30) `_ABSENT_REQUIRED`(2) `_MAX_VERIFIES`(6) `_DIGEST_LIMIT`(5, 상한 5) | 선택. `CLAIM_STALE > JOB_TTL`, `MAX_VERIFIES > ABSENT_REQUIRED`이어야 시작한다 |

Worker Lambda (VPC 밖): `DISCORD_BOT_TOKEN`(시크릿), `CAREER_SHARE_CHANNEL_ID`(기존 `💼│취업-소식` 채널 ID), `CAREER_SHARE_RESULT_QUEUE_URL`.
Worker는 작업이 가리키는 채널이 아니라 **자기 환경변수의 채널**로만 보낸다.

## 4. AWS 설정 요구사항 (초안)

- **VPC 안 DB Lambda → SQS 경로**: VPC 안 Lambda는 기본적으로 인터넷에 나갈 수 없다. 발송 큐에 게시하려면 SQS **인터페이스 VPC 엔드포인트**
  (`com.amazonaws.<region>.sqs`) 또는 NAT가 필요하다 (문서 기준). 결과 큐는 이벤트 소스 매핑이 Lambda 서비스 쪽에서 읽으므로 DB Lambda가 직접
  접속하지 않는다 (문서 기준). 엔드포인트 보안 그룹은 Lambda의 보안 그룹에서 443을 허용해야 한다.
- **Worker는 VPC 밖**: Discord(인터넷)에 직접 나간다. DB 자격 증명을 주지 않는다 (IAM/환경변수 모두).
- **Scheduler**: 타임존 `Asia/Seoul`. 20시 배치 `cron(0 20 * * ? *)`, 입력 `{"action":"digest","scheduled_at":"<aws.scheduler.scheduled-time>"}`
  (이 컨텍스트 속성 치환은 문서 기준, 실제 확인 필요. 값이 비정상이어도 현재 시각의 KST 날짜로 진행한다).
  1분 배치 `rate(1 minute)`, 입력 `{"action":"relay"}`. DB Lambda 예약 동시성 1을 권장한다 (같은 Lambda가 겹쳐 실행되지 않게. 겹쳐도 DB 선점은 안전하다).
- **발송 큐 / Worker 이벤트 소스 (필수 설정, 선택 아님)**: Worker **예약 동시성 = 1**, 이벤트 소스 **배치 크기 = 1**, `ReportBatchItemFailures` 켬.
  이것이 없으면 같은 작업을 두 Worker가 동시에 처리해 **둘 다 마커를 못 찾고 둘 다 보내는 중복 게시**가 코드로는 막히지 않는다 (테스트로 재현한 한계).
  예약 동시성 1을 지켜도 표준 큐의 동시 중복 전달 가능성이 0은 아니다 (아래 5절 "남은 위험"). Worker 함수 타임아웃은 60초 이상(조회 최대 4회 + 전송 + 429 대기)을 권장하고 그 6배 이상으로 가시성 타임아웃을 둔다 (미검증, 실제 소요시간 측정 필요).
- **발송 큐**: 표준 큐. 가시성 타임아웃 ≥ Worker 함수 타임아웃 × 6 (AWS 권장), Worker **예약 동시성 1, 배치 크기 1**, `ReportBatchItemFailures` 켬.
  Discord 메시지 전송 순서와 속도(채널당 초당 한도)를 지키려는 것이다. 예약 동시성 1이면 스로틀로 수신 횟수가 늘 수 있으므로
  `maxReceiveCount`는 5 이상으로 하고 DLQ를 연결한다. 메시지 보존 기간 ≥ 1일 (`not_after`는 10분이라 오래된 작업은 어차피 보내지 않는다).
- **결과 큐**: 표준 큐, DB Lambda 이벤트 소스 매핑 (`ReportBatchItemFailures`), DLQ 연결. DLQ 메시지는 사람이 확인한다 (본문에 `unit_id`, `message_id` 있음).
- **IAM**: DB Lambda = 발송 큐 `sqs:SendMessage` + 결과 큐 `ReceiveMessage/DeleteMessage/GetQueueAttributes` + 시크릿 읽기 + VPC 접근 역할.
  Worker = 발송 큐 수신 권한 + 결과 큐 `SendMessage` + 토큰 시크릿 읽기. 서로의 권한을 주지 않는다.
- **DB 계정 권한**: `048_career_discord_share.sql` 하단 주석 참고 (SELECT posts/career, SELECT·INSERT·UPDATE 이력 2개 테이블).
- **Discord 봇 권한**: 대상 채널에 `View Channel`, `Send Messages`, **`Read Message History`**(마커 확인에 필수), `Embed Links`.
  Read Message History가 없으면 Discord는 오류 없이 빈 목록을 주므로 중복 방지 확인이 약해지고 UNKNOWN이 늘어난다.
- **패키징**: `career_share/`, `discord_rest/`(core 모듈), `services/web_links.py`, `repositories/db.py`, `repositories/__init__.py`, `services/__init__.py`.
  Worker는 표준 라이브러리 + `discord_rest`만 필요 (discord.py/psycopg 불필요). DB Lambda는 `psycopg[binary]`를 **Linux(Lambda) wheel**로 넣는다
  (이 PC는 Windows wheel이라 그대로 쓸 수 없음). `discord_rest/reuse.py`는 import하지 않는다. Python 3.10 이상 필요 (`X | None` 문법).

## 5. 중복 방지와 복구 (요약)

- **선점**: `career_discord_announcements.post_id` 기본키 + `INSERT … ON CONFLICT DO UPDATE WHERE status='FAILED' AND next_retry_at <= now AND attempt_count < 한도`.
  advisory lock으로 같은 종류의 선점을 직렬화. 컷오버 이전 글은 조회에서 제외 + `baseline`으로 BASELINE 기록 (이중 안전장치).
- **묶음**: `career_discord_share_batches.batch_date PRIMARY KEY`(2컬럼: `batch_date`, `created_at`) → 같은 KST 날짜의 두 번째 실행은 아무것도 선점하지 못한다. 배치 행 INSERT와 글 선점은 한 트랜잭션이다. 오래된 순(`created_at, post_id`) 최대 5건.
- **상태**: `PENDING`(선점) → `SENT` / `FAILED`(재시도 가능, `next_retry_at`) / `UNKNOWN`(전송되었을 수도 있음). UNKNOWN은 **자동 재발송하지 않는다**.
- **복구 (결과 불명 요청의 조기 재발송 방지)**: 선점 후 `claim_stale_minutes`(30분)가 지나도 결과가 없으면 PENDING→UNKNOWN, Worker가 5xx/타임아웃으로 `UNKNOWN`을 보고해도 마찬가지다.
  **UNKNOWN이 된 시각(`last_verified_at`)이 정착 기준점**이며 첫 `verify`는 그로부터 `verify_settle_minutes`(30분) 뒤에야 나간다 (클라이언트가 5xx/타임아웃을 받은 뒤에도 Discord가 뒤늦게 메시지를 저장할 수 있다).
  이후 확인은 `verify_interval_minutes`(10분) 간격이다. Worker가 채널을 최대 300개(3페이지) 훑어 마커를 찾으면 `SENT`. 못 찾아도 **조회가 `claimed_at` 이전 메시지까지 닿은 경우만** `ABSENT_PROVEN`이고,
  **서로 다른 확인 작업에서 `absent_required`(2)번 연속** 증명돼야 FAILED→재시도한다 (같은 확인 결과의 중복 도착은 한 번으로 센다. `INCONCLUSIVE`가 끼면 처음부터 다시 센다). 아니면 UNKNOWN 유지(최대 6회 확인 후 사람 확인).
  따라서 결과 불명 건의 최단 자동 재발송은 UNKNOWN 후 약 40분이다. **이것은 중복이 불가능하다는 뜻이 아니다**: 서버가 그보다 더 늦게 저장하면 여전히 중복될 수 있으므로 중복 방지가 우선인 운영이면 `UNKNOWN`을 사람이 확인하도록 `verify_settle_minutes`/`absent_required`를 키운다.
  재전달된 작업이 `not_after`를 넘겼으면 `EXPIRED`(미전송)가 아니라 `UNKNOWN`으로 보고한다 (앞선 전달이 보냈을 수 있음).
  뒤늦은 발송 방지: 작업의 `not_after`(10분)가 지나면 Worker가 보내지 않고, 복구는 30분 뒤에만 시작한다. **Lambda/SQS 시계 차이가 크면 이 보장이 약해진다.**
- **SQS 발행 실패**: 큐에 들어갔는지 알 수 없으므로 FAILED로 단정하지 않고 PENDING으로 둔 채 위 복구로 처리한다 (복구까지 최대 약 30분 지연).
- **영구 오류(401/403/404/400)**: FAILED + `next_retry_at=NULL` (자동 재시도 없음). 설정을 고친 뒤 `UPDATE … SET status='FAILED', next_retry_at=…`로 사람이 풀어 준다.
  특히 **401은 토큰 문제라 전체가 멈춘다** (Discord는 잘못된 요청 반복 시 IP를 일시 차단할 수 있다).
- **운영 확인**: `{"action":"summary"}` → 상태별 건수와 `FAILED_NO_AUTO_RETRY`. UNKNOWN/FAILED_NO_AUTO_RETRY가 0이 아니면 알림을 걸 것 (CloudWatch 로그 필터 권장).
- **남은 위험**: (1) SQS 표준 큐가 같은 작업을 **동시에** 두 Worker에 전달하면 둘 다 마커가 없다고 보고 보낼 수 있다 (예약 동시성 1로 완화, 제거는 불가. 로컬에서 두 Worker를 동시에 돌려 중복 2건이 나옴을 재현했다).
  (2) Read Message History 권한 문제로 마커를 못 볼 때 첫 전달에서는 전송을 진행한다 (재전달이면 UNKNOWN). (3) `nonce`(enforce_nonce)를 같이 보내지만
  **실제 Discord에서 검증하기 전이라 의존하지 않는다**. 

## 6. 컷오버 절차 (기존 18:00 공지 → 이 기능)

기존 Gateway Bot의 18:00 `CareerNoticeService`와 이 기능을 **동시에 켜지 않는다** (같은 `career_discord_announcements`를 쓰고, 이 기능의 FAILED 행을 기존 공지가 집어 갈 수 있다).
기존 스위치: `PLAYMATE_CAREER_NOTICE_ENABLED` (기본 켜짐; `false/0/no/off`일 때만 꺼짐). **`PLAYMATE_CAREER_CHANNEL_ID`는 비우지 않는다** (공식 채널 보호 목록에 쓰인다).

**동시 활성 금지 조건**: 기존 18:00 공지가 켜져 있는 동안에는 이 기능의 Scheduler를 켜지 않는다. 기존 공지(`claim_due`)는 상태가 `FAILED`이고 시도 횟수가 3 미만인 행이면 `share_kind`와 무관하게 선점한다 (테스트로 재현).
이 기능은 그런 행(기존 공지가 `announce_date`를 채운 행)을 **자기 소유가 아니라고 보고 상태 변경, 복구, 재선점을 하지 않는다**(코드로 방어). 그래도 기존 공지가 먼저 보내 버린 글이 있을 수 있으므로 동시 활성은 금지다.
감지: `{"action":"summary"}`의 `CLAIMED_BY_LEGACY_NOTICE`가 0이 아니면 18:00 공지가 켜져 있다는 신호다 → 즉시 Scheduler를 끄고 조사한다.

1. (DB 담당) 검증 DB에서 `048_career_discord_share.sql` 적용 → 확인 후 운영 적용. 013은 수정하지 않는다.
2. 스위치 코드가 들어간 Bot을 먼저 배포 (기본값이 켜짐이라 동작 변화 없음).
3. DB Lambda/Worker/큐/DLQ 배포, **Scheduler는 비활성** 상태로 둔다. Worker는 실제 채널이 아닌 시험 채널로 먼저 확인.
4. 컷오버 시각 `T`를 정한다 (예: 당일 18:00 공지가 끝난 직후). `CAREER_SHARE_CUTOVER_AT=T`로 설정하고 `{"action":"baseline"}`을 한 번 실행.
   - T 이전에 쓰였지만 기존 18:00 공지가 아직 못 보낸 글은 **공유되지 않는다** (필요하면 수동 공유). T를 18:00 공지 직후로 잡으면 공백이 거의 없다.
5. `PLAYMATE_CAREER_NOTICE_ENABLED=false`로 Bot 재시작 → 로그에 `18:00 공지를 실행하지 않습니다`가 보이는지 확인.
6. Scheduler 활성화 (relay, digest). 첫 1~2회는 `summary`와 Discord 채널을 사람이 확인.
- **롤백**: Scheduler 비활성 → `PLAYMATE_CAREER_NOTICE_ENABLED=true`로 Bot 재시작. 이 기능이 만든 PENDING/UNKNOWN 행은 먼저 확인한다 (기존 공지는 `share_kind='LEGACY'`가 아닌 행도 FAILED면 집을 수 있다 → 롤백 전 해당 행을 정리).

## 7. 공개 범위 위험 (제목)

메시지에는 **글 제목**이 그대로 들어간다 (본문, 작성자 닉네임, 익명 정보는 넣지 않는다). 제목에 개인정보, 기업명, 면접 내용이 들어 있을 수 있고,
`💼│취업-소식`은 서버 구성원에게 보이는 채널이다. 익명 글(`is_anonymous`)도 제목은 공개된다. 서버 공개 범위(외부 초대/공개 서버 여부)를 확인하고, 필요하면
제목 필터링 또는 후기 공유 동의 정책을 정할 것. 멘션은 보내지 않으며(`allowed_mentions: {"parse": []}`, `@` 뒤 제로폭 문자) Markdown 링크 문법은 이스케이프한다.

## 8. 실제 AWS/Discord에서 확인해야 할 것 (미검증)

- VPC 엔드포인트/NAT 경로로 DB Lambda가 발송 큐에 게시되는지, 결과 큐 이벤트 소스 매핑 동작, DLQ 이동, 가시성 타임아웃 값.
- Scheduler 타임존(`Asia/Seoul`)과 `<aws.scheduler.scheduled-time>` 치환, 1분 주기 지연 분포.
- Lambda(Linux) 패키징: `psycopg[binary]` wheel, Python 버전. 콜드 스타트 시 DB 연결.
- Discord: 봇 권한(특히 Read Message History), 메시지 embed 표시 모양, 실제 429/5xx 동작, `nonce` 동작, 빈 목록 반환 조건, 제목 이스케이프 표시.

## 9. 운영 활성화 차단 조건 (이 항목이 해결되기 전에는 Scheduler를 켜지 않는다)

| # | 조건 | 상태 |
|---|---|---|
| 1 | **SQL 번호**: DB 담당자와 협의해 **048로 확정**했다 (`origin/refactor/157·159`의 042~047과 충돌 없음. 머지 직전에 최신 develop에서 048이 다른 파일에 쓰이지 않았는지 한 번 더 확인) | 확정 (머지 전 재확인) |
| 2 | **`posts.created_at` 시간대 확인 (M2)**: 컬럼이 `timestamp without time zone DEFAULT CURRENT_TIMESTAMP`라서 값은 입력 세션의 시간대 기준이다. 이 기능은 컷오버를 **UTC**로 비교한다. 운영 DB(읽기 전용 쿼리)에서 확인: `SHOW timezone;`, `SELECT datname, setconfig FROM pg_db_role_setting s LEFT JOIN pg_database d ON d.oid = s.setdatabase;`, 백엔드 DB 역할의 `rolconfig`(`SELECT rolname, rolconfig FROM pg_roles WHERE rolname = '<백엔드 역할>'`). 그리고 검증 환경에서 글을 하나 쓴 직후 `SELECT created_at, now() AT TIME ZONE 'UTC' FROM posts ORDER BY post_id DESC LIMIT 1;`로 같은 값인지 확인한다. KST이면 컷오버 계산을 맞춰야 한다 (그대로 켜면 컷오버 전 최대 9시간 분량 글이 공유된다. `test_kst_naive_posts_would_be_misjudged_by_utc_cutover`가 이 영향을 재현한다) | 미확인 |
| 3 | **삭제된 글의 뒤늦은 공유 (M5)**: Worker가 DB에 접근하지 않는 구조에서는 전송 직전 삭제 여부를 확인할 수 없다. 선점 후 삭제된 글은 작업에 들어 있는 제목으로 게시될 수 있다 (노출 창: 선점 ~ Worker 전송, 보통 1~2분, 최대 `job_ttl_minutes`=10분). 이번 Issue에서는 **구현하지 않았다** (정책 결정 필요: 전송 직전 DB 확인용 왕복 큐 추가, 또는 게시 후 삭제 반영 = Discord 메시지 삭제 기능 필요) | 미해결, 위험 수용 여부 결정 필요 |
| 4 | **Worker 예약 동시성 1 / 배치 크기 1** (위 4절) | 배포 시 필수 |
| 5 | **기존 18:00 공지 중단 후 활성화** (위 6절) | 배포 시 필수 |
| 6 | 알림: `UNKNOWN`, `FAILED_NO_AUTO_RETRY`, `CLAIMED_BY_LEGACY_NOTICE`, DLQ 메시지가 0이 아니면 사람이 확인 | 배포 시 필수 |

### 같은 날짜 묶음 실패 후 이월 정책 (M3)
20시 묶음이 큐 적재 전에 실패해 PENDING이 되고 이후 복구로 FAILED가 되어도, **같은 KST 날짜에는 두 번째 묶음을 만들지 않는다** (`batch_date UNIQUE`가 날짜당 1건을 보장). 그 글들은 **다음 날 20시 묶음**에서 오래된 순으로 우선 발송된다.
결과: 복구는 되지만 최대 약 24시간 늦어진다. 같은 날 재발송이 필요하면 운영자가 수동으로 처리해야 한다 (이번 Issue 범위에서는 하지 않음).
미전송이 증명되지 않은 `UNKNOWN` 배치의 글은 증명되거나 사람이 풀 때까지 다음 날 묶음에도 들어가지 않는다 (중복 방지 우선).
