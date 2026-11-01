# PlayMate Discord Bot

PlayMate의 **모임 기능과 Discord를 연결하기 위한 Bot 모듈**입니다.

모임 Discord 채널은 **모임 하나당 채널 하나**입니다 (모임별 Category / 음성 채널은 만들지 않습니다).
채널은 모임 생성 즉시가 아니라 **모집 마감(`recruits.deadline_at`) 시점**에 만들고, 그때의 최종 참여자에게 권한을 줍니다.
공용 PostgreSQL(`recruit_discord_channels`)과 **DB polling** 방식으로 연결하며, Bot이 DB를 주기적으로 읽어 Discord에 반영합니다.
PUBLIC/PRIVATE 저장 위치와 실제 로그인 사용자 연동은 아직 미완료입니다.
무엇이 구현되었고 무엇이 실환경에서 확인되었는지는 "2. 현재 개발 상태"와 "13. 실환경에서 확인된 내용"을 참고하세요.

> 팀원이 이 저장소를 처음 받아도 구조를 이해하고, 로컬에서 Bot을 실행하고,
> 테스트 코드까지 확인할 수 있도록 정리한 README입니다.

---
## 요약

```text
모임 생성 → (모집 중: Discord 채널 없음)
        ↓
모집 마감(deadline_at) 도달
        ↓
Bot이 최종 참여자 조회 → 공용 카테고리 "모임별 채널" 아래에 모임 채널 1개 생성 → 참여자 권한 부여
        ↓
7일 동안 메시지 없음 → 해당 모임 채널에 Bot 경고 → 24시간 안에 메시지 없으면 채널 삭제
                                     └ 메시지가 생기면 삭제 예약 취소 (취소 안내 Bot 메시지)
```

정책 요약:

- `recruit_mode`가 `regular`든 `short`든 마감 시점에 모임 채널을 만듭니다 (프로젝트 / 스터디 구분 없이 같은 정책).
- `recruits.state`(OPEN/CLOSED 등)는 **모집 상태**일 뿐이며 채널 생성·삭제 기준이 아닙니다. `meeting_end`도 사용하지 않습니다.
- HOST도 일반 참여자입니다. HOST 전용 권한(`manage_channels` 등)과 HOST DM은 없습니다.
- 상시 오픈채팅(자격증 / 기술스택 / 직무)은 모임과 무관한 채널이며 자동 삭제되지 않습니다.

---

## 1. 이 Bot이 하는 일

PlayMate 공식 Discord 서버의 구조는 아래와 같습니다.

```text
PlayMate 공식 Discord 서버
├─ 공지, 자유채팅, 취업 정보 공유, IT 정보 공유   (Bot이 관리하지 않음)
├─ 상시 오픈채팅                                     ← Bot이 시작 때 확인/생성, 자동 삭제 안 함
│  ├─ #자격증-정보공유
│  ├─ #기술스택-정보공유
│  └─ #직무-정보공유
└─ 모임별 채널                                       ← 공용 카테고리 (가득 차면 "모임별 채널 2" ...)
   ├─ Python 스터디         ← 모임 하나당 텍스트 채널 하나
   ├─ SQLD 스터디
   └─ LangChain 프로젝트
```

현재 구현된 핵심 기능은 다음과 같습니다.

- 모집 마감(`deadline_at`) 시점에 모임 채널 1개 생성 + 최종 참여자(HOST 포함) 권한 부여
  (`deadline_at`이 없는 예전 데이터만 regular는 `regular_start_date` 당일 00:00, short는 `meeting_start` 날짜 00:00 기준,
  그 기준도 없으면 만들지 않고 `MANUAL:` 실패 행을 남깁니다)
- Bot이 꺼져 있던 동안 마감된 모임도 다음 polling에서 복구해 생성 (기간 제한 없음, 한 번에 5개까지, 아래 참고)
- PUBLIC / PRIVATE 모임 권한 처리, 참여 취소 시 권한 회수
- 모임 채널 활동 시각 추적 (DB `last_activity_at`, 채널 ID 기준)
- 7일 동안 메시지가 없으면 **해당 모임 채널에** Bot 경고 메시지 (DM 아님)
- 경고 후 24시간 안에 메시지가 없으면 채널 자동 삭제, 메시지가 생기면 삭제 예약 취소 + 취소 안내 메시지
- 삭제 직전 최신 활동 여부를 다시 확인하는 안전장치, 매핑된 채널 **하나만** 삭제
- 상시 오픈채팅 채널 3개 확인/생성 (중복 생성 없음, 삭제 보호)
- Discord 채널 삭제가 확인된 뒤에만 `discord_deleted_at` 기록

메시지 **본문은 저장하지 않습니다.**
활동 여부 판단에는 마지막 활동 시각만 사용합니다.

---

## 2. 현재 개발 상태

"구현됨"은 코드가 있고 자동 테스트로 확인했다는 뜻이고, "실환경 확인"은 실제 Discord 서버와
공용 DB로 직접 확인한 항목입니다. 두 가지는 구분해서 읽어야 합니다. 실환경 결과는 13절에 있습니다.

### 구현됨 (자동 테스트로 확인)

- Discord Bot 로그인 / Guild 연결
- 모집 마감(`deadline_at`) 기준 모임 채널 생성 (마감 전에는 생성 안 함, 놓친 마감 복구, 중복 생성 방지, 실패 복구)
- Category / 음성 채널 없이 **모임 하나에 채널 하나**, 채널 ID는 `recruit_discord_channels.discord_text_channel_id`에 저장
- 최종 참여자 권한 부여 (`recruit_members` → `members.discord_id`), HOST는 일반 참여자, 취소·무효 ID·`member_id=-1` 제외
- PUBLIC / PRIVATE 권한 정책 (코드 유지, 현재 DB 연동은 임시로 PUBLIC)
- 활동 감지 → 채널 ID로 모임을 찾아 `last_activity_at` 갱신
- 7일 무활동 → 모임 채널 경고 → 24시간 뒤 삭제, 활동 시 취소, 삭제 직전 재확인, 상태는 DB에 저장되어 재시작 후에도 유지
- 삭제는 DB에 매핑된 채널 하나만 (카테고리나 다른 채널은 절대 지우지 않음, 주제 표지와 보호 목록으로 이중 확인)
- 상시 오픈채팅(자격증 / 기술스택 / 직무) 확인·생성, 자동삭제 제외
- 실패 복구: `FAILED` / `MANUAL` / `ABORTED` 구분, row lock, timeout, 취소 안전성

자동 테스트는 두 종류입니다.

- **mock 테스트** (`test_refactor.py`, `test_safety.py`): Discord와 DB에 연결하지 않는 정책·설정 확인.
- **DB 통합 테스트** (`test_db_integration.py`): **실제 일회용 PostgreSQL**을 쓰지만 Discord는
  **가짜 객체**입니다. 실제 Discord 서버와의 동작을 증명하지는 않습니다.

### 실환경에서 확인된 것 / 아직 확인하지 못한 것

**#45 모임 채널 구조 개편은 실제 Discord 서버에서 아직 확인하지 않았습니다.** 자동 테스트(mock과 일회용
PostgreSQL + 가짜 Discord)만 통과한 상태이며, 실서버 확인 항목은 13절에 정리했습니다.
13절의 "DB 연동 이후" 표는 이전 구조(카테고리 방식)에서 팀이 확인한 결과입니다.

### 아직 하지 않은 것 (미완료)

- **PUBLIC / PRIVATE 저장 위치**: 미확정입니다. `config.DEFAULT_VISIBILITY="PUBLIC"` 임시 정책을 사용합니다.
- **실제 로그인 사용자 기반 참여/취소**: Backend의 참여(`join`)와 취소(`cancel_join`)가 아직 `member_id=-1`로 고정되어 있어
  실제 사용자가 참여해도 Discord 참여자로 연결되지 않습니다. `member_id=-1`, `discord_id`가 없거나 숫자가 아닌 회원은 권한 동기화에서 제외합니다.
  **Discord 참여자 권한 동기화 로직은 구현되어 있으나, 현재 Backend 참여/취소가 실제 로그인 member_id 대신 -1을 사용하므로
  운영 적용 전 실제 회원 연동 수정이 필요합니다.** (별도 Backend Issue로 처리 예정, #45에서는 수정하지 않았습니다.)
- **마감 이후 자동 마감 상태**: Backend에 `deadline_at` 이후 `state`를 자동으로 닫는 로직이 없습니다. Bot은 `state`가 아니라
  `deadline_at`을 직접 기준으로 쓰므로 영향은 없지만, 화면 표시와 어긋날 수 있습니다 (Backend 담당).
- 이전 구조(모임별 Category + 채팅 + 음성)로 만들어진 행(`discord_category_id`가 있는 행)은 새 로직이 **관리하지 않고 건드리지 않습니다.**
  해당 Discord 카테고리는 운영자가 직접 정리해야 합니다.
- 공용 카테고리 "모임별 채널"은 채널 50개가 한도라서 가득 차면 "모임별 채널 2"처럼 늘립니다 (서버 전체 채널 500개 한도는 별도).
- Backend → Bot 내부 API 호출 방식은 도입하지 않았습니다 (현재는 DB polling).

## 3. 프로젝트 구조

```text
playmate-discord-bot/
│
├─ bot.py
├─ config.py
│
├─ services/
│  ├─ __init__.py
│  ├─ meeting_space.py
│  ├─ permissions.py
│  ├─ lifecycle.py
│  ├─ db_sync.py
│  ├─ official_channels.py
│  ├─ notification_service.py
│  ├─ hot_content_service.py
│  └─ career_content_service.py
│
├─ handlers/
│  ├─ __init__.py
│  ├─ message_handler.py
│  ├─ notification_command_handler.py
│  └─ promotion_command_handler.py
│
├─ repositories/
│  ├─ __init__.py
│  ├─ meeting_repository.py
│  ├─ db.py
│  ├─ notification_repository.py
│  ├─ content_repository.py
│  └─ career_content_repository.py
│
├─ tests/
│  ├─ fixtures/
│  │  └─ original_bot.py      (리팩터링 이전 원본 Bot. 참고용으로 보관하며 현재 테스트는 사용하지 않음)
│  ├─ test_refactor.py
│  ├─ test_safety.py
│  ├─ test_notification_promotion.py
│  └─ test_db_integration.py
│
├─ .env.example
├─ .gitignore
├─ requirements.txt
└─ README.md
```

### 파일별 역할

| 파일 | 역할 |
| --- | --- |
| `bot.py` | Discord Client 생성, 저장소 선택, 이벤트 등록, 상시 채널 확인, DB 동기화·라이프사이클 Task 시작 |
| `config.py` | 환경변수와 시간 정책 관리 |
| `services/meeting_space.py` | 모임 채널 1개 생성 / 매핑된 채널 하나만 삭제 (공용 카테고리 확보, 삭제 안전 확인) |
| `services/permissions.py` | 참여자 / 참여 취소 권한 처리 (HOST도 같은 정책) |
| `services/lifecycle.py` | 7일 무활동 채널 경고 / 24시간 뒤 삭제 정책과 주기 검사 |
| `services/db_sync.py` | DB polling: 마감된 모임의 채널 생성, 참여자 권한 동기화 |
| `services/official_channels.py` | 상시 오픈채팅 채널 확인/생성, 삭제 보호 목록 |
| `handlers/message_handler.py` | 모임 채널(채널 ID 기준) 활동 감지, 삭제 예약 취소와 안내 메시지 |
| `repositories/meeting_repository.py` | 저장소 경계. 메모리 구현(DB 설정 없을 때)과 PostgreSQL 구현 |
| `repositories/db.py` | 알림 / 공식 채널 기능 전용 DB 연결 (모임 저장소와 분리) |
| `services/notification_service.py`, `handlers/notification_command_handler.py`, `repositories/notification_repository.py` | `/알림설정`, notifications polling (19절) |
| `services/hot_content_service.py`, `handlers/promotion_command_handler.py`, `repositories/content_repository.py` | `/게시글추천` 수동 추천 (19절) |
| `services/web_links.py` | PlayMate 웹 상세 페이지 주소 (게시판 / 모임 / 취업) |
| `services/career_content_service.py`, `repositories/career_content_repository.py` | 취업 소식 포워딩 구조 (19절, 저장소 미연결) |
| `tests/test_refactor.py` | 정책 회귀 테스트 (mock, Discord/DB 연결 없음) |
| `tests/test_safety.py` | 운영 설정, 의존성, `.env` 제외 등 안전성 검증 |
| `tests/test_notification_promotion.py` | 알림 설정(기본 ON) / polling, 웹 링크, `/게시글추천` 권한·조회, 취업 D-3·D-1 판정 (mock) |
| `tests/test_db_integration.py` | 실제 일회용 PostgreSQL + 가짜 Discord 객체로 DB 연동·실패 복구·경쟁 조건 테스트 |
| `services/career_notice_service.py`, `repositories/career_notice_repository.py` | 취업게시판 신규 글 자동 공지 (매일 18:00, 19절) |
| `tests/test_career_notice.py` / `tests/test_career_notice_db.py` | 취업 자동 공지 정책 (mock) / 선점·재시작·동시 실행 (일회용 PostgreSQL) |

---

## 4. 권한 정책

### PUBLIC 모임

비참여자도 모임의 존재와 대화를 볼 수 있지만 직접 참여하기 전에는 글을 쓸 수 없습니다.

| 사용자 | 채널 보기 | 메시지 읽기 | 메시지 쓰기 |
| --- | --- | --- | --- |
| 비참여자 | O | O | X |
| 참여자 (HOST 포함) | O | O | O |

### PRIVATE 모임

비참여자에게는 모임 채널 자체가 보이지 않습니다.

| 사용자 | 채널 보기 | 메시지 쓰기 |
| --- | --- | --- |
| 비참여자 | X | X |
| 참여자 (HOST 포함) | O | O |

### HOST도 일반 참여자입니다

`recruit_members`에서 `JOINED`인 모든 사용자(HOST 포함)가 같은 권한을 받습니다.

```text
view_channel / read_message_history / send_messages = True
manage_channels / manage_messages = 부여하지 않음 (None)
```

HOST 전용 권한과 HOST DM은 없습니다. 채널 관리 권한을 주지 않는 이유: HOST가 채널을 지우거나 옮기면
Bot의 활동 감지와 삭제 대상 추적이 어긋날 수 있습니다. 음성 채널은 만들지 않으므로 `connect` / `speak` 권한도 없습니다.

---

## 5. 모임 채널 라이프사이클

### 채널 생성 (모집 마감 시점)

```text
모임 생성 (recruits.deadline_at = 모집 마감 시각)
    ↓  (모집 중에는 Discord 채널 없음)
deadline_at 도달
    ↓
Bot polling이 "마감이 지났고 채널 행이 없는 모임"을 조회 (재시작/장애로 놓친 모임도 같은 조회로 복구)
    ↓
PENDING 행 선점 (중복 생성 방지) → 최종 JOINED 참여자 조회 (HOST 포함) → 채널 생성 + 권한 → 채널 ID 저장 (SUCCESS)
```

- 마감 시각은 `deadline_at`입니다. **`deadline_at`이 없는 예전 데이터만** regular는 `regular_start_date` 당일 00:00,
  short는 `meeting_start` 날짜 00:00을 대신 씁니다. 기준이 전혀 없으면 임의로 지금 만들지 않고
  `sync_error`가 `MANUAL:`로 시작하는 실패 행을 남깁니다.
- 시각은 Backend와 같은 기준(timezone 없는 한국 시각)으로 비교합니다. `deadline_at`은 프론트가 보낸 한국 시각이 timezone 없이
  저장된 값입니다. Bot은 서버 timezone과 무관하게 KST 시각에서 timezone만 떼서 비교하고, Backend의 마감 후 참여 차단도 같은 기준
  (`kst_now()`)으로 비교합니다. 서버가 UTC로 실행돼도 마감 판단이 9시간 어긋나지 않습니다.
- **복구에는 기간 제한이 없습니다.** "마감이 지났고, 채널이 아직 없고, 글이 삭제되지 않은 모임"이면 얼마나 오래전에 마감됐든 만듭니다
  (7일 같은 값은 회의에서 정한 정책이 아니므로 코드에 고정하지 않았습니다). 대신 과거 데이터가 한꺼번에 채널이 되지 않도록
  **한 번의 polling에서 5개까지만**(`PLAYMATE_PROVISION_BATCH_LIMIT`) 마감이 오래된 순서로 만들고 나머지는 다음 polling에서 만듭니다.
  Backend의 `state` / 종료 상태가 아직 완전하지 않아 "지금도 채널이 필요한 모임인지"를 정확히 가를 수 없기 때문입니다.
  **처음 배포할 때** 오래된 모임이 많다면 환경변수 `PLAYMATE_CATCHUP_DAYS=<일>`로 복구 범위를 정할 수 있습니다 (기본값은 제한 없음).
- **생성 중 상태 변경 재검증**: 채널을 만든 뒤 SUCCESS로 확정하기 직전에, 같은 트랜잭션에서 `recruits` 행을 잠그고
  ① 대상 모임 방식 ② 글이 삭제되지 않았는지 ③ `deadline_at`이 지났는지를 다시 확인합니다. 그 사이 마감이 연장되었거나 글이 삭제되었다면
  SUCCESS로 기록하지 않고 **방금 만든 그 채널만** 삭제합니다 (`sync_error`는 `RECHECK:`, 조건이 다시 맞으면 5분 뒤 자동 재시도).
  모임 방식이 바뀐 경우는 `ABORTED:`, 정리에 실패하면 `MANUAL:`입니다.
- 참여자는 채널 생성 시점에 한 번 조회해서 권한을 줍니다. 이후에도 polling이 JOINED / CANCELED 변화를 같은 정책으로 반영합니다
  (취소한 사람의 권한 회수 등). `recruits.state`는 보지 않습니다.
- 채널은 공용 카테고리(`MEMBER`가 아닌 모두가 쓰는 "모임별 채널") 아래에 만들고, 채널 주제에 `PlayMate 모임 #<recruit_id>` 표지를 남깁니다.

### 비활성 정책 (프로젝트 / 스터디 공통)

```text
모임 채널에 7일 동안 메시지 없음
    ↓
해당 모임 채널에 Bot 경고 메시지 (DM 아님) → inactivity_warned_at 기록, scheduled_delete_at = 24시간 후
    ↓
24시간 대기
    ├─ 메시지 발생 → 삭제 예약 취소 (경고/예약 초기화) + "삭제 예약이 취소되었습니다" Bot 메시지
    │
    └─ 메시지 없음 → 삭제 직전 DB 상태 재확인 → 모임 채널 삭제 → 삭제 확인 후 discord_deleted_at 기록
```

경고 문구: "최근 7일 동안 대화가 없어 이 채널은 삭제 예정입니다. 24시간 이내에 대화가 발생하면 삭제가 자동으로 취소됩니다."
점검 주기는 24시간 유예를 지키려고 **1시간**입니다 (테스트 모드 1분).

- Bot 메시지는 활동으로 세지 않습니다. 활동 감지는 `message.channel.id`로 모임을 찾습니다.
- 상태 변경은 목적별 **조건부 UPDATE**로만 하므로, 오래된 값이 최신 활동을 덮어쓰지 못합니다.
- 경고 메시지를 보내지 못하면(권한 없음 등) 삭제 예약을 저장하지 않고 다음 주기에 다시 시도합니다.
- **삭제는 DB에 매핑된 채널 하나만** 대상입니다. 카테고리나 하위 채널 전체를 지우는 로직은 없으며, 삭제 직전에
  ① 보호 목록(상시 오픈채팅 등) ② 텍스트 채널 여부 ③ 채널 주제의 `PlayMate 모임 #<recruit_id>` 표지를 다시 확인합니다.
  어느 하나라도 맞지 않으면 삭제하지 않고 삭제 완료로도 기록하지 않습니다.
- 채널이 캐시에 없다는 것은 "없음"의 근거가 아닙니다. `fetch_channel`로 확인하고, Forbidden / HTTP 오류 / 타임아웃은
  "삭제 미완료"로 취급합니다. `discord_deleted_at`은 API가 NotFound를 돌려준 뒤에만 기록합니다.
- **모임 방식 변경 직렬화 (DB row lock)**: 삭제와 참여/취소 권한 변경은 `recruits` 행에 `SELECT ... FOR SHARE`를 잡은 트랜잭션 안에서
  실행합니다. 작업이 끝날 때까지 락을 유지하므로 Backend의 모임 방식 변경 UPDATE는 그동안 대기하고, 이미 대상이 아니게 commit되었다면
  Bot은 락을 얻은 뒤 이를 확인하고 Discord를 건드리지 않습니다. 타임아웃은 세 가지로 구분됩니다.
  - **DB 락 대기 5초** (`lock_timeout`): Backend가 해당 행을 잡고 있어 락을 못 얻으면 이번 주기는 건너뛰고 다음 주기에 재시도합니다.
  - **Discord 작업 전체 30초** (`DISCORD_LOCK_HOLD_SECONDS`): 락을 얻은 *이후*의 전체 구간(채널 조회, 삭제, 최종 확인, `discord_deleted_at` 기록)이
    하나의 예산입니다. 초과하면 중단하고 기록 없이 rollback해 락을 풀며 다음 주기에 재시도합니다. 권한 변경도 같은 예산을 씁니다.
  - **서버 안전망 60초** (`idle_in_transaction_session_timeout`): Bot이 비정상 종료되었을 때를 위한 최후 수단입니다.
- **취소(cancel) 안전성**: 락 획득이 worker thread에서 진행되므로, 획득 도중 작업이 취소되어도 세션의 소유권이 한 곳으로만 넘어가도록
  했습니다. 어느 시점에 취소되어도 열린 트랜잭션과 연결이 남지 않습니다.
- **삭제 기록은 락과 같은 트랜잭션에서만** 합니다 (`mark_deleted`). timeout·취소·오류가 나면 진행 중인 SQL을 서버에서 취소하고
  ROLLBACK하므로 대기 중이던 UPDATE가 나중에 COMMIT되는 일이 없습니다. Discord 채널이 이미 사라졌는데 기록만 실패한 경우는 다음 주기에
  "이미 없음"으로 기록됩니다.
- 삭제 시도 중 들어온 활동은 거부되지 않고 기록되며, 삭제가 실패하면 최신 활동 기준으로 다시 계산됩니다.
- **활동 처리와 삭제의 경쟁 방지**: 삭제 직전에 ① Discord 채널의 최근 메시지(최신 50개) 중 경고 이후의 **사용자** 메시지가 있는지
  확인하고(Bot 메시지는 활동으로 세지 않음), ② DB의 삭제 예약 상태를 다시 읽고, ③ 메시지 이벤트가 도착했는지 확인한 뒤
  ④ `channel.delete()` 호출 직전에 한 번 더 확인합니다. 활동 처리(`message_handler`)와 lifecycle은 **같은 채널 락**을 쓰므로,
  활동이 먼저 처리되어 예약이 취소되면 삭제 작업은 그 결과를 보고 중단하고, 삭제가 이미 진행 중이면 활동 처리는 삭제가 끝난 뒤에
  실행되어 이미 삭제된 모임에는 "취소되었습니다" 안내를 보내지 않습니다. Discord 최근 메시지를 확인할 수 없으면(권한/HTTP 오류)
  삭제하지 않고 다음 주기에 다시 시도합니다. 이 보호는 Bot 프로세스 하나 기준입니다 (Bot을 여러 개 동시에 실행하는 구성은 지원하지 않음).

### 상시 오픈채팅

모임과 무관한 채널입니다 (1차는 큰 분류 3개만, 세분화는 범위 밖).

```text
상시 오픈채팅 (카테고리)
├─ #자격증-정보공유
├─ #기술스택-정보공유
└─ #직무-정보공유
```

- Bot이 시작할 때(`on_ready`) 카테고리와 채널이 있는지 확인하고, **없는 것만** 만듭니다. 같은 이름의 채널이 서버에 이미 있으면 그것을 재사용하므로
  재시작해도 중복 생성되지 않습니다. 채널 하나의 생성이 실패해도 나머지는 계속 시도하고, 실패해도 모임 기능은 그대로 동작합니다.
- `recruit_id`와 연결하지 않고 `recruit_discord_channels` 행도 만들지 않으므로 비활성 자동삭제 대상이 될 수 없습니다.
  추가로 채널 ID를 삭제 보호 목록에 넣어, 모임 채널 삭제 함수가 이 채널들(그리고 HOT / 취업 소식 채널)을 거부합니다.
- **필수 3개가 모두 있을 때만 완료**로 봅니다. 일부만 만들어졌다면 완료로 보지 않고, 10분마다(`OFFICIAL_RETRY_MINUTES`) 또는 다음 `on_ready`에
  없는 채널만 다시 만듭니다 (있는 채널은 재사용하므로 중복되지 않음). 모두 준비되면 재시도가 멈춥니다.
- 이름은 `config.OFFICIAL_CATEGORY_NAME`, `config.OFFICIAL_CHANNEL_NAMES`에서 바꿉니다.

---

## 6. 실행 전 준비

필요한 환경:

- Python
- Discord Bot
- Bot을 초대한 Discord 테스트 서버

현재 검증 환경:

```text
Python 3.13.15
discord.py 2.7.1
python-dotenv 1.2.4
psycopg[binary] 3.3.6   (PostgreSQL 연결, DB 연동 시 필요)
tzdata 2026.5           (Asia/Seoul 시간대. 일부 리눅스 이미지는 시스템 tzdata가 없어 명시적으로 고정)
```

운영 DB 계정은 `recruit_discord_channels`와 `recruits`/`posts`/`recruit_members`/`members`를 조회·수정할 수 있어야 하고,
`recruits`에 대한 `SELECT ... FOR SHARE`(UPDATE 권한)가 필요합니다
(SUCCESS 확정, 권한 변경, 삭제가 recruit_mode 변경과 엇갈리지 않게 행을 잠그기 위함).
락 세션마다 DB 연결을 하나 더 사용하므로, 동시에 처리하는 작업 수만큼의 연결 여유가 필요합니다 (순차 처리라 보통 1개).

### Discord Bot 준비

Discord Developer Portal에서 Bot을 생성한 뒤 테스트 서버에 초대합니다.

이 Bot은 채널 생성·삭제와 Permission Overwrite 변경을 수행하므로,
테스트 서버에서 이에 필요한 Discord 권한이 있어야 합니다.

처음 테스트할 때는 **실제 운영 서버가 아닌 별도의 테스트 서버 사용을 권장합니다.**

---

## 7. 설치

저장소를 받은 뒤 프로젝트 폴더로 이동합니다.

```powershell
cd playmate-discord-bot
```

가상환경 사용을 권장합니다.

```powershell
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

필요 패키지를 설치합니다.

```powershell
python -m pip install -r requirements.txt
```

현재 `requirements.txt`:

```text
discord.py==2.7.1
python-dotenv==1.2.4
psycopg[binary]==3.3.6
tzdata==2026.5
```

새 가상환경에서 위 파일만으로 설치한 뒤 `bot` import와 회귀 테스트가 통과하는 것을 확인했습니다.

---

## 8. 환경변수 설정

`.env.example`을 복사해서 `.env`를 만듭니다.

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

`.env`:

```dotenv
DISCORD_BOT_TOKEN=여기에_본인의_Bot_Token
DISCORD_GUILD_ID=여기에_테스트_서버_ID
PLAYMATE_TEST_MODE=false

# 공용 PostgreSQL (Backend와 같은 변수 이름). 비워 두면 메모리 저장소로 동작하며 DB 동기화는 시작되지 않습니다.
DB_HOST=
DB_PORT=
DB_USER=
DB_PASSWORD=
DB_NAME=
DB_SSLMODE=

# DB ↔ Discord 동기화 주기(초), 기본 10
PLAYMATE_SYNC_INTERVAL_SECONDS=

# 선택: 알림 / 공식 채널 기능 (비우면 해당 기능만 꺼짐, 19절)
PLAYMATE_ADMIN_ROLE_ID=
PLAYMATE_HOT_CHANNEL_ID=
PLAYMATE_CAREER_CHANNEL_ID=   # #취업-소식 채널: 취업게시판 신규 글 자동 공지 (매일 18:00)
PLAYMATE_WEB_BASE_URL=   # 예: https://playmate.example.com (localhost는 PLAYMATE_TEST_MODE=true일 때만)
```

### 중요

`.env`에는 실제 Bot Token이 들어가기 때문에 **GitHub에 절대 커밋하면 안 됩니다.**

이 프로젝트의 `.gitignore`에는 `.env`가 제외되어 있습니다.

확인:

```powershell
git status
```

`.env`가 Git 추적 대상으로 나타나지 않는지 확인하세요.

---

## 9. 테스트 모드와 운영 모드

`PLAYMATE_TEST_MODE`는 라이프사이클 검사 주기를 결정합니다.

### 운영 기본값

```dotenv
PLAYMATE_TEST_MODE=false
```

검사 주기:

```text
86,400초 = 하루 1회
```

환경변수를 아예 작성하지 않아도 기본값은 `false`입니다.

### 테스트 모드

```dotenv
PLAYMATE_TEST_MODE=true
```

검사 주기:

```text
60초 = 1분
```

빠르게 라이프사이클 동작을 확인할 때만 사용하세요.

> 테스트 후 `true`를 그대로 두고 운영하지 않도록 주의하세요.

---

## 10. Bot 실행

```powershell
python bot.py
```

정상 실행 예시:

```text
Bot 로그인 성공: PlayMate Bot#....
서버 연결 성공: PlayMate Bot Test
PlayMate Discord Bot 라이프사이클 관리 준비 완료
PlayMate DB 동기화 시작            (DB_* 설정이 있을 때만)
상시 오픈채팅 채널 확인 완료: 자격증-정보공유, 기술스택-정보공유, 직무-정보공유
모임 라이프사이클 검사 시작 (실서비스: 1시간 주기)

[모임 채널 라이프사이클 검사] YYYY-MM-DD HH:MM:SS
```

라이프사이클 Task는 시작 직후 한 번 실행되고,
그 이후 설정된 주기마다 다시 실행됩니다.

즉 운영 모드에서도 처음 실행 직후 검사 로그가 한 번 출력되는 것은 정상입니다.

---

## 11. "실행했는데 모임 채널이 안 생겨요"

모임 채널은 모임 생성 즉시가 아니라 **모집 마감(`deadline_at`)이 지난 뒤**에 만들어집니다. `DB_*` 환경변수가 설정되어 있으면 Bot은
약 10초마다(`PLAYMATE_SYNC_INTERVAL_SECONDS`) 공용 DB를 조회해서 마감이 지난 모임에 채널을 만듭니다. 만들어지지 않는다면 아래를 확인하세요.

- `DB_*`가 없으면 메모리 저장소로 시작하며 "DB 설정이 없어 메모리 저장소를 사용합니다" 로그가 나옵니다.
- `deadline_at`이 아직 지나지 않았나요? (마감 전에는 만들지 않습니다.)
- 한 번의 polling에서는 최대 5개까지만 만듭니다 (`PLAYMATE_PROVISION_BATCH_LIMIT`). 밀린 모임이 많으면 몇 번의 polling에 걸쳐 만들어집니다.
  `PLAYMATE_CATCHUP_DAYS`를 지정했다면 그보다 오래된 마감은 만들지 않습니다.
- 글이 삭제 상태이거나 `recruit_mode`가 `regular` / `short`가 아니면 만들지 않습니다.
- `recruit_discord_channels`에 이미 행이 있으면 건너뜁니다.
  - `FAILED`: 일반 오류는 5분 뒤 자동 재시도합니다.
  - `sync_error`가 `MANUAL:` 또는 `ABORTED:`로 시작하면 **자동 재시도하지 않습니다** (운영자 확인 필요, 아래 15절).
    마감 기준(`deadline_at` / 시작일)이 전혀 없는 모임도 `MANUAL:`로 남습니다.
  - `PENDING`이 10분 넘게 남아 있으면 중단된 것으로 보고 `MANUAL:`로 표시합니다.
- 이전 구조(카테고리 방식)로 만든 행이 있는 모임은 새로 만들지 않습니다.
- Bot 계정이 채널 생성 / 삭제 / 권한 관리 권한을 가지고 있는지 확인하세요.

---

## 12. 테스트 실행

### 정책 회귀 테스트 (mock)

Discord와 DB에 연결하지 않고, 가짜 객체로 정책과 배선을 확인합니다.

```powershell
python tests/test_refactor.py
```

검증 내용 예시:

- 7일 / 24시간 경계값, 모임 채널에 경고 메시지(DM 아님), 24시간 전 삭제 없음
- 채널 구조: Category / 음성 채널을 만들지 않고 모임 채널 하나만 생성, 공용 카테고리 재사용·확장
- 삭제 안전: 매핑된 채널 하나만 삭제, 다른 모임 채널·카테고리·보호된 채널은 삭제 거부
- 활동 재개와 취소 안내 메시지, 채널 ID 기준 활동 감지 (Bot / DM / 다른 채널 무시)
- 삭제 성공 / 실패 / 서버 미조회
- 상시 오픈채팅 3개 확인·생성(중복 없음, 보호 목록 등록)
- 중복 Task 시작 방지

현재 **88개 단언을 통과**한 상태입니다.

### 알림 / 공식 채널 정책 테스트 (mock)

```powershell
python tests/test_notification_promotion.py
```

알림 기본 ON·토글과 저장 실패 안내, notifications 테이블·SQL 미연결 시 건너뛰기, 알림 한 건 실패 격리,
웹 상세 링크 생성, HOT 자동 선정 제거, `/게시글추천` 권한·게시판/모임/취업 조회, 취업 D-3/D-1 판정을 확인합니다.

### 취업 자동 공지 테스트

```powershell
python tests/test_career_notice.py
# 일회용 DB가 있을 때 (localhost만 허용, public 스키마의 테이블을 지우고 다시 만듦)
$env:PLAYMATE_TEST_PG_DSN="host=127.0.0.1 port=55432 user=postgres password=test dbname=pm"
python tests/test_career_notice_db.py
```

### 안전성 테스트

```powershell
python tests/test_safety.py
```

검증 내용:

- `PLAYMATE_TEST_MODE` 기본값
- 운영 검사주기 3,600초 (24시간 유예를 지키기 위한 1시간 주기)
- HOST 전용 함수와 채널 관리 권한이 없고, 참여자 권한이 보기/읽기/쓰기뿐인지
- 의존성 버전
- `.env` 배포 제외 등

### DB 통합 테스트 (실제 일회용 PostgreSQL + 가짜 Discord)

DB 동작은 실제 PostgreSQL로 확인하지만 Discord는 가짜 객체입니다. 일회용 PostgreSQL이 필요합니다. 공용 DB로 실행하지 마세요 (테스트는 별도 스키마 `bot_test`를 만들고 지웁니다).

```powershell
docker run -d --name pm-test-pg -e POSTGRES_PASSWORD=test -e POSTGRES_DB=pm -p 55432:5432 postgres:16
$env:PLAYMATE_TEST_PG_DSN = "host=127.0.0.1 port=55432 user=postgres password=test dbname=pm"
python tests/test_db_integration.py
```

`PLAYMATE_TEST_PG_DSN`이 없으면 건너뜁니다. 검증 내용:

- 마감 전 미생성 / 마감 후 생성 / 놓친 마감 복구(기간 제한 없음, poll당 상한, 운영자 지정 범위) / 중복 생성 방지 / fallback(시작일) / 기준 없음 → `MANUAL:`
- 생성 중 마감 연장·글 삭제·방식 변경 → SUCCESS 미기록 + 만든 채널만 정리 (다른 모임/공식 채널 불변), `RECHECK:` 재시도·`MANUAL:`
- 최종 참여자 권한 (HOST 포함, CANCELED·`-1`·무효 ID 제외), 채널 하나·공용 카테고리·음성 없음
- 7일 경고 / 24시간 삭제 / 활동 시 취소 / 삭제 직전 활동 경쟁 / 경고 전송 실패·전송 중 활동
- 단일 채널 삭제(다른 채널·카테고리 불변), 주제 표지 불일치·보호 채널 삭제 거부, 예전 카테고리 방식 행 제외
- 선점 동시성 / 응답 유실 / 저장 실패 정리 / `MANUAL:` · `ABORTED:` 재시도 제외
- row lock 직렬화(Backend와 두 연결 경쟁), 취소·timeout 시 연결 누수 없음, `mark_deleted`가 락 트랜잭션 안에서만 COMMIT됨

---

## 13. 실환경에서 확인된 내용

### #45 개편 이후 (모임 하나에 채널 하나, 마감 시점 생성)

**실제 Discord 서버 확인은 아직 하지 않았습니다.** 테스트 서버에서 확인할 항목은 다음과 같습니다.

- 마감 전 모임에는 채널이 없고, 마감이 지나면 "모임별 채널" 아래에 채널이 하나만 생기는지 (Category / 음성 없음)
- 최종 참여자만 글을 쓸 수 있고 비참여자는 읽기만 되는지 (**Owner가 아닌 일반 사용자 계정으로** 확인)
- 7일 무활동 시 채널에 경고가 올라오고, 24시간 안에 메시지를 보내면 취소 안내가 올라오는지, 아니면 그 채널만 삭제되는지
- 상시 오픈채팅 채널 3개가 시작 때 한 번만 만들어지고 재시작해도 중복되지 않는지
- Bot 역할에 채널 관리(생성 / 삭제 / 권한) 권한이 있는지, 공용 카테고리가 50개를 넘을 때 동작

### 이전 구조(모임별 Category) — 실제 Discord 서버 + 공용 PostgreSQL (팀 확인 결과)

아래는 #45 이전의 카테고리 방식 기준 결과이며, 새 구조의 검증이 아닙니다.

| 항목 | 결과 |
| --- | --- |
| Bot 로그인 및 Gateway 연결 | 확인됨 |
| 공용 PostgreSQL DB polling | 확인됨 |
| regular 모임 → 카테고리 / 채팅 / 음성 자동 생성 | 확인됨 |
| Bot 재시작 후 중복 채널 생성 없음 | 확인됨 |
| 실제 `members.discord_id` 기반 JOINED 참여자 권한 부여 | 확인됨 |
| 실제 메시지 → `last_activity_at` 갱신 | 확인됨 |
| CANCELED 감지 및 PUBLIC 읽기 전용 처리 로직 실행 | 실행 확인 (아래 한계 참고) |
| short 모임은 채널을 만들지 않음 | 확인됨 |
| short 모임은 `recruit_discord_channels`에도 행을 만들지 않음 | 확인됨 |

**확인하지 못한 항목**

- 일반 사용자 계정의 실제 쓰기·음성 차단: 테스트 계정이 서버 Owner라서 권한 제한을 받지 않아 최종 확인하지 못했습니다.
- HOST 권한과 HOST DM: DB 조회 연결 후 DB 통합 테스트로는 확인했지만, 실제 Discord 서버에서는 아직 확인하지 않았습니다.
- 30일 비활성 경고, 7일 유예, 자동 삭제를 DB 연동 상태의 실제 서버에서 끝까지 돌려 본 결과는 아직 없습니다.
- PRIVATE 모임, `MANUAL:` / `ABORTED:` 상태의 실제 운영 시나리오, 실제 로그인 사용자 기반 참여/취소도 확인하지 못했습니다.

### DB 연동 이전: 독립 Bot의 7단계 검증

DB 연동 이전의 독립 Bot에서 실제 테스트 서버로 다음을 확인했습니다. 현재 DB 연동 코드의 검증은 아닙니다.

```text
모임 공간 생성                    PASS
PUBLIC 비참여자 권한              PASS
PRIVATE 비참여자 숨김             PASS
참여자 권한 부여                  PASS
참여 취소 권한 회수               PASS
HOST 권한                         PASS
모임 공간 삭제                    PASS
```

테스트 과정에서 생성한 임시 카테고리와 채널은 검증 종료 후 모두 삭제했습니다.

---

## 14. 보안 주의사항

다음 값은 코드, README, Issue, Discord 채팅, GitHub 등에 올리지 마세요.

- Discord Bot Token
- `.env`
- DB 비밀번호
- 향후 추가될 OAuth Client Secret

반드시 환경변수로 관리합니다.

공유할 때는:

```text
.env            X
.env.example    O
```

형태로 전달합니다.

Token이 외부에 노출되었다면 단순히 파일에서 지우는 것으로 끝내지 말고,
Discord Developer Portal에서 Token을 재발급해야 합니다.

---

## 15. Repository 구현과 한계

- `DB_*` 환경변수(Backend와 같은 이름)가 있으면 `PostgresMeetingRepository`를 사용합니다. 상태가 DB에 저장되어 재시작 후에도 유지됩니다.
- `DB_*`가 없으면 `InMemoryMeetingRepository`로 동작하며, 이 경우 프로세스 종료 시 상태가 사라지고 DB 동기화는 시작되지 않습니다.
- DB 호출은 동기 코드를 worker thread에서 실행하며, 연결 타임아웃 10초 / statement timeout 15초 / row lock 대기 5초입니다.
- Backend가 `recruits`를 오래 잠그고 있으면(미커밋 트랜잭션) Bot의 해당 작업은 건너뛰어지고 다음 주기에 재시도됩니다.
- 쓰기 SQL은 자동 재시도하지 않습니다 (응답이 유실되어도 commit되었을 수 있기 때문). 읽기만 1회 재시도합니다.
- Bot 프로세스는 1개를 전제로 합니다. 생성 선점(`PENDING`)은 DB에서 원자적이라 중복 실행에도 중복 생성은 막지만, 권한 동기화는 다중 프로세스를 고려하지 않았습니다.
- **`recruits.discord_channel_id` / `discord_channel_status`**는 legacy Discord 컬럼으로 보이며 Bot은 읽지도 쓰지도 않습니다.
  Discord 상태의 기준은 `recruit_discord_channels`입니다. 실제 사용 여부 확인 후 추후 팀 협의로 정리합니다.

### 자동 재시도 규칙

| `sync_status` / `sync_error` | 자동 재시도 |
| --- | --- |
| `FAILED` + 일반 오류 (`CREATE ...`, `SAVE ...`) | 5분 뒤 재시도 (채널 ID가 없는 경우에 한함) |
| `FAILED` + `MANUAL: ...` (정리 실패, 저장 결과 불명, 마감 기준 없음) | **안 함** |
| `FAILED` + `ABORTED: ...` | **안 함** |
| `FAILED` + `RECHECK: ...` (생성 중 마감 연장 / 글 삭제) | 5분 뒤, 마감이 지났고 글이 있을 때 재시도 |
| `PENDING` 10분 초과 | 중단된 것으로 보고 `MANUAL:`로 변경 |

### `MANUAL:` / `ABORTED:` 행 — 운영자 확인 필요

- `MANUAL:` — 생성 도중 실패했고 정리도 실패했거나, DB 저장 결과를 확인할 수 없는 경우입니다.
  Discord에 공간이 남아 있을 수 있어 중복 생성을 막기 위해 자동 재시도하지 않습니다.
  `sync_error`에 남은 channel ID가 있으면 Discord 서버에서 해당 채널을 확인하고 수동으로 정리하세요.
- `ABORTED:` — 생성 중 모임이 채널 대상이 아니게 되어 만든 채널을 정리한 경우입니다.
  이후 다시 regular로 바뀌어도 **자동으로 재생성하지 않습니다.** 다시 만들려면 사람이 상황을 확인한 뒤
  해당 행을 정리해야 합니다 (수동 recovery 기능은 아직 없습니다).

---

## 16. 연결 구조와 앞으로의 계획

현재 (DB polling):

```text
Backend가 posts / recruits / recruit_members 저장 (모집 중에는 Discord 채널 없음)
        ↓  (Bot이 주기적으로 조회)
deadline_at 도달 → 최종 참여자 조회 → 모임 채널 1개 생성 → recruit_discord_channels에 채널 ID 저장
참여/취소 → members.discord_id로 Discord 권한 부여/회수
Discord 채팅 → 채널 ID로 모임을 찾아 last_activity_at 갱신
7일 비활성 → 모임 채널 경고 → 24시간 뒤 삭제 확인 후 discord_deleted_at 기록
```

Discord 채널 ID는 `recruit_discord_channels.discord_text_channel_id`(varchar)에 저장하고(`str`로 쓰고 `int`로 읽음),
`discord_category_id` / `discord_voice_channel_id`는 새 구조에서 쓰지 않고 NULL로 둡니다 (스키마 변경 없음).
중복 방지는 모임 이름이 아니라 `recruit_id`(PK)와 채널 ID의 연결을 기준으로 합니다.

Backend 담당자와 협의 후 진행할 항목:

1. PUBLIC/PRIVATE 저장 위치 결정 → `DEFAULT_VISIBILITY` 대체
2. 참여/취소가 실제 로그인 사용자(`member_id`)를 쓰도록 변경 (현재 `-1` 고정)
3. 마감(`deadline_at`) 이후 모임 `state`를 자동으로 닫는 처리 (Backend 담당)
4. 필요하면 DB polling을 Backend → Bot 내부 API 호출로 교체

---

## 17. 개발할 때 알아둘 점

### 모임 이름은 식별자가 아닙니다

Discord 채널 이름을 이용해 동일 모임인지 판단하지 않습니다.

실제 서비스에서는:

```text
recruit_id
↕
discord_text_channel_id   (모임 채널 ID)
```

형태로 연결합니다. 채널 주제의 `PlayMate 모임 #<recruit_id>`는 삭제 직전에 "이 채널이 정말 그 모임의 채널인지" 확인하는 표지입니다.

### Discord 메시지 본문은 저장하지 않습니다

상시모임 활성 여부 판단에 필요한 것은:

```text
last_activity_at
```

뿐입니다.

개인 대화 내용을 PlayMate DB에 복사하지 않습니다.

### 삭제된 Discord 공간은 보관하지 않습니다

Discord 서버의 채널 수에는 제한(서버 500개, 카테고리 50개)이 있으므로,
7일 동안 대화가 없다가 24시간 안에도 대화가 없는 모임 채널은 계속 쌓아두지 않고 삭제합니다.

필요한 활동 기록은 향후 PlayMate 서비스의 후기/활동 기록 기능으로 관리하는 것을 전제로 합니다.

---

## 18. 문제 발생 시 확인 순서

### `DISCORD_BOT_TOKEN이 .env에 없습니다.`

`.env` 파일이 프로젝트 루트에 있는지 확인하세요.

```text
playmate-discord-bot/
├─ bot.py
├─ .env        ← 여기
└─ ...
```

### `DISCORD_GUILD_ID가 .env에 없습니다.`

`.env`의 `DISCORD_GUILD_ID`에 테스트 서버 ID를 입력했는지 확인하세요.

### Bot 로그인은 되는데 서버를 못 찾음

- `DISCORD_GUILD_ID`가 맞는지
- Bot이 해당 서버에 초대되어 있는지

확인하세요.

### 권한 변경 / 채널 생성·삭제 실패

테스트 서버에서 Bot 역할의 Discord 권한을 확인하세요.

### 검사 주기가 1분으로 나옴

`.env`에 아래 값이 남아 있는지 확인하세요.

```dotenv
PLAYMATE_TEST_MODE=true
```

운영 방식으로 실행하려면:

```dotenv
PLAYMATE_TEST_MODE=false
```

로 변경하세요.

---

---

## 19. 알림 / 공식 채널 기능 (구조 추가, 일부 미연결)

모임 기능과 분리되어 있습니다. DB 연결 시에만 켜지며, 기존 동기화·lifecycle 작업을 **먼저** 시작한 뒤
별도 task로 시작합니다. 새 기능이 실패해도 모임 기능에는 영향을 주지 않습니다.
DB 연결은 모임 저장소와 따로 씁니다 (`repositories/db.py`).

slash command는 `DISCORD_GUILD_ID` 서버에만 등록됩니다. Bot 초대 scope에 `applications.commands`가 필요합니다.

### `/알림설정` — 구현됨

- `members.discord_id`로 회원을 찾고 `members.external_dm_opt_in`을 보여 줍니다 (본인에게만 보이는 메시지).
- **기본 ON**입니다. `false`(회원이 직접 끔)만 미허용이고, `true`와 `NULL`(아직 선택 안 함)은 허용합니다.
  신규 가입은 Backend가 `true`로 저장합니다 (`database/sql/012_member_dm_default_on.sql`은 컬럼 기본값을 `TRUE`로 바꾸며, 기존 값은 바꾸지 않음).
  버튼 1개로 켜고 끄며 같은 메시지를 갱신합니다.
- 저장에는 **`members.external_dm_opt_in` UPDATE 권한**이 필요합니다. 권한이 없으면 해당 사용자에게
  "알림 설정 저장에 실패했습니다"라고 안내하고 Bot은 계속 동작합니다.

### notifications polling — 구현됨

10초마다 실행되는 별도 루프입니다. `status='PENDING'` 알림을 오래된 순으로 20건씩 가져와
(`idx_notifications_pending` 사용) 한 건씩 처리합니다. 알림이 0건이어도 정상이며,
테이블이 없으면 로그를 한 번 남기고 건너뜁니다.

| 상황 | 결과 |
| --- | --- |
| DM 전송 성공 | `SENT`, `sent_at` 기록 |
| 본인 알림(actor = receiver), 게시글·댓글이 없거나 삭제됨, 알림 꺼짐(`false`), `discord_id` 없음, Discord 사용자 없음 | `SKIPPED`, 사유는 `error_message` |
| DM 전송 실패 (DM 차단 포함) | `retry_count + 1`, `last_attempt_at`·`error_message` 갱신. 총 3회 실패하면 `FAILED`, 그 전에는 `PENDING` 유지 후 60초 뒤 재시도 |

- 상태 변경은 `status='PENDING'`인 행에만 적용됩니다. 시각은 DB의 `CURRENT_TIMESTAMP`를 쓰고,
  `updated_at`은 DB trigger가 갱신하므로 Bot이 직접 바꾸지 않습니다.
- 한 알림의 처리·저장 실패는 로그만 남기고 다음 알림과 루프는 계속됩니다.
- 상수: `config.NOTIFICATION_MAX_ATTEMPTS = 3`, `NOTIFICATION_RETRY_DELAY_SECONDS = 60`, `NOTIFICATION_BATCH_SIZE = 20`.

**제한 사항 (MVP에서 허용)**

- `PROCESSING` 상태가 없어서, DM 전송 성공 직후 `SENT` 저장 전에 Bot이 죽거나 저장이 실패하면
  다음 polling에서 **같은 DM이 다시 갈 수 있습니다.**
- 행을 잠그지 않으므로 Bot은 **한 프로세스로만** 실행해야 합니다.
- Backend가 댓글 저장 시 `notifications`에 행을 넣어야 실제 알림이 생깁니다.

### HOT PLAYMATE — 수동 추천만 구현됨

- `/게시글추천 유형:<게시판|모임|취업> id:<ID>`: `PLAYMATE_ADMIN_ROLE_ID` 역할만 실행할 수 있습니다.
  최소 조건 없이 `PLAYMATE_HOT_CHANNEL_ID` 채널에 게시합니다. 중복 추천을 허용하고 이력은 저장하지 않습니다.
  게시판·취업은 `post_id`, 모임은 `recruit_id`를 입력합니다. 대상 조건은 Backend와 같습니다
  (삭제 제외, 모집글은 게시판에서 제외, 취업 글은 `post_type='CAREER'` + `career_posts`). 작성자는 표시하지 않습니다.
- `🔥 HOT PLAYMATE` Embed에 PlayMate 웹 상세 페이지 링크(제목 링크 + "PlayMate에서 보기")를 붙입니다.
  `PLAYMATE_WEB_BASE_URL`이 비어 있거나 http(s)가 아니면 링크 없이 게시합니다.
  `localhost` 주소는 `PLAYMATE_TEST_MODE=true`일 때만 쓰고, 운영에서는 무시합니다.

  | 유형 | 상세 주소 (프론트 React Router와 같음) |
  | --- | --- |
  | 게시판 | `/board/{board_id}/posts/{post_id}` |
  | 모임 | `/meetup/{recruit_id}` |
  | 취업 | `/career/{reviews\|talk\|lounge\|lab}/{post_id}` (`career_posts.category_code`) |

- **자동 선정 제거**: 좋아요·댓글·참여자 점수로 13:00 / 19:00에 게시하던 자체 HOT 선정과 집계 SQL을 없앴습니다.
  팀원이 별도 HOT 게시판을 만들고 있어, 그 API·DB 구조가 확정되면 연동합니다. 그 전까지 자동 게시는 없습니다.

### 취업게시판 신규 글 자동 공지 — 구현됨 (013 마이그레이션 필요)

- 매일 **18:00 (Asia/Seoul)** 에 `PLAYMATE_CAREER_CHANNEL_ID` 채널(#취업-소식)에 게시합니다. 개인 DM은 보내지 않습니다.
- 대상: 취준 도감(`reviews`)·커리어 연구소(`lab`) 글 중 `post_type='CAREER'`, `post_status='PUBLISHED'`,
  `deleted_at IS NULL`인 글. 커리어 톡톡·현직자 라운지는 제외합니다.
- **하루 최대 5개**, 작성 순서(`created_at`, `post_id`)로 오래된 신규 글부터 공지하고 남은 글은 다음 날 이어서 공지합니다.
  신규 글이 없으면 아무 메시지도 보내지 않습니다.
- 메시지는 글마다 Embed 1개: 게시판 이름, 제목(링크), "PlayMate에서 보기" 링크만 담습니다 (본문·작성자 없음).
  `AllowedMentions.none()`으로 `@everyone`/`@here`/사용자/역할 멘션을 막습니다.
- 공지 이력은 `career_discord_announcements` 테이블(`database/sql/013_career_discord_announcements.sql`)에 저장되어
  Bot을 재시작해도 유지됩니다. **테이블이 없으면 공지하지 않습니다.**

  | 상태 | 의미 |
  | --- | --- |
  | `BASELINE` | 013 적용 시점에 이미 있던 글. 공지하지 않음 (최초 실행 대량 공지 방지) |
  | `PENDING` | Bot이 공지를 선점함. 결과가 저장되지 않은 채 남으면 중복 방지를 위해 자동 재시도하지 않고 로그로 알림 |
  | `SENT` | 공지 완료 (채널·메시지 ID 기록) |
  | `FAILED` | 전송 실패. 다음 실행에서 다시 시도 (총 3회까지) |

- 중복 방지: 글은 `post_id` 기본키로 한 번만 선점되고(`ON CONFLICT ... WHERE status = 'FAILED'`),
  하루 공지 수는 `pg_advisory_xact_lock`을 잡은 한 트랜잭션 안에서 집계·선점하므로 Bot 프로세스가 여러 개여도 넘지 않습니다.
  task는 `feature_tasks`로 한 번만 시작되며, 재연결(`on_ready` 재호출) 때 다시 등록하지 않습니다.
- 안전 처리: `PLAYMATE_WEB_BASE_URL`이 없거나(또는 운영에서 localhost) 채널을 찾지 못하면 선점·전송하지 않고 로그만 남깁니다.
  전송에 실패한 글은 `SENT`로 기록하지 않습니다.
- Bot이 18:00에 꺼져 있었다면 그날 공지는 건너뛰고, 다음 날 18:00에 남은 글을 이어서 공지합니다.
- 필요한 DB 권한: `posts`, `career_posts` SELECT / `career_discord_announcements` SELECT·INSERT·UPDATE.

### 취업 소식 — 구조만

- 채용공고는 신규 즉시 + 마감 D-3 / D-1 13:00 재노출, 면접후기·합격스펙·뉴스는 신규 1회입니다.
- 취업 DB/API가 없어 `UnconnectedCareerContentRepository`(항상 빈 결과)를 쓰며, 이 동안 루프를 시작하지 않습니다.
  스키마가 나오면 `CareerContentRepository`를 구현해 `bot.py`에서 바꿔 끼웁니다.
