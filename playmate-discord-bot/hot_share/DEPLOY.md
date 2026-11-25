# HOT 게시글 Discord 자동 공유: 배포·운영 문서 (초안)

> Issue #184: [기존 EC2 Runner](../../infra/discord-db-runner/DEPLOY.md)가 기존 서비스를 호출할 수 있다.
> EC2 방식에서는 아래 DB Lambda/Scheduler 리소스를 추가하지 않는다. baseline은 계속 수동 절차다.

Issue #165. **AWS 리소스는 하나도 만들지 않았고, 운영 배포는 이 Issue 범위가 아니다.** AWS 동작 설명은 #163 `career_share/DEPLOY.md`와
같은 "문서 기준"이며 실제 AWS에서 확인하지 않았다. **`052_hot_discord_share.sql`은 잠정 번호다. DB 담당자가 확정하기 전에는 적용하지 않는다.**
PR #174 now uses `068_remove_compat_views.sql` to avoid the migration number collision. The HOT migration number remains provisional; both migrations require deployment review.
선행 마이그레이션: `030_board_access_scope.sql`(boards.scope_type 등), `045_post_reactions.sql`(LIKE 집계). 둘 다 develop에 있다.

## 1. 구성

```
EventBridge Scheduler(5분, rate(5 minutes)) ─▶ HOT DB Lambda {"action":"hot_relay"}   (VPC 안, PostgreSQL)
                                                     │ baseline 완료 확인 → HOT 후보 조회·선점 → 메시지 생성
                                                     ▼
                                           [HOT 발송 SQS 표준 큐] ─▶ DLQ
                                                     ▼
                         HOT Worker Lambda (VPC 밖, DB 없음, 채널 = 🔥│핫플레이메이트) ─▶ Discord REST API
                                                     ▼
                                           [HOT 결과 SQS 표준 큐] ─▶ DLQ
                                                     ▼
                                       HOT DB Lambda (SQS 이벤트 소스, 결과 기록)
```

| Lambda | 핸들러 | 트리거 |
|---|---|---|
| HOT DB Lambda | `hot_share.db_lambda.handler` | Scheduler(5분) + HOT 결과 큐 + 수동(`hot_baseline`, `hot_summary`) |
| HOT Worker Lambda | `hot_share.worker_lambda.handler` | HOT 발송 큐 |

### 왜 #163의 큐·Worker 함수를 같이 쓰지 않는가 (코드는 재사용, 리소스는 분리)

- #163 Worker는 **자기 환경변수의 채널 하나**로만 보내고, 중복 방지 마커도 그 채널에서만 찾는다. HOT은 다른 채널이므로 같은 함수를 쓰려면
  작업마다 채널을 고르도록 #163 Worker를 바꿔야 한다. 그러면 #163의 실행 결과가 달라질 수 있어 하지 않았다.
- Worker는 예약 동시성 1이 필수다. 큐를 공유하면 HOT 처리량이 취업 공유 지연을 일으킨다.
- 대신 **코드는 그대로 재사용한다**: `CareerShareWorker`, `handle_records`, `CareerShareService`의 발행·복구·결과 반영 흐름,
  `contract`/`state`/`queues`/`messages`, `discord_rest.DiscordRestClient`. HOT 전용 코드는 HOT SQL, baseline, 메시지 본문, 설정뿐이다.
- 잘못된 큐 연결 방지 (Worker 단에서 막는다, 테스트로 확인):
  - 각 Worker는 자기 작업 단위만 처리한다: 취업 Worker `CareerShareWorker.UNIT_PREFIXES = ("post-", "digest-")`, HOT Worker `("hot-",)`
    (+ `kind=HOT` 확인). 계약(`contract`)은 두 기능의 단위를 모두 허용하므로 이 검사가 실제 방어선이다.
  - 검사는 Discord 조회·전송보다 먼저 실행되고 `ContractError`를 낸다. `handle_records`가 실패로 보고하므로 재전달돼도 매번 거부되어
    DLQ로 간다 (결과 메시지를 만들지 않으므로 DB 상태도 바뀌지 않는다). 발송 작업과 확인(verify) 작업 모두 해당한다.
  - 결과가 다른 DB Lambda로 가도 반영되지 않는다: 취업 DB Lambda는 `hot-` 결과를, HOT DB Lambda는 `post-`/`digest-` 결과를 `ignored`로 끝낸다.
  - 큐를 뒤바꿔 연결하면 해당 작업은 게시되지 않고 DLQ에 쌓이며, HOT 행은 PENDING → (만료) UNKNOWN으로 남는다. DLQ 경보로 발견해 설정을 고친다.
  - 보조 검사: HOT 설정은 발송 큐가 `CAREER_SHARE_SEND_QUEUE_URL`과 같으면 시작하지 않는다 (같은 함수 환경에 둘 다 있을 때만 비교 가능).
- **남은 운영 위험 (코드로 막지 못함)**: Worker는 작업이 아니라 **자기 환경변수의 채널**로 보낸다. HOT Worker의 `HOT_SHARE_CHANNEL_ID`에
  다른 채널(예: 취업 소식) ID를 넣으면 HOT 글이 그 채널에 게시된다. 반대도 같다. 배포 시 두 Worker의 채널 ID를 교차 확인한다.

## 2. HOT 판정 (웹 기준과 동일)

`hot_share/policy.py` 상단 주석이 기준이다. 웹 `board_repository.list_featured_posts(kind="hot")`의 조건을 그대로 옮겼다.
웹의 `LIMIT 100`은 표시 개수라 후보 조회에 쓰지 않는다(105개 HOT 글이 모두 후보가 되는 것을 테스트로 확인).

### 7일 경계와 시간대 (운영 전 필수 확인)

`post_reactions.created_at`은 시간대 없는 `TIMESTAMP`이고 기본값 `CURRENT_TIMESTAMP`는 **쓰는 세션의 TimeZone**으로 저장된다. 웹 HOT SQL은
`created_at >= CURRENT_TIMESTAMP - 7일`로 비교하는데, 이때 naive 값도 **웹 세션의 TimeZone**으로 해석된다. backend(`app/core/db_connect.py`)는
TimeZone을 지정하지 않으므로 **서버·계정 기본값**을 쓴다. Lambda 연결은 `TimeZone=Asia/Seoul`이라, 웹 SQL을 그대로 쓰면 9시간 어긋난다(테스트로 재현).
그래서 HOT SQL은 기준 시각을 `HOT_SHARE_DB_TIMEZONE`의 naive 값으로 바꿔 비교한다.

운영 확인 절차 (공용 DB 담당자가 실행):
1. backend가 쓰는 DB 계정으로 접속해 `SHOW TimeZone;` 실행 (계정별 `ALTER ROLE ... SET timezone`이 있을 수 있으므로 반드시 그 계정으로)
2. 그 값을 `HOT_SHARE_DB_TIMEZONE`에 넣는다 (예: `UTC`). 일광절약 시간이 있는 시간대는 설정 단계에서 거부한다
3. backend 배포 환경이 바뀌어 TimeZone이 달라지면 이 값도 바꿔야 한다 (안 바꾸면 웹 HOT과 결과가 달라진다)

## 3. 공유 범위

`scope_type = 'LEGACY' AND course_code IS NULL AND cohort IS NULL`(+ institution/program/cohort_id IS NULL) 이고 `공지사항`이 아닌 게시판만.
SQL 조건과 `policy.is_shareable_board`로 이중 확인한다. 웹과 다른 점: 웹은 LEGACY 과정·기수 게시판도 모든 회원에게 읽기를 허용하지만 Discord는 제외한다.
NULL scope_type은 웹도 거부한다(컬럼은 NOT NULL DEFAULT 'LEGACY'). 게시판 설정이 바뀌면 다음 선점부터 바로 반영된다.
**회원이 만든 일반 게시판(LEGACY, 과정 없음)은 공유 대상이다.** 특정 게시판을 빼야 하면 정책 결정 후 허용 목록 방식으로 바꾼다.

메시지에는 제목·원문 링크·마커만 들어간다. 작성자, 익명 여부, 본문, 좋아요 수는 넣지 않는다. 멘션은 무력화한다.

## 4. 환경변수

HOT DB Lambda: `DB_*`(#163과 같음), `HOT_SHARE_SEND_QUEUE_URL`(필수), `PLAYMATE_WEB_BASE_URL`(비었거나 localhost면 아무것도 선점하지 않음),
`HOT_SHARE_DB_TIMEZONE`(필수, 2절), 선택: `HOT_SHARE_RELAY_LIMIT`(10) `_MAX_ATTEMPTS`(3) `_RETRY_BASE_MINUTES`(5) `_JOB_TTL_MINUTES`(3)
`_CLAIM_STALE_MINUTES`(15) `_VERIFY_INTERVAL_MINUTES`(10) `_VERIFY_SETTLE_MINUTES`(30) `_ABSENT_REQUIRED`(2) `_MAX_VERIFIES`(6).

HOT Worker Lambda: `DISCORD_BOT_TOKEN`(시크릿), `HOT_SHARE_CHANNEL_ID`(기존 `🔥│핫플레이메이트`, Gateway Bot의 `PLAYMATE_HOT_CHANNEL_ID`와 같은 값),
`HOT_SHARE_RESULT_QUEUE_URL`.

AWS 설정 요구사항(VPC 엔드포인트, 예약 동시성 1·배치 크기 1·ReportBatchItemFailures, 가시성 타임아웃, DLQ, IAM 분리, Discord 권한
`View Channel`/`Send Messages`/`Read Message History`/`Embed Links`)은 #163 `career_share/DEPLOY.md` 4절과 같다. 패키징에 `hot_share/`를 추가한다.
DB 계정 추가 권한은 `052` 하단 주석 참고 (SELECT boards, post_reactions, recruits / SELECT·INSERT·UPDATE HOT 테이블 2개).

## 5. 활성화 순서

1. `052` 적용 (번호 확정 후, DB 담당자)
2. 2절 TimeZone 확인 → 환경변수 설정
3. HOT DB Lambda에 `{"action":"hot_baseline"}` **1회** 수동 실행 → `baseline_rows`와 `baseline_completed_at` 확인
   - 지금 HOT인 글 전부(공개 범위와 무관)를 `BASELINE`으로 기록하고 완료 표시를 남긴다. 두 번째 실행은 아무것도 바꾸지 않는다
4. HOT Worker 이벤트 소스 활성화 → Scheduler(5분) 활성화
5. `{"action":"hot_summary"}`로 상태 확인

baseline 전에 Scheduler가 켜져도 relay는 `{"skipped":"baseline_required"}`로 끝나며 아무것도 선점하지 않는다.

## 6. 중복 방지·복구 (요약)

- **게시글당 1회**: `hot_discord_shares.post_id` PK. 행이 생기면(BASELINE/PENDING/SENT/UNKNOWN/SKIPPED) 다시 신규로 선점하지 않는다 → 재진입 재공유 없음.
  자동 재선점은 재시도 가능한 `FAILED`뿐이며, 그때도 **HOT·공개 게시판·미삭제·게시 상태**를 같은 SQL로 다시 확인한다.
- **Scheduler 중복/동시 실행**: baseline과 relay가 같은 `pg_advisory_xact_lock`을 잡는다 + PK 충돌. 동시 relay 4개, baseline 2개+relay 4개 동시 실행을 테스트했다.
- **baseline 도중 HOT 진입**: baseline 문장의 스냅샷 이후 HOT이 된 글은 BASELINE이 아니며, baseline 커밋 뒤 relay가 1번만 선점한다(테스트로 재현).
- **SQS 중복 전달, Discord 5xx/타임아웃(UNKNOWN), 정착 대기, 마커 기반 미전송 증명(서로 다른 확인 2회)**: #163과 같은 규칙·코드.
  UNKNOWN은 자동 재발송하지 않는다.

## 7. 삭제·비공개 전환: 대응 범위와 남은 위험

| 시점 | 대응 | 상태 |
|---|---|---|
| 최초 후보 조회·선점 | 같은 트랜잭션의 SQL이 삭제·HIDDEN·미게시·모임 글·비공개 게시판을 제외 | 구현·테스트 |
| FAILED 재선점(미전송 증명 후 포함) | 같은 SQL로 최신 상태 재확인. 삭제·HIDDEN·게시판 범위 변경 글은 FAILED로 남는다 | 구현·테스트 |
| 선점 → Worker 전송 사이 | **막지 못한다.** Worker는 DB에 접근하지 않는다. 작업 TTL 3분(#163은 10분)으로 노출 창만 줄였다 | **남은 위험** |
| 전송 결과 반영 시 | 글 상태를 다시 보고, 공유하면 안 되는 글이면 ERROR 로그 + `applied_post_not_shareable` 반환 | 감지 구현·테스트 |
| 게시 후 (사용자 삭제·관리자 숨김·게시판 범위 변경) | **5분 relay마다** `SENT`인데 지금은 공유 불가인 글을 찾아 ERROR 로그(`Discord 메시지 삭제 필요`, post_id·message_id)와 relay 응답 `sent_not_shareable` 건수로 알린다. `hot_summary`의 `SENT_POST_NOT_SHAREABLE`에도 표시. **Discord 메시지는 자동으로 지우지 않는다** | 감지·반복 알림 구현·테스트 (PR #170 리뷰 ①) |

**경보는 아직 없다.** 코드가 만드는 것은 CloudWatch Logs에 남는 ERROR 로그뿐이다. 로그만으로는 아무도 알림을 받지 않는다.
배포 시 CloudWatch Logs 지표 필터(`"Discord 메시지 삭제 필요"`, 그리고 조회 실패용 `"HOT 게시 후 상태 확인 실패"`) + 경보 + 알림 대상(SNS 등)을
**별도로 만들어야** 이 대응이 동작한다 (이 PR은 AWS 리소스를 만들지 않았다. 8절 미검증 목록).

경보가 오면 운영자가 Discord에서 해당 메시지를 지우고, **실제로 사라졌는지 확인한 뒤에만** `052` 하단 주석의 SQL(post_id·message_id 일치)로
`RETRACTED`를 기록한다. 삭제에 실패했거나 확인하지 못했으면 기록하지 않는다 (기록하면 경보가 멈춘다). 기록 전까지는 매 주기 다시 알린다.
`RETRACTED` 글은 복구·재HOT이 돼도 다시 공유하지 않으며, 늦게 도착한 예전 결과(SENT 등)도 상태를 바꾸지 않는다.
알림 조회가 실패해도 그 주기의 선점·발행 결과는 그대로이며 relay 응답 `sent_not_shareable: null`과 ERROR 로그(예외 종류만)가 남는다.
경보 건수는 전체 건수이고, 로그·`hot_summary` 목록은 50건까지만 보여 준다.

**구조적 한계 (전송 직전 재검증 불가)**: HOT Worker는 VPC 밖에서 DB 접근 없이 Discord로 보낸다(DB 자격 증명을 인터넷에 노출된 함수에 두지 않는 #163 설계).
그래서 Worker가 보내기 직전에 글 상태를 확인할 방법이 없다. DB 조회는 선점 시점과 결과 반영 시점·이후 relay에서만 할 수 있다.

**남은 위험 (해결된 것이 아님)**: 선점→전송 사이(최대 작업 TTL 3분)와 게시 이후 상태 변경 모두, 메시지가 Discord에 실제로 보이는 시간은
"다음 relay(최대 5분) + 운영자가 경보를 보고 지우는 시간"이다. 자동 철회(아래 후속 Issue)를 구현하기 전까지 사람의 대응에 의존한다.

### 후속 Issue 제안: 게시 후 삭제 동기화

- #161 `DiscordRestClient`에 `delete_message(channel_id, message_id)` 추가 (404는 이미 삭제됨으로 성공 처리)
- HOT DB Lambda가 `SENT`이면서 지금은 공유 불가인 행(`_STILL_SHAREABLE_SQL` 반대 조건)을 골라 `type: "delete"` 작업 발행
  (계약에 새 작업 종류, 결과 `DELETED` 추가. 상태 `RETRACTED`는 수동 정리용으로 052에 이미 있으므로 자동 철회도 같은 상태를 쓴다)
- Worker는 작업의 message_id가 자기 채널 메시지이고 footer 마커가 `ref:hot-<id>`와 일치할 때만 삭제 (다른 메시지 삭제 방지)
- 선점→전송 사이 창을 없애려면 Worker가 전송 직전 DB Lambda에 확인을 요청하는 왕복 큐가 필요하다 (지연·복잡도 증가, 정책 결정 필요)

## 8. 실제 환경에서 확인해야 할 것 (미검증)

- 운영 DB backend 계정의 TimeZone (2절)
- 운영 `boards` 데이터: 공유 대상이 될 LEGACY·과정 없음 게시판 목록을 사람이 검토 (`SELECT board_id, board_name FROM boards WHERE scope_type='LEGACY' AND course_code IS NULL AND cohort IS NULL`)
- 5분 주기 HOT 집계 쿼리 비용: `post_reactions` LIKE 전체 중 최근 7일 범위를 매번 집계한다(웹과 같은 방식). 데이터가 많아지면 실행 계획 확인
- AWS: Scheduler 입력, VPC 엔드포인트, 이벤트 소스 매핑, 예약 동시성, DLQ 동작 (모두 문서 기준, 미확인)
- AWS: 7절의 CloudWatch 지표 필터·경보·알림 대상 (만들지 않음. 만들기 전에는 게시 후 삭제 알림이 아무에게도 가지 않는다)
- Discord: 실제 채널 권한과 마커 조회 (가짜 서버로만 확인)
