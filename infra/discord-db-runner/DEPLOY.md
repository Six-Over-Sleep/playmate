# EC2 Discord DB Runner (#184)

기존 EC2의 독립 Python 프로세스 두 개다. 신규 AWS 리소스, DB migration, Discord 발송 구현을 추가하지 않는다.
기존 DB Lambda builder/Service/Repository를 재사용한다. DB Lambda를 배포할 필요는 없다.

## 설치와 사전 검증

운영 활성화 전에 별도 코드 리뷰와 테스트 환경 검증이 필요하다. 이 문서의 명령은 배포 절차 예시이며 자동 실행되지 않는다.

1. 기존 EC2에 전용 `playmate` 계정, `/opt/playmate` 코드·venv를 준비한다. Python 3.13 권장.
2. `playmate-discord-bot/requirements-runner.txt`를 설치한다. boto3는 EC2 기본 제공이 아니다. 배포 환경에서 의존성을 고정하고 검사한다.
3. `runner.env.example`을 저장소 밖 `/etc/playmate/discord-db-runner.env`에 복사해 채운다. 소유 root, 권한 0600 권장
   (systemd가 읽어 실행 계정에 전달). `.env` 자동 로드는 하지 않는다. shell source와 systemd EnvironmentFile 문법은 다르다.
4. 같은 환경을 주입한 상태에서 봇 디렉터리에서 `python -m db_runner scheduler --check`, `python -m db_runner results --check`를 실행한다.
   이 검증은 환경 형식만 검사하며 AWS·DB 접속·권한·스키마 존재를 검증하지 않는다.
5. 두 service 예시의 사용자·코드·venv·환경 파일 경로를 실제 EC2에 맞춘다. 설치 후 `systemd-analyze verify`로 검증한다.
   이 저장소의 로컬 구현 테스트는 systemd 설치/시작을 수행하지 않는다.

모든 기능 기본값은 false다. 아무 기능도 opt-in하지 않으면 연결 없이 정상 종료한다. systemd도 반복 재시작하지 않는다.
각 `DB_RUNNER_{CAREER,HOT,DM}_ENABLED=true`는 선택한 CLI 모드에서 그 기능만 활성화한다.
DM 활성화에는 `DB_RUNNER_DM_MODE=relay` 또는 `recover`도 명시해야 한다. 오타는 종료 코드 78로 차단한다.
설정 오류(78)는 자동 재시작하지 않으며, 수정 후 운영자가 재시작한다. 다른 비정상 종료는 10초 뒤 재시작하며
5분에 5회 제한에 걸리면 조사 후 다시 시작한다. 서비스가 active인지와 queue age를 함께 감시한다.

큐 URL은 `https://sqs.<region>.amazonaws.com/<12자리 account>/playmate-<test|prod>-<feature>-share-<send|result>`를 검증한다.
중국 리전은 amazonaws.com.cn, DM send만 `.fifo`다. 다른 명명 규칙·커스텀 endpoint는 지원하지 않는다.
활성 큐는 모두 같은 account, 명시한 region/environment여야 한다. send/result 중복은 거부한다.

## DB·IAM·네트워크

DB_HOST/PORT/USER/PASSWORD/NAME/SSLMODE로 Aiven 또는 EC2 PostgreSQL을 지정한다. 연결 함수는 기존
`career_share.repository.connect_for_lambda`다: connect_timeout 10초, statement_timeout 15초, 세션 Asia/Seoul.
TLS CA가 필요하면 libpq의 `PGSSLROOTCERT`와 `DB_SSLMODE=verify-full` 등을 환경에서 지정한다.
`require`는 인증서 hostname 검증을 제공하지 않는다. disable/allow/prefer는 명시적으로 선택할 때만 사용하며
운영 외부 DB는 검증 가능한 TLS를 권장한다. PostgreSQL IAM DB 인증을 새로 구현하지 않는다.

기존 EC2 instance profile만 SDK credential provider로 사용한다. 환경 access key·공유 profile·credential_process를
사용하지 않는다. EC2 metadata/role 접근이 불가능하면 SQS 호출은 실패한다. Discord token은 Runner에 필요 없다.
운영 전 별도로 role·IMDSv2·DB 연결 한도·DNS·TLS·외부 SQS HTTPS 경로를 확인한다. 새 NAT/endpoint를 만들지 않는다.

최소 IAM (활성 기능의 정확한 큐 ARN에만 부여):

- 발송 큐: sqs:SendMessage (scheduler)
- 결과 큐: sqs:ReceiveMessage, sqs:DeleteMessage, sqs:GetQueueAttributes, sqs:ChangeMessageVisibility
- 기존 SSE-SQS 큐는 별도 KMS 권한 불필요. 이 Runner가 비밀 관리 API를 조회하지 않으므로 Secrets Manager 권한 불필요.

기존 SQL 048/052/053과 선행 스키마 적용, Career posts.created_at의 UTC naive 전제,
HOT_SHARE_DB_TIMEZONE과 웹 DB 시간대 일치, DM notifications 세션 시간대 의미를 별도 확인한다.
Runner는 migration이나 baseline을 실행하지 않는다. 스키마 불일치는 반복 오류가 되므로 활성화 전에 확인한다.
프로세스당 기능별 연결이 생겨 두 프로세스에서 최대 6개 DB 연결을 사용할 수 있다.

## 스케줄과 전환

| 작업 | 간격 |
|---|---|
| Career relay | 60초 |
| HOT relay | 300초 |
| DM relay | 60초 |
| DM recover | 롤백 모드에서만 600초 |
| Career digest | KST 20:00, 당일 grace 창 안에서 한 번 |

interval 작업은 시작 시 1회 실행하고 이후 monotonic clock의 간격 슬롯으로 실행한다. 느린 작업으로 지연될 수 있지만
순차 실행으로 중첩되지 않는다. 작업 실패도 다음 간격까지 기다리며 다른 작업을 막지 않는다.
실행 중 지난 슬롯은 건너뛰고 다음 미래 슬롯으로 이동하며 밀린 interval 전체를 재생하지 않는다.
HOT baseline은 사전에 수동으로 기존 절차에 따라 실행한다.

digest는 `20:00 <= 현재 KST <= 20:00 + DB_RUNNER_DIGEST_GRACE_MINUTES`에서 프로세스당 날짜별 1회 시도한다.
기본 30분, 설정 범위 1~180분(정수). 과거 날짜 재생 없음. 원래 20시를 scheduled_at으로, 실제 시각을 now로 전달한다.
실패 또는 후보 0건이어도 같은 프로세스에서는 당일 다시 시도하지 않는다. 재시작 시 창 안에서는 다시 시도할 수 있으나
기존 DB 날짜별 batch 선점이 중복 배치를 차단한다. 후보 0건이면 기존 DB가 batch를 만들지 않으므로 재시작 시
후속 후보가 포함될 수 있다. 실패 시 무제한 자동 재시도 대신 경보와 조사 후 grace 안의 재시작을 사용한다.

Career: 기존 Gateway `PLAYMATE_CAREER_NOTICE_ENABLED=false`와 재시작을 먼저 확인한다. 기존 18시 공지와 공동 선점은 안전하지 않다.
HOT: 기존 수동 추천과 자동 HOT의 중복은 별도 정책이며 이 Runner가 막지 않는다.
DM: 053·공동 선점 버전 Gateway를 확인하고 전환한다. sender는 EC2에서도 LAMBDA다. FIFO wrapper, 401 차단기,
16분 Gateway 인수 제한은 변경하지 않는다. 정상 모드는 relay가 recover를 포함한다.

롤백은 기존 `playmate-discord-bot/dm_share/DEPLOY.md` 5절 순서:
공동 선점 Gateway 폴링 복구 → scheduler DM_MODE=recover로 재시작 → Worker와 결과 소비 유지 →
LAMBDA PENDING/UNKNOWN의 복구·마감 확인 → 필요한 경우 Worker/DM 소비 중단. 구버전 Gateway 복귀 금지.
recover 모드는 신규 send 선점 없이 verify를 발행할 수 있으므로 Worker가 계속 필요하다.

## 수신·장애·DLQ

큐별 thread가 20초 Long Polling, 최대 1건씩 처리한다. ReadTimeout 기본 30초, connect 5초,
SDK 최대 시도 2회다. 기존 계약 + 큐별 kind/unit 검증 뒤 기존 apply_result가 정상 반환해야 삭제한다.
duplicate/ignored, HOT applied_post_not_shareable, DM auth_*와 missing_notification도 정상 반환이다.
본문·ReceiptHandle·token·비밀번호·수신자 정보는 Runner 로그에 출력하지 않는다. 예외 문자열 대신 유형만 남긴다.
라이브러리 DEBUG 로그를 운영에서 활성화하지 않는다.

visibility는 기본 360초로 수신 시 지정한다. 처리 직전 lease를 연장하고 60초마다 heartbeat한다.
연장은 최초 ReceiveMessage 호출 직전부터 잰 경과 시간과 1초 여유를 SQS 최대 43,200초에서 빼서 제한한다.
DB 반영 중 heartbeat는 SIGTERM 후에도 유지한다. DB 반영이 끝나면 heartbeat에 종료를 요청하고 최대 10초 동안 join한다.
종료를 확인한 뒤에만 삭제하며, join 시간 초과·연장 실패·visibility 여유 부족이면 메시지를 보존한다.
갱신이 계속 진행 중이면 해당 큐의 신규 수신을 보류하고 다른 큐는 계속 처리한다.
삭제 실패는 재전달 후 기존 멱등 처리로 복구한다. commit 응답 유실도 삭제하지 않는다.
DB/poll/delete/lease 오류는 큐별 지수 backoff+jitter(최대 약 301초). 다른 큐 thread는 계속 동작한다.

Poison Message는 삭제하거나 직접 DLQ로 보내지 않는다. 기존 maxReceiveCount=5 redrive에 맡긴다.
장기 DB 장애의 정상 메시지도 DLQ로 갈 수 있다. maxReceiveCount와 14일 보존은 무한 재시도 보장이 아니다.

운영자는 기존 result queue age/각 result DLQ 경보를 감시하고 다음 절차로 수동 복구한다:

1. 발송·결과 큐의 환경/기능을 확인하고, 본문은 제한된 접근 환경에서만 조사한다. 로그·티켓에 원문을 복사하지 않는다.
2. DB·설정·권한 또는 poison schema 원인을 고친다. Worker 결과와 현재 claim 소유권을 확인한다.
3. 기존 결과를 수정하지 않고 해당 원본 결과 큐로 제한된 건수 redrive한다. 오래된 token은 기존 저장소가 무시할 수 있다.
4. queue age·DLQ·DB 상태를 확인하며 확대한다. 반복 실패 메시지는 원인 규명 전 재순환하지 않는다.
5. 발송 DLQ를 결과 DLQ처럼 재발송하지 않는다. TTL·UNKNOWN 복구와 각 기능 DEPLOY.md의 절차를 따른다.

DLQ 자동 redrive, purge, token 교체, 강제 재발송은 구현하지 않았다. 로컬 fake DLQ 테스트는 AWS redrive 동작 증명이 아니다.

## 로컬 테스트와 PostgreSQL 18 검증

`playmate-discord-bot`에서 `python -B tests/run_db_runner_offline.py`를 실행한다. 이 실행기는 테스트 DSN을 비우고,
실제 DB connect와 boto3 client 생성, loopback 외 네트워크를 차단한다. 기존 가짜 Discord HTTP 서버만 loopback으로 허용한다.
Runner 설정/clock/commit/재전달/종료/visibility 테스트와 Career/HOT/DM/FIFO/패키징 회귀를 실행한다.

PostgreSQL 통합 테스트는 위 오프라인 실행에서 의도적으로 SKIP한다. 별도 CI에서 PostgreSQL 18의 폐기 가능한
로컬 테스트 DB를 준비한 뒤 DB 버전과 전용 DB임을 확인하고 `PLAYMATE_TEST_PG_DSN`을 명시하여 기존
test_career_share/test_hot_share/test_dm_share/test_db_integration을 실행한다. 이 테스트들은 public 스키마를
재생성하므로 운영/공유 DB를 절대 지정하지 않는다. 기존 안내의 postgres:16 대신 18로 검증해야 한다.
환경이 없으면 SKIP를 유지하며 현재 Docker 컨테이너·볼륨을 재사용/변경하지 않는다.

## 종료·복구·관측 한계

SIGTERM/SIGINT는 신규 작업/수신을 멈춘다. polling 직후 종료 요청이 있으면 받은 메시지를 처리·삭제하지 않는다.
진행 중 DB 반영과 삭제는 완료까지 기다린다. 연결은 소유 thread가 닫는다. systemd TimeoutStopSec=180을 넘기면
강제 종료될 수 있으며 미삭제 결과는 visibility 만료 후 다시 전달된다. heartbeat join은 최대 10초이고
타임아웃된 I/O는 daemon thread에 남는다. SDK connect 5초와 read 기본 30초는 요청 단계별 제한이다.
SDK 재시도, 자격증명 갱신, 진행 중인 DB 처리를 합한 종료 시간은 이 값들로 보장되지 않으며 systemd가 최종 상한을 적용한다.
scheduler 발행 중 종료도 기존 PENDING/UNKNOWN
복구에 맡긴다. DB statement timeout은 전체 배치/commit 시간 상한이 아니다. 스택·네트워크가 멈추면 강제 종료가 최종 상한이다.

서비스별 OS 파일 잠금은 같은 EC2의 중복 수동 실행도 막는다. StateDirectory의 lock 파일은 삭제하지 않는다.
별도 EC2 전체를 잠그는 분산 singleton은 아니다. SIGKILL/재부팅 시 OS 잠금은 해제된다.
서비스 부팅은 multi-user.target에 enable했을 때만 자동이다. 두 서비스는 서로 독립적으로 재시작한다.

실제 AWS FIFO/visibility/redrive, IAM credential 갱신, EC2 재부팅/systemd 종료, 운영 DB 시간대와 성능,
Discord nonce/마커 동작은 로컬 테스트로 입증되지 않는다. 기존 verify 한도 소모·삭제 후 늦은 발송·exactly-once 한계도 유지된다.
