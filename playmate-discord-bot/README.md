# PlayMate Discord Bot

PlayMate의 **모임 기능과 Discord를 연결하기 위한 Bot 모듈**입니다.

Discord 기능은 독립적으로 구현·검증되어 있고, 이 브랜치(`feature/13-discord-bot`)에서
**공용 PostgreSQL(`recruit_discord_channels`)과 DB polling 방식으로 연결**했습니다.
Backend / Frontend / Auth 코드는 수정하지 않고, Bot이 DB를 주기적으로 읽어 Discord에 반영합니다.
HOST는 DB(`recruit_members.role='HOST'`)에서 조회해 새 공간에 권한을 주고 비활성 DM을 보냅니다.
기존 공간 HOST 권한 소급·실패 재시도, PUBLIC/PRIVATE 저장 위치, 실제 로그인 사용자 연동은 아직 미완료입니다.
무엇이 구현되었고 무엇이 실환경에서 확인되었는지는 "2. 현재 개발 상태"와
"13. 실환경에서 확인된 내용"을 참고하세요.

> 팀원이 이 저장소를 처음 받아도 구조를 이해하고, 로컬에서 Bot을 실행하고,
> 테스트 코드까지 확인할 수 있도록 정리한 README입니다.

---
## 요약

```text
Discord 기능 구현 / 모듈화 / 실제 Discord 검증     완료
↓
공용 DB 연동 (DB polling, regular 모임만)          구현 완료, 실환경 확인은 일부 (13절 참고)
↓
HOST 조회 연결                                     구현 완료 (새 공간 권한 + 비활성 DM, 실서버 미확인)
↓
HOST 소급/재시도 · PUBLIC/PRIVATE 저장 · 실제 사용자  미완료
```

정책 요약:

- `recruit_mode='regular'` 모임만 Discord 공간을 만들고 관리합니다.
- `recruit_mode='short'` 모임은 Discord 공간을 만들지 않으며, Bot의 모든 경로(생성·권한·활동·삭제)에서 제외됩니다.
- `recruits.state`(OPEN/CLOSED 등)는 **모집 상태**일 뿐이며 Discord 삭제 기준이 아닙니다. `meeting_end`도 사용하지 않습니다.

---

## 1. 이 Bot이 하는 일

PlayMate에서 생성되는 모임마다 Discord 공간을 아래처럼 구성하는 것을 목표로 합니다.

```text
PlayMate 공식 Discord 서버

📁 알고리즘 스터디
├─ # ╔・채팅
└─ 🔊 ╚・음성

📁 LOL 내전
├─ # ╔・채팅
└─ 🔊 ╚・음성
```

모임 하나당 Discord **카테고리 1개**를 만들고, 그 아래에 `╔・채팅` 채널과 `╚・음성` 채널을 생성합니다.

현재 구현된 핵심 기능은 다음과 같습니다.

- PUBLIC / PRIVATE 모임 권한 처리
- 모임 참여자 Discord 권한 부여
- 참여 취소 시 권한 회수
- HOST 권한 부여
- regular 모임 활동 시각 추적 (DB `last_activity_at`)
- 30일 비활성 시 HOST에게 DM 경고
- 경고 후 7일 동안 활동이 없으면 자동 종료
- 유예기간 중 활동이 재개되면 자동 종료 예약 취소
- 삭제 직전 최신 활동 여부를 다시 확인하는 안전장치
- Discord 공간 삭제가 확인된 뒤에만 `discord_deleted_at` 기록

메시지 **본문은 저장하지 않습니다.**  
상시모임의 활동 여부 판단에는 마지막 활동 시각만 사용합니다.

---

## 2. 현재 개발 상태

"구현됨"은 코드가 있고 자동 테스트로 확인했다는 뜻이고, "실환경 확인"은 실제 Discord 서버와
공용 DB로 직접 확인한 항목입니다. 두 가지는 구분해서 읽어야 합니다. 실환경 결과는 13절에 있습니다.

### 구현됨 (자동 테스트로 확인)

- Discord Bot 로그인 / Guild 연결
- regular 모임 카테고리 + 채팅 + 음성 채널 생성 (DB에서 감지, 중복 생성 방지, 실패 복구)
- short 모임은 Discord 공간도, `recruit_discord_channels` 행도 만들지 않음
- PUBLIC / PRIVATE 권한 정책 (코드 유지, 현재 DB 연동은 임시로 PUBLIC)
- 참여자 권한 부여 / 회수 (`members.discord_id` 기반, 카테고리·텍스트·음성 전체 위치 검증)
- 활동 감지 → `last_activity_at` 갱신
- HOST 조회: `recruit_members`(role='HOST', status='JOINED') + `members.discord_id`를 저장소가 직접 조회
  (lifecycle 목록 조회 한 번에 함께 가져옴), 새 공간 생성 직후 HOST 사용 권한 부여
- regular 모임 라이프사이클 (30일 → HOST DM → 7일 유예 → 삭제), 상태는 DB에 저장되어 재시작 후에도 유지
- 실패 복구: 생성 실패 정리, `FAILED` / `MANUAL` / `ABORTED` 구분, row lock, timeout, 취소 안전성

자동 테스트는 두 종류입니다.

- **mock 테스트** (`test_refactor.py`, `test_safety.py`): Discord와 DB에 연결하지 않는 정책·설정 확인.
- **DB 통합 테스트** (`test_db_integration.py`): **실제 일회용 PostgreSQL**을 쓰지만 Discord는
  **가짜 객체**입니다. 실제 Discord 서버와의 동작을 증명하지는 않습니다.

### 실환경에서 확인된 것 / 아직 확인하지 못한 것

실제 Discord 서버와 공용 PostgreSQL로 팀이 확인한 결과이며, 자세한 내용은 13절에 있습니다.

- 확인됨: Bot 로그인과 Gateway 연결, DB polling, regular 모임 채널 자동 생성(재시작 후 중복 없음),
  `members.discord_id` 기반 JOINED 참여자 권한 부여, 실제 메시지로 `last_activity_at` 갱신,
  CANCELED 감지와 PUBLIC 읽기 전용 처리 로직 실행, short 모임에 채널과 DB 행이 생기지 않음.
- 확인하지 못함: 일반 사용자 계정의 실제 쓰기·음성 차단 (테스트 계정이 서버 Owner라서),
  HOST 권한과 HOST DM (DB 조회 연결 후 실서버에서는 아직 확인하지 않음), 그 밖의 아래 미확인 항목.

### 아직 하지 않은 것 (미완료)

- **HOST 권한의 범위**: HOST 권한은 **새 공간을 만든 직후 한 번만** 부여합니다.
  - 이미 만들어진 공간에는 소급 적용하지 않습니다.
  - 그 순간 HOST가 서버에 없거나 Discord 호출이 실패하면 다시 시도하지 않습니다.
    참여자 권한 동기화는 HOST 권한을 덮어쓰지 않도록 HOST 행을 제외하기 때문입니다.
  - HOST 권한 부여는 아직 `regular_lock` 밖에서 실행됩니다.
- **HOST 행이 없는 과거 모임**(Backend가 HOST를 저장하기 전에 만든 모임)은 HOST를 알 수 없어
  경고/유예 예약을 하지 않습니다.
- **PUBLIC / PRIVATE 저장 위치**: 미확정입니다. `config.DEFAULT_VISIBILITY="PUBLIC"` 임시 정책을 사용합니다.
- **실제 로그인 사용자 기반 참여/취소**: Backend가 `member_id=-1`로 고정되어 있어
  `member_id=-1`, `discord_id`가 없거나 숫자가 아닌 회원은 권한 동기화에서 제외합니다.
- Backend → Bot 내부 API 호출 방식은 이번 단계에서 도입하지 않았습니다 (현재는 DB polling).

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
| `bot.py` | Discord Client 생성, 저장소 선택, 이벤트 등록, DB 동기화·라이프사이클 Task 시작 |
| `config.py` | 환경변수와 시간 정책 관리 |
| `services/meeting_space.py` | Discord 모임 공간 생성 / 삭제 |
| `services/permissions.py` | 참여자 / 참여 취소 / HOST 권한 처리 |
| `services/lifecycle.py` | regular 모임 30일 경고 / 7일 유예 / 삭제 정책과 주기 검사 |
| `services/db_sync.py` | DB polling: regular 모임 Discord 생성, 참여자 권한 동기화 |
| `handlers/message_handler.py` | Discord 사용자 활동 감지 및 활동 재개 처리 |
| `repositories/meeting_repository.py` | 저장소 경계. 메모리 구현(DB 설정 없을 때)과 PostgreSQL 구현 |
| `repositories/db.py` | 알림 / 공식 채널 기능 전용 DB 연결 (모임 저장소와 분리) |
| `services/notification_service.py`, `handlers/notification_command_handler.py`, `repositories/notification_repository.py` | `/알림설정`, notifications polling (19절) |
| `services/hot_content_service.py`, `handlers/promotion_command_handler.py`, `repositories/content_repository.py` | HOT PLAYMATE 자동 게시, `/게시글추천` (19절) |
| `services/career_content_service.py`, `repositories/career_content_repository.py` | 취업 소식 포워딩 구조 (19절, 저장소 미연결) |
| `tests/test_refactor.py` | 정책 회귀 테스트 (mock, Discord/DB 연결 없음) |
| `tests/test_safety.py` | 운영 설정, 의존성, `.env` 제외 등 안전성 검증 |
| `tests/test_notification_promotion.py` | 알림 설정 / polling, HOT 점수·선정, `/게시글추천` 권한, 취업 D-3·D-1 판정 (mock) |
| `tests/test_db_integration.py` | 실제 일회용 PostgreSQL + 가짜 Discord 객체로 DB 연동·실패 복구·경쟁 조건 테스트 |

---

## 4. 권한 정책

### PUBLIC 모임

비참여자도 모임의 존재와 대화를 볼 수 있지만 직접 참여하기 전에는 활동할 수 없습니다.

| 사용자 | 채널 보기 | 메시지 읽기 | 메시지 쓰기 | 음성 연결 |
| --- | --- | --- | --- | --- |
| 비참여자 | O | O | X | X |
| 참여자 | O | O | O | O |
| HOST | O | O | O | O |

### PRIVATE 모임

비참여자에게는 모임 공간 자체가 보이지 않습니다.

| 사용자 | 채널 보기 | 메시지 쓰기 | 음성 연결 |
| --- | --- | --- | --- |
| 비참여자 | X | X | X |
| 참여자 | O | O | O |
| HOST | O | O | O |

### HOST 권한

HOST는 참여자와 같은 사용 권한만 받습니다 (확정 정책).

```text
view_channel / read_message_history / send_messages / connect / speak = True
manage_channels = 미부여
manage_messages = 미설정(None)
```

`None`은 이 overwrite에서 허용도 거부도 하지 않고 상위 Discord 권한 설정을 따른다는 뜻입니다.

채널 관리 권한(`manage_channels`)을 주지 않는 이유:
Bot은 세 리소스(카테고리·채팅·음성)가 모두 사라져야 공간 삭제로 판단하고, 일부 삭제는 복구하거나 다시 만들지 않습니다.
HOST가 채팅 채널이나 카테고리만 지우거나 채널을 다른 카테고리로 옮기면 활동 감지가 끊기거나
다른 모임의 활동으로 기록될 수 있습니다.

---

## 5. 모임 라이프사이클

### short 모임

Discord 공간을 **만들지 않으며**, Bot의 어떤 경로(생성 / 권한 / 활동 / 삭제)에서도 다루지 않습니다.
`meeting_end`는 Bot에서 사용하지 않습니다. 모임이 생성된 뒤 `short`로 바뀌어도 Bot은 더 이상 관리하지 않습니다.

### regular 모임

```text
Discord 채팅 활동 → last_activity_at 갱신 (메시지 본문은 저장 안 함)
    ↓
30일 동안 활동 없음
    ↓
HOST에게 DM 경고 → inactivity_warned_at 기록, scheduled_delete_at = 7일 후
    ↓
7일 유예
    ├─ 활동 발생 → inactivity_warned_at / scheduled_delete_at 초기화 (삭제 예약 취소)
    │
    └─ 활동 없음 → 삭제 직전 DB 상태 재확인
                          ↓
                    Discord 공간 삭제 → 삭제가 확인된 뒤 discord_deleted_at 기록
```

- `recruits.state`(모집 상태)는 삭제 기준이 아닙니다.
- 상태 변경은 목적별 **조건부 UPDATE**로만 하므로, 오래된 값이 최신 활동을 덮어쓰지 못합니다.
- **Discord는 카테고리를 삭제해도 하위 채널을 자동 삭제하지 않습니다.**
  그래서 삭제 완료 여부를 카테고리 하나로 판단하지 않고, DB에 저장된 세 리소스
  (`discord_category_id`, `discord_text_channel_id`, `discord_voice_channel_id`)를 각각 삭제·확인합니다.
  `discord_deleted_at`은 **세 리소스 모두 Discord API가 NotFound를 돌려준 경우에만** 기록합니다.
  권한 부여/회수도 같은 원칙으로 **DB에 저장된 세 ID가 기준**입니다: 카테고리 하위 목록이나 캐시에 의존하지 않고,
  캐시에 없으면 API로 조회하며, 채널이 다른 카테고리로 옮겨져 있어도 해당 채널의 overwrite를 부여/회수합니다.
  NotFound는 "그 리소스가 없음", Forbidden/HTTP 오류/타임아웃은 "불명확"이며 불명확하면 완료로 보지 않고 다음 poll에 다시 시도합니다.
  캐시에 없다는 것은 "없음"의 근거가 아닙니다: 캐시에 없으면 `fetch_channel`로 실제 존재를 확인하고,
  Forbidden / HTTP 오류 / 타임아웃 등 불명확한 응답은 "삭제 미완료"로 취급합니다.
  카테고리만 없고 text/voice가 남아 있으면 남은 채널을 계속 정리합니다.
- 일부 채널 삭제가 실패하면 `discord_deleted_at`을 기록하지 않고(나머지 채널은 계속 시도),
  다음 검사 주기 또는 재시작 후 DB 상태를 기준으로 남은 리소스를 다시 정리합니다.
- **regular → short 직렬화 (DB row lock)**: 삭제와 참여/취소 권한 변경 같은 Discord 부수효과는
  `recruits` 행에 `SELECT ... FOR SHARE`를 잡은 트랜잭션 안에서 실행합니다. 모임이 regular이고 Discord 공간이
  SUCCESS/미삭제인지 확인한 뒤 **작업이 끝날 때까지 락을 유지**하므로, Backend의 `recruit_mode='short'` UPDATE는
  그 작업이 끝날 때까지 대기합니다. short가 먼저 commit되었다면 Bot은 락을 얻은 뒤 이를 확인하고 Discord를 건드리지 않습니다.
  타임아웃은 세 가지로 구분됩니다.
  - **DB 락 대기 5초** (`lock_timeout`): Backend가 해당 행을 잡고 있어 락을 못 얻으면 이번 주기는 건너뛰고 다음 주기에 재시도합니다.
  - **Discord 작업 전체 30초** (`DISCORD_LOCK_HOLD_SECONDS`): 락을 얻은 *이후*의 전체 구간 — 채널 조회/fetch, 하위 채널·카테고리 삭제,
    삭제 후 세 리소스의 최종 fetch 확인, `discord_deleted_at` 기록 — 이 하나의 예산입니다. 초과하면 작업을 중단하고
    `discord_deleted_at`을 기록하지 않으며 트랜잭션을 rollback해 락을 풀고, 다음 주기에 재시도합니다 (Bot loop는 계속 동작).
    권한 변경(참여/취소)도 같은 30초 예산을 씁니다.
  - **서버 안전망 60초** (`idle_in_transaction_session_timeout`): 정상 해제 경로가 아니라, Bot이 비정상 종료되었을 때를 위한 최후 수단입니다.
- **취소(cancel) 안전성**: 락 획득은 worker thread에서 진행되므로, 획득 도중 작업이 취소되어도 세션의 소유권이 한 곳으로만 넘어가도록
  했습니다. 취소를 알게 된 쪽이 "포기(abandoned)" 표시를 하고, 이후 worker가 뒤늦게 락을 얻으면 스스로 rollback/close 하며,
  이미 획득을 마친 경우에는 호출자가 해제합니다. 어느 시점에 취소되어도 열린 트랜잭션과 연결이 남지 않습니다.
- `discord_deleted_at`을 기록하는 SQL(`mark_deleted`)도 `recruit_mode='regular'`일 때만 성공합니다.
  0행이면 기록하지 않고 로그만 남기며 Bot은 계속 동작합니다.
- **삭제 기록은 락과 같은 트랜잭션에서만 합니다.** 삭제 lifecycle에서는 `mark_deleted`가 별도 autocommit 연결이 아니라
  `regular_lock`이 잡고 있는 **같은 DB 연결·같은 트랜잭션** 안에서 실행되고, 블록이 오류 없이 끝날 때 한 번 COMMIT됩니다.
  순서: `BEGIN → recruits 행 FOR SHARE → regular/SUCCESS/미삭제 확인 → Discord 삭제 → 세 리소스 NotFound 확인 → mark_deleted(같은 트랜잭션) → COMMIT`.
  timeout·취소·오류가 나면 진행 중인 SQL을 서버에서 취소(`cancel_safe`)하고, worker thread가 그 SQL을 실제로 끝낸 뒤에야
  ROLLBACK/close 하므로, 대기 중이던 UPDATE가 나중에 살아나 COMMIT되는 일이 없습니다.
  SQL에는 남은 시간 예산만큼의 서버 `statement_timeout`도 설정합니다.
  (Discord 공간이 이미 사라졌는데 기록만 실패한 경우는 다음 주기에 "이미 없음"으로 기록됩니다.)
- 삭제 시도 중 들어온 활동은 거부되지 않고 기록되며, 삭제가 실패하면 최신 활동 기준으로 다시 계산됩니다.
- HOST를 알 수 없는 모임(HOST 행이나 `discord_id` 없음)은 경고/유예 예약을 하지 않습니다.
  HOST가 서버에 없거나 DM이 막히면 경고를 저장하지 않고 다음 주기에 다시 시도합니다.

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
PLAYMATE_CAREER_CHANNEL_ID=
PLAYMATE_WEB_BASE_URL=
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
모임 라이프사이클 검사 시작 (실서비스: 하루 1회)

[모임 라이프사이클 검사] YYYY-MM-DD HH:MM:SS
```

라이프사이클 Task는 시작 직후 한 번 실행되고,
그 이후 설정된 주기마다 다시 실행됩니다.

즉 운영 모드에서도 처음 실행 직후 검사 로그가 한 번 출력되는 것은 정상입니다.

---

## 11. "실행했는데 모임이 자동으로 안 생겨요"

`DB_*` 환경변수가 설정되어 있으면 Bot은 약 10초마다(`PLAYMATE_SYNC_INTERVAL_SECONDS`) 공용 DB를 조회해서
**`recruit_mode='regular'`이고 삭제되지 않은 모임**에 Discord 공간을 자동으로 만듭니다
(Backend 호출이 필요하지 않습니다). 만들어지지 않는다면 아래를 확인하세요.

- `DB_*`가 없으면 메모리 저장소로 시작하며 "DB 설정이 없어 메모리 저장소를 사용합니다" 로그가 나옵니다.
- `recruit_mode='short'` 모임은 만들지 않습니다.
- `recruit_discord_channels`에 이미 행이 있으면 건너뜁니다.
  - `FAILED`: 일반 오류는 5분 뒤 자동 재시도합니다.
  - `sync_error`가 `MANUAL:` 또는 `ABORTED:`로 시작하면 **자동 재시도하지 않습니다** (운영자 확인 필요, 아래 15절).
  - `PENDING`이 10분 넘게 남아 있으면 중단된 것으로 보고 `MANUAL:`로 표시합니다.
- Bot 계정이 채널 생성 권한을 가지고 있는지 확인하세요.

---

## 12. 테스트 실행

### 정책 회귀 테스트 (mock)

Discord와 DB에 연결하지 않고, 가짜 객체로 정책과 배선을 확인합니다.

```powershell
python tests/test_refactor.py
```

검증 내용 예시:

- 30일 / 7일 경계값
- PUBLIC / PRIVATE 권한
- 삭제 성공 / 실패
- 활동 재개
- HOST 조회 / DM 오류
- 운영 저장소의 HOST 조회 연결 (`bot.py`가 resolver 없이 만들고, 저장소가 SQL로 조회)
- Bot 메시지 / DM / 미등록 채널 무시
- 중복 Task 시작 방지

현재 **50개 단언을 통과**한 상태입니다.

### 알림 / 공식 채널 정책 테스트 (mock)

```powershell
python tests/test_notification_promotion.py
```

알림 동의 토글과 저장 실패 안내, notifications 테이블·SQL 미연결 시 건너뛰기, 알림 한 건 실패 격리,
HOT 점수·최소 조건·13시/19시 선정, `/게시글추천` 권한, 취업 D-3/D-1 판정을 확인합니다.

### 안전성 테스트

```powershell
python tests/test_safety.py
```

검증 내용:

- `PLAYMATE_TEST_MODE` 기본값
- 운영 검사주기 86,400초
- HOST 권한 설정
- 의존성 버전
- `.env` 배포 제외 등

### DB 통합 테스트 (실제 일회용 PostgreSQL + 가짜 Discord)

DB 동작은 실제 PostgreSQL로 확인하지만 Discord는 가짜 객체입니다. 일회용 PostgreSQL이 필요합니다. 공용 DB로 실행하지 마세요 (테스트는 별도 스키마 `bot_test`를 만들고 지웁니다).

```powershell
docker run -d --name pm-test-pg -e POSTGRES_PASSWORD=test -e POSTGRES_DB=pm -p 55432:5432 postgres:16
$env:PLAYMATE_TEST_PG_DSN = "host=127.0.0.1 port=55432 user=postgres password=test dbname=pm"
python tests/test_db_integration.py
```

`PLAYMATE_TEST_PG_DSN`이 없으면 건너뜁니다. 검증 내용: regular만 생성 / 중복 생성 방지 / 응답 유실·정리 실패·ID 저장 실패 복구 /
참여·취소 권한 전체 위치 검증 / 활동·경고·삭제 경쟁 조건 / DB 장애 후 loop 유지 / regular→short 경쟁.

---

## 13. 실환경에서 확인된 내용

### DB 연동 이후: 실제 Discord 서버 + 공용 PostgreSQL (팀 확인 결과)

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
| `FAILED` + 일반 오류 (`CREATE ...`, `SAVE ...`) | 5분 뒤 재시도 (Discord ID가 없는 경우에 한함) |
| `FAILED` + `MANUAL: ...` | **안 함** |
| `FAILED` + `ABORTED: ...` | **안 함** |
| `PENDING` 10분 초과 | 중단된 것으로 보고 `MANUAL:`로 변경 |

### `MANUAL:` / `ABORTED:` 행 — 운영자 확인 필요

- `MANUAL:` — 생성 도중 실패했고 정리도 실패했거나, DB 저장 결과를 확인할 수 없는 경우입니다.
  Discord에 공간이 남아 있을 수 있어 중복 생성을 막기 위해 자동 재시도하지 않습니다.
  `sync_error`에 남은 category/channel ID가 있으면 Discord 서버에서 해당 리소스를 확인하고 수동으로 정리하세요.
- `ABORTED:` — 생성 중 모임이 regular가 아니게 되어(예: short로 수정) 만든 공간을 정리한 경우입니다.
  이후 다시 regular로 바뀌어도 **자동으로 재생성하지 않습니다.** 다시 만들려면 사람이 상황을 확인한 뒤
  해당 행을 정리해야 합니다 (수동 recovery 기능은 아직 없습니다).

---

## 16. 연결 구조와 앞으로의 계획

현재 (DB polling, Backend 수정 없음):

```text
Backend가 posts / recruits / recruit_members 저장
        ↓  (Bot이 주기적으로 조회)
regular 모임 → Discord 카테고리/채팅/음성 생성 → recruit_discord_channels에 ID 저장
참여/취소 → members.discord_id로 Discord 권한 부여/회수
Discord 채팅 → last_activity_at 갱신
30일 비활성 → HOST DM → 7일 유예 → 삭제 확인 후 discord_deleted_at 기록
```

Discord resource ID는 `recruit_discord_channels`에 `varchar`로 저장하고(`str`로 쓰고 `int`로 읽음),
중복 방지는 모임 이름이 아니라 `recruit_id`(PK)와 Discord resource ID의 연결을 기준으로 합니다.

Backend 담당자와 협의 후 진행할 항목:

1. 기존 공간 HOST 권한 소급, HOST 권한 실패 재시도, HOST 권한 부여를 `regular_lock` 안에서 처리
2. PUBLIC/PRIVATE 저장 위치 결정 → `DEFAULT_VISIBILITY` 대체
3. 참여/취소가 실제 로그인 사용자(`member_id`)를 쓰도록 변경
4. 필요하면 DB polling을 Backend → Bot 내부 API 호출로 교체

---

## 17. 개발할 때 알아둘 점

### 모임 이름은 식별자가 아닙니다

Discord 카테고리 이름을 이용해 동일 모임인지 판단하지 않습니다.

실제 서비스에서는:

```text
recruit_id
↕
discord_category_id
discord_text_channel_id
discord_voice_channel_id
```

형태로 연결할 예정입니다.

### Discord 메시지 본문은 저장하지 않습니다

상시모임 활성 여부 판단에 필요한 것은:

```text
last_activity_at
```

뿐입니다.

개인 대화 내용을 PlayMate DB에 복사하지 않습니다.

### 삭제된 Discord 공간은 보관하지 않습니다

Discord 서버의 카테고리 수에는 제한이 있으므로,
비활성으로 삭제 대상이 된 regular 모임은 Discord 공간을 계속 쌓아두지 않고 삭제합니다.

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
- `true`만 알림 허용, `false`/`NULL`은 미허용입니다. 버튼 1개로 켜고 끄며 같은 메시지를 갱신합니다.
- 저장에는 **`members.external_dm_opt_in` UPDATE 권한**이 필요합니다. 권한이 없으면 해당 사용자에게
  "알림 설정 저장에 실패했습니다"라고 안내하고 Bot은 계속 동작합니다.

### notifications polling — 구현됨

10초마다 실행되는 별도 루프입니다. `status='PENDING'` 알림을 오래된 순으로 20건씩 가져와
(`idx_notifications_pending` 사용) 한 건씩 처리합니다. 알림이 0건이어도 정상이며,
테이블이 없으면 로그를 한 번 남기고 건너뜁니다.

| 상황 | 결과 |
| --- | --- |
| DM 전송 성공 | `SENT`, `sent_at` 기록 |
| 본인 알림(actor = receiver), 게시글·댓글이 없거나 삭제됨, 미동의(`false`/`NULL`), `discord_id` 없음, Discord 사용자 없음 | `SKIPPED`, 사유는 `error_message` |
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

### HOT PLAYMATE — 수동 추천 구현됨, 자동 선정은 좋아요 스키마 대기

- `/게시글추천 유형:<게시판|모임> id:<ID>`: `PLAYMATE_ADMIN_ROLE_ID` 역할만 실행할 수 있습니다.
  최소 조건 없이 `PLAYMATE_HOT_CHANNEL_ID` 채널에 게시합니다. 중복 추천을 허용하고 이력은 저장하지 않습니다.
  게시판은 `post_id`, 모임은 `recruit_id`를 입력합니다.
- 자동 게시: 매일 13:00 / 19:00 (KST), 최근 24시간 후보.
  게시판 = 좋아요×3 + 댓글×2 (좋아요 ≥ 2 AND 댓글 ≥ 2), 모임 = 좋아요×3 + 참여 멤버×4 (좋아요 ≥ 2 AND 멤버 ≥ 2).
  19시 1위가 13시 게시물과 같으면 2위를 게시합니다. 13시 기록은 메모리에만 있습니다.
- **좋아요 스키마가 아직 없어 자동 후보는 0건이며 게시하지 않는 것이 정상입니다.**
  연결할 때 `PostgresContentRepository.list_*_candidates`가 `HotCandidate`를 돌려주게 구현합니다.
- 자동/수동 모두 같은 `🔥 HOT PLAYMATE` 형식이며, 상세 링크 버튼은 프론트 route 확정 후 추가합니다.

### 취업 소식 — 구조만

- 채용공고는 신규 즉시 + 마감 D-3 / D-1 13:00 재노출, 면접후기·합격스펙·뉴스는 신규 1회입니다.
- 취업 DB/API가 없어 `UnconnectedCareerContentRepository`(항상 빈 결과)를 쓰며, 이 동안 루프를 시작하지 않습니다.
  스키마가 나오면 `CareerContentRepository`를 구현해 `bot.py`에서 바꿔 끼웁니다.
