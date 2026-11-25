# Issue #188 모임 채널 전환

Gateway의 기본 동작을 유지한다. SAM 모임 리소스와 매핑은 기본 비활성이고 승인 경로는 기본 등록하지 않는다.
SAM에서 자동 GRANT는 비활성으로 고정한다. Lambda는 채널 삭제나 PostgreSQL 접속을 하지 않는다.

## 배포 전제와 설정

- 운영 기준은 2026-11-25 팀 공지의 Aiven PostgreSQL 18.7, defaultdb, public이다. 공지된
  물리 테이블 60개, View 4개, FK 90개와 job_insights·호환 View 12개 제거는
  개별 컬럼·제약·실행 권한의 확인을 대신하지 않는다.

- FastAPI 승인 라우터는 `POST /internal/discord-meeting/approve`를 직접 등록한다. `/api` prefix가
  없고 Worker도 이 정확한 URL 경로만 허용한다. 배포 workflow에서 nginx 상태 확인만 확인된다.
  운영 가상 호스트, 경로 매핑, 인증서, 네트워크 도달성은 별도로 확인한다. 정책 승인된 HTTPS 인입에만
  정확한 경로를 연결하고 일반 `/api` 공개 라우팅에 포함하지 않는다.
- 스테이징에서 Lambda의 DNS·인증서·HTTPS 접근, 진입 경로의 요청량·동시성·본문/읽기 제한,
  인증 실패·재전송 거부, 실패 시 SQS 동작을 확인한다. 512바이트 본문 상한은 앱에서 적용한다.
  HMAC은 메서드·경로·시각·본문에 바인딩되며 15초 허용 편차, DB 단일 승인, 5초 실행 기한을 사용한다.
  Worker 승인 호출의 3초 타임아웃과 프록시·백엔드 타임아웃을 함께 검증한다. 프록시와 앱 로그에서
  서명 헤더, 요청·응답 본문, 시크릿을 기록하지 않는다. 승인된 인입이 없으면 API와 Worker 매핑을 끈다.
- 백엔드 DISCORD_MEETING_APPROVAL_ENABLED와 DISCORD_MEETING_APPROVAL_SECRET은 인입 검증 후 설정한다.
  모임 Worker는 별도 Discord 토큰·승인 시크릿을 지정된 Secrets Manager ARN에서 읽는다.
  AWS 관리 키 사용을 전제로 한다. 전용 봇의 권한과 접근 가능한 guild·카테고리를 제한한다.
  시크릿 교체 전 신규 생성 승인을 중지하고 진행 중 요청을 정리한다. API와 Secret을 교체하고
  캐시된 Worker 실행 환경을 새 버전으로 교체한 뒤 서명·재전송 검증과 소량 시험을 거쳐 재개한다.
- SQL 069는 기존 모임 상태를 보존하고 outbox와 소유권·결과 heartbeat, 조회·인계 함수를 추가한다.
  실제 DB 역할의 필요한 열·테이블 권한을 나눠 검증한다. 소유권 변경은 운영자만 한다.
- 기존 EC2에 discord-db-meeting@results 와 discord-db-meeting@scheduler 를 설치한다.
  환경 파일에 DB_RUNNER_MEETING_ENABLED=true, 리전·환경, MEETING_WORK_QUEUE_URL,
  MEETING_RESULT_QUEUE_URL, 기존 DB 연결값을 지정한다. Scheduler 실행에는
  DB_RUNNER_MEETING_SCHEDULE=true와 DB_RUNNER_MEETING_CREATE,
  MEETING_GUILD_ID, MEETING_CATEGORY_ID, MEETING_VISIBILITY가 필요하다. 생성은
  시간대가 있는 MEETING_CUTOVER_AT 이후의 대상만 처리한다.
- 전용 IAM은 work SendMessage와 result Receive/Delete/ChangeMessageVisibility를 각 큐로 제한한다.
  보호 채널·사용자 ID는 MeetingProtectedIds, 보호 역할은 MeetingStaffRoleIds에 지정한다.
  Gateway가 사용하던 모임 카테고리와 사전 생성한 여유 카테고리를 검증해
  `MeetingCategoryId`와 `MeetingAdditionalCategoryIds`(우선순위순 CSV)에 등록한다.
  Lambda는 등록된 카테고리만 사용하고 자식 채널 50개 미만인 첫 카테고리를 선택한다.
  모두 포화되면 쓰기 승인 없이 MANUAL에 보류하고 기존 Worker 경보로 알린다.
  카테고리 생성·삭제는 운영자가 담당한다.
  비공개 신규 생성은 참여자 접근·Gateway 활동을 검증하기 전 Runner가 거부한다.

## 인계와 롤백

1. 기존 Gateway를 인계 락을 사용하는 버전으로 먼저 교체한다. PLAYMATE_GATEWAY_MEETING_ 접두어의
   CREATE, PERMISSIONS, AUDIT, CACHE, LIFECYCLE, ACTIVITY는 각각 기본 true다.
2. 결과 소비자를 먼저 올린다. 정상 빈 poll 또는 성공 ACK로 갱신된 90초 heartbeat가 없으면
   신규 승인을 거부한다. 4분 넘게 결과 미확정인 승인도 신규 승인을 막는다.
3. Gateway의 채널 생성만 멈추고 `create_owner`를 `paused`로 바꾼다. Gateway가 생성 session lock을 잡고
   있으면 전환을 거부한다. 구버전 Gateway나 연결 단절 뒤 남아 있는 외부 요청은 락으로 취소되지
   않으므로 이전 프로세스·진행 중 요청을 먼저 확인한다.
4. 검증된 API와 Worker 매핑을 켠 뒤 `create_owner`만 `lambda`로 설정한다.
   `permission_owner=gateway`와 Gateway 참여 동기화·기존 탈퇴 권한 감사 설정을 유지한다.
   DB는 `permission_owner=gateway`만 허용하고 Runner도 `DB_RUNNER_MEETING_PERMISSIONS` 또는
   `DB_RUNNER_MEETING_GRANT`의 활성화를 시작 단계에서 거부한다. 기존 Gateway overwrite의 안전한
   인계와 자동 GRANT 검증은 후속 범위다.
5. 채널 생성 롤백은 신규 발행 중지, `create_owner=paused`, 승인 차단, 진행 중 호출과 불명 결과 대조,
   결과 소비 유지, `create_owner=gateway` 복귀 순이다. MANUAL 생성 행을 초기화하거나 작업 DLQ를
   무조건 redrive하지 않는다. 활동 이벤트, 무활동 경고·예약·삭제, Slash Command, 공식 채널은 유지한다.
   생성이 paused인 동안에도 Scheduler를 복구 전용으로 남겨 이미 승인된 생성의 조회·결과 정리를 진행한다.

## 출시 차단 조건

- 미승인 generation은 생성 후 5분이 지나면 DB에서 만료하고 새 job ID로 재선점할 수 있다.
  이전 FIFO 메시지는 실행 기한 뒤 수신되면 조회·승인 요청 없이 완료한다. 같은 그룹에서 이미 처리 중인
  메시지는 큐 visibility(360초) 동안 뒤 메시지를 지연시킬 수 있다. FIFO 5분 dedup ID는 세대별로 다르다.
- 중복 또는 범위 밖 topic 마커, 보호·정책 충돌, 유효하지 않은 카테고리 또는 전체 포화는
  기존 Worker 경보와 MANUAL 사유로 기록한다. 운영자는 기존 채널을 대조하고 카테고리·용량·설정을
  해결한 다음 재처리를 판단한다.
- 생성 경쟁에서 Discord가 HTTP 400을 반환하면 상태와 숫자 오류 코드를 기록하고 MANUAL에 보류한다.
  서버 전체 채널 한도(`30013`)와 일반 잘못된 폼(`50035`)을 카테고리 자리가 찬 증거로 사용하지
  않는다. 카테고리별 용량 초과를 식별하는 정확한 응답 형식을 스테이징에서 검증하기 전까지
  400에 대한 자동 재시도를 열지 않는다. 새로 처리 가능한 작업은 기존 등록 순서대로 남은 용량을 확인한다.
- 승인 이력이 있고 POST 또는 결과가 불명확하면 마커 조회만 허용하고, 10분 후 MANUAL로 남긴다.
  늦은 결과가 동일 generation의 MANUAL 행에 대응하면 조건부로 연결한다. 다른 작업이나 채널 연결과
  충돌할 경우 채널 ID만 작업 이력에 보존한다. 운영자는 이력, topic, guild, type, 카테고리,
  모임의 최신 상태와 채널 소유권을 확인한 뒤 복구하며, 확인 전 새 채널을 생성하지 않는다.
  Discord 변경과 DB commit은 원자적이지 않다. 실제 topic·guild·type·category와 가시성을 확인한다.
  정책상 429·403 등으로 거절된 생성도 자동 재시도하지 않고 MANUAL로 보존한다.
- GRANT 코드는 있으나 SAM에서 꺼져 있다. 취소 커밋 후 과거 승인 거부, 늦은 GRANT의 자동 회수와
  관측 가능한 복구 지연, 탈퇴 추적, 429·5xx·타임아웃, 운영진·수동 권한 및 PUBLIC/PRIVATE 검증이
  필요하다. 이미 진행 중인 요청의 즉시 차단은 보장하지 않는다.
- 회수에는 과거 승인에 기록된 Discord 사용자 식별자를 사용한다. 보존·삭제 정책과 접근 권한을
  합의하기 전에는 운영 권한 쓰기를 시작하지 않는다. 기존 미추적·수동 overwrite는 감사 대상이다.
  비활성 권한 경로를 검증할 때는 참여·정책 변경을 다음 주기에 재평가한다. 같은 상태의 일시 실패는
  60초 후 재시도하고, 적용 완료는 24시간 뒤 drift를 점검한다. 최근 GRANT를 회수한 직후는
  늦게 적용된 권한을 찾기 위해 짧은 주기를 유지한다. Discord의 Unknown Member는 해당 FIFO 작업을
  완료하고 상태가 그대로일 때만 1시간 뒤 다시 조회한다.
  현행 Gateway의 일반 참여·취소 동기화는 기존 정책을 유지하며, 불일치한 멤버 overwrite를
  참여 또는 취소 목표 상태로 바꿀 수 있다. 운영진·수동 overwrite 보호 판정은 기존 탈퇴 권한
  감사의 dry-run/쓰기 정책에서 적용한다.
- 격리 PostgreSQL 18에서 합성 fixture와 069로 다중 연결의 선점·승인 유일성,
  인계·rollback·commit 이후 ACK를 확인한다. 과거 SQL은 fixture 작성 참고용이다.
  운영 DB나 기존 개발 DB·컨테이너 또는 운영 데이터 복제본은 사용하지 않는다.
- 069 회귀는 `test_meeting_share_pg18` 모듈로 실행한다. 백엔드와 Bot의 테스트 의존성이 모두 필요하다.
  전용 PostgreSQL 18.7의 loopback DSN(`PLAYMATE_TEST_PG_DSN`)과 별도로 확인한
  시스템 식별자(`ISSUE188_TEST_CLUSTER_ID`)를 지정한다. 테스트는 `playmate_issue188_test`의
  빈 `public`에 합성 테이블을 생성하고 지운다. SQS·Discord는 가짜 객체로 대체한다.
- 실제 AWS에서 FIFO, DLQ, IAM, TLS 경로, Lambda timeout과 비용을 검증한다.
  신규 비용은 SQS 요청, Lambda, 로그·경보, 시크릿 조회다. 신규 EC2·RDS·NAT는 없다.

## Aiven 스키마 확인과 전진 배포

기준 브랜치의 마지막 추적 SQL은 068이고 #188 변경에는 069가 포함된다. 번호는 승인·머지 직전에
최신 저장소와 배포 기록에서 다시 대조한다. 운영에서는 **022·048·052·053·068을 포함한 기존 SQL을
다시 실행하지 않는다.** 069는 기존 테이블이나 데이터를 수정하지 않고 새 객체만 만드는 전진 전용
마이그레이션이다. 새 제어 행의 두 소유권 기본값은 gateway다.

### 기존 구조와 신규 객체

- recruit_discord_channels를 모임당 채널 선점·확정, PENDING/SUCCESS/FAILED, MANUAL 사유,
  Gateway 활동·경고·예약·삭제의 권위 있는 저장소로 유지한다. 모임당 한 행으로는 여러 회원의
  재조정 작업, 단일 사용 승인, 결과 세대와 재전달을 표현할 수 없다.
- recruit_outbox는 event_key, recruit_id, kind, schedule_version, status, attempts, payload를
  사용한다. 저장소 SQL 012와 ORM의 FK 대상은 recruit_programs다. 기존 dispatcher의
  DISCORD_PREPARE는 프로그램 일정 버전과 전달 성공을 다룬다. 레거시 regular/short 전체를
  담거나 회원별 권한·실행 승인 유일성을 강제하기에는 계약이 다르다. 기존 이벤트는 유지하고
  #188 Scheduler·Worker에서는 읽거나 변경하지 않는다.
- discord_meeting_jobs 한 테이블에 생성·권한 작업과 승인 소비를 함께 둔다. job_id PK,
  approval_id UNIQUE, 활성 생성·권한의 부분 유일 인덱스가 중복 실행을 막는 DB 경계다.
  discord_meeting_control 단일 행은 Gateway/Lambda 소유권과 소비 heartbeat의 공유 기준이다.
  069는 이 두 테이블과 인덱스, 권한 스냅샷 함수, 인계 함수·트리거만 추가한다. 기존 FK 또는
  호환 View를 추가·복구하지 않는다.

### 코드와 운영 카탈로그 비교표

| public 객체 | 코드에서 요구하는 컬럼 | 저장소 근거 | Aiven 승인 전 확인 |
|---|---|---|---|
| recruits | recruit_id, post_id, recruit_mode, deadline_at, regular_start_date, meeting_start | 000 및 Recruit ORM | PK, posts 조인/FK, 모드 값, 날짜·timestamp 형식과 NULL, 마감 원본의 KST naive 전제 |
| recruit_members | recruit_id, member_id, status, joined_at, canceled_at, role(Gateway 감사) | 000 및 RecruitMember ORM | 복합 PK 또는 동등한 유일성, 두 FK, 상태·role 값과 NULL, 재참여·취소 경로가 세대 계산에 쓰는 시각을 갱신하는 방식 |
| recruit_discord_channels | recruit_id, discord_text_channel_id, discord_category_id, discord_voice_channel_id, sync_status, sync_error, synced_at, created_at, updated_at, last_activity_at, inactivity_warned_at, scheduled_delete_at, discord_deleted_at | 022 | recruit_id PK/FK, 채널 ID의 유일성과 문자열 길이, 상태 CHECK, 시간대·기본값 및 유형, 레거시 카테고리 행 제외 조건 |
| recruit_outbox | #188 직접 의존 없음. 기존 dispatcher는 event_key, recruit_id, kind, schedule_version, status, attempts, payload 사용 | 012 및 OutboxRecord ORM | 테이블·PK·FK 대상, JSON 타입, status와 kind, 활성 소비자. 이 확인을 위해 기존 작업을 수정하지 않는다 |
| members | member_id, discord_id, member_status, updated_at(Gateway 감사) | 000, 멤버 ORM·탈퇴 로직 | PK, Discord ID DB 타입·길이·유일성, 상태 값, 탈퇴 문자 표지와 updated_at 시간 의미 |
| posts | post_id, title, post_status | 000 및 Post ORM | PK, title 타입·NULL, DELETED 상태값, 결과 확정 쿼리에서 필요한 행 잠금 권한 |
| discord_meeting_jobs / discord_meeting_control | 069에 정의된 작업 ID·대상·fingerprint·시각·결과, 승인 ID·행 소유권·heartbeat | 신규 069 | 적용 전 객체명 충돌 없음. 적용 후 PK·부분 인덱스·CHECK·트리거·함수 정의 및 실행 역할 권한 일치 |

Gateway의 기존 쿼리 중 스키마를 생략한 참조는 실제 실행 역할의 search_path에서 public 객체로
해석되어야 한다. #188과 Career·HOT·DM 신규 경로는 삭제된 호환 View나 job_insights를 복원하지 않는다.
카탈로그에 표시되는 timestamp 형식이나 조회 세션의 TimeZone만으로 기존 데이터의 저장 의미를
판단하지 않는다. 모임 마감의 KST naive 처리, Career의 posts.created_at UTC naive 전제,
HOT의 웹 DB 시간대, DM의 Gateway·Runner 세션 의미는 백엔드 쓰기 설정과 합성 데이터로 따로 검증한다.

### 운영자가 승인 후 사용할 읽기 전용 메타데이터 SQL

아래 예시는 작성만 했다. 이번 작업에서 실행하지 않았다. 대상 테이블의 데이터,
사용자 값, 승인 이력 또는 자격증명은 조회하지 않는다. 정보 스키마는 역할 권한에 따라
일부 객체를 숨길 수 있으므로 DBA 확인 결과와 실제 실행 역할 확인을 구분한다.

```sql
BEGIN READ ONLY;

SELECT current_database(), current_setting('server_version'), current_setting('TimeZone'),
       current_setting('search_path');

SELECT c.relname, c.relkind
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname IN ('recruits', 'recruit_members', 'recruit_discord_channels', 'recruit_outbox',
                    'members', 'posts', 'discord_meeting_jobs', 'discord_meeting_control')
ORDER BY c.relname;

SELECT table_name, column_name, data_type, udt_name, is_nullable,
       column_default, character_maximum_length, datetime_precision
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('recruits', 'recruit_members', 'recruit_discord_channels', 'recruit_outbox',
                     'members', 'posts', 'discord_meeting_jobs', 'discord_meeting_control')
ORDER BY table_name, ordinal_position;

SELECT c.relname AS table_name, k.conname, k.contype, k.convalidated,
       pg_catalog.pg_get_constraintdef(k.oid) AS definition
FROM pg_catalog.pg_constraint k
JOIN pg_catalog.pg_class c ON c.oid = k.conrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname IN ('recruits', 'recruit_members', 'recruit_discord_channels', 'recruit_outbox',
                    'members', 'posts', 'discord_meeting_jobs', 'discord_meeting_control')
ORDER BY c.relname, k.conname;

SELECT col.table_name, col.column_name, e.enumsortorder, e.enumlabel
FROM information_schema.columns col
JOIN pg_catalog.pg_namespace n ON n.nspname = col.udt_schema
JOIN pg_catalog.pg_type t ON t.typnamespace = n.oid AND t.typname = col.udt_name
JOIN pg_catalog.pg_enum e ON e.enumtypid = t.oid
WHERE col.table_schema = 'public'
  AND (col.table_name, col.column_name) IN (('recruits', 'recruit_mode'),
      ('recruit_members', 'status'), ('recruit_members', 'role'), ('members', 'member_status'),
      ('posts', 'post_status'), ('recruit_discord_channels', 'sync_status'))
ORDER BY col.table_name, col.column_name, e.enumsortorder;

SELECT tablename, indexname, indexdef
FROM pg_catalog.pg_indexes
WHERE schemaname = 'public' AND tablename IN ('recruit_members', 'recruit_discord_channels',
      'recruit_outbox', 'discord_meeting_jobs', 'discord_meeting_control')
ORDER BY tablename, indexname;

SELECT to_regprocedure('public.discord_meeting_permission_snapshot(bigint,bigint)') AS snapshot,
       to_regprocedure('public.discord_meeting_guard_handoff()') AS handoff;

SELECT t.tgname, t.tgenabled, pg_catalog.pg_get_triggerdef(t.oid) AS definition
FROM pg_catalog.pg_trigger t
WHERE t.tgrelid = to_regclass('public.discord_meeting_control') AND NOT t.tgisinternal;

ROLLBACK;
```

### 승인, TLS 및 복구

1. 팀장이 메타데이터 차이, 069와 권한 변경, 백업·복원 계획을 승인한다. 최신 복구 시점과
   별도 환경 복원 리허설, 담당자·중단 기준을 확인한다. 기존 서비스와 무관한 복원을 운영에
   덮어쓰는 방식으로 롤백하지 않는다.
2. 격리 PG18에서 합성 스키마를 사용해 069와 인계·실행 승인을 먼저 검증한다. 운영의 실제
   적용은 이전 SQL을 실행하지 않고 승인된 **069만 한 번** 적용하는 별도 절차다. 객체가 이미
   있거나 스키마가 다르면 중단·대조한다. 서비스 시작 코드에서 migration을 실행하지 않는다.
3. 백엔드·Runner·Gateway를 각각 Aiven 서비스의 hostname, 실제 포트, defaultdb로 설정한다.
   기본 require만으로 hostname 인증을 증명하지 않는다. 실제 서비스 인증서 체인에 맞는 CA를
   설치하고 DB_SSLMODE=verify-full과 libpq PGSSLROOTCERT 경로로 접속을 검증한다.
   systemd 실행 계정의 CA 읽기 권한, 도메인 확인, 인증서 교체, EC2/백엔드 egress와 Aiven 접근
   정책, 연결 한도 및 timeout을 시험 환경에서 확인한다. Lambda에 DB 연결·CA·자격증명을 배포하지 않는다.
4. 역할별 public USAGE·필요한 열 권한과 함수 EXECUTE를 확인한다. PostgreSQL 행 잠금 조회에
   필요한 UPDATE 권한까지 검증하되 소유권 열의 UPDATE는 운영 역할로 제한한다. 결과 소비자의
   heartbeat 갱신, 승인 역할의 작업 승인 갱신, 모임 저장소의 결과 확정을 각각 검증한다.
   069의 함수는 호출자 권한으로 실행되며 PUBLIC에 EXECUTE를 부여하지 않는다.
   권한 스냅샷 함수의 EXECUTE는 모임 Scheduler와 승인 API의 DB 역할에만 부여하고,
   소유권 전환 역할이 인계 트리거에서 작업 상태를 SELECT할 수 있는지 검증한다.
   특히 결과 확정의 FOR SHARE OF r,p는 recruits·posts 권한에 영향을 준다. 기존 역할 정책에
   맞지 않으면 넓은 권한을 부여하기 전에 역할 또는 잠금 경계를 재검토한다. 운영 DB 권한 변경과
   역할 구성은 팀장 승인 대상이다.
5. 배포 뒤 우선 기존 Gateway 소유권을 확인한다. 정지·롤백 시 신규 실행과 승인을 차단하고
   진행 중 작업을 대조한다. 069의 테이블에 저장된 실행 승인·이력은 유지한다.
