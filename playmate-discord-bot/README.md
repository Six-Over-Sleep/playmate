# PlayMate Discord Bot

PlayMate의 **모임 기능과 Discord를 연결하기 위한 Bot 모듈**입니다.

현재 버전은 Discord 기능 자체를 독립적으로 구현하고 검증한 단계이며,  
아직 PlayMate 모임 프론트엔드/백엔드 및 PostgreSQL과는 연결하지 않았습니다.

> 팀원이 이 저장소를 처음 받아도 구조를 이해하고, 로컬에서 Bot을 실행하고,
> 테스트 코드까지 확인할 수 있도록 정리한 README입니다.

---
## 요약

현재 PlayMate Discord Bot은 Discord 기능 자체에 대한 구현과 검증을 완료한 상태입니다.

```text
Discord 기능 구현             완료
↓
모듈화                       완료
↓
운영 안전성 수정              완료
↓
실제 Discord 통합 재검증      완료
↓
모임 FE/BE 구현               대기
↓
PostgreSQL / API 연동          예정
```

모임 백엔드가 준비되면 현재 서비스와 Repository 경계를 이용해
실제 PlayMate 데이터와 연결하는 단계로 넘어갑니다.

---

## 1. 이 Bot이 하는 일

PlayMate에서 생성되는 모임마다 Discord 공간을 아래처럼 구성하는 것을 목표로 합니다.

```text
PlayMate 공식 Discord 서버

📁 알고리즘 스터디
├─ # 채팅
└─ 🔊 음성

📁 LOL 내전
├─ # 채팅
└─ 🔊 음성
```

모임 하나당 Discord **카테고리 1개**를 만들고, 그 아래에 `채팅` 채널과 `음성` 채널을 생성합니다.

현재 구현된 핵심 기능은 다음과 같습니다.

- PUBLIC / PRIVATE 모임 권한 처리
- 모임 참여자 Discord 권한 부여
- 참여 취소 시 권한 회수
- HOST 권한 부여
- 일회성 모임 종료 후 24시간 뒤 Discord 공간 자동 삭제
- 상시모임 활동 시각 추적
- 30일 비활성 시 HOST에게 DM 경고
- 경고 후 7일 동안 활동이 없으면 자동 종료
- 유예기간 중 활동이 재개되면 자동 종료 예약 취소
- 삭제 직전 최신 활동 여부를 다시 확인하는 안전장치
- Discord 공간 삭제 후 삭제 시각 기록

메시지 **본문은 저장하지 않습니다.**  
상시모임의 활동 여부 판단에는 마지막 활동 시각만 사용합니다.

---

## 2. 현재 개발 상태

### 완료

- Discord Bot 로그인 / Guild 연결
- 모임별 카테고리 + 채팅 + 음성 채널 생성
- PUBLIC / PRIVATE 권한 정책
- 참여자 권한 부여 / 회수
- HOST 권한
- 일회성 모임 라이프사이클
- 상시모임 라이프사이클
- 단일 `bot.py` 구조를 역할별 모듈로 리팩터링
- 운영 안전성 설정
- 실제 Discord 테스트 서버 통합 재검증

실제 Discord 테스트 서버에서 다음 7단계를 모두 다시 검증했습니다.

| 단계 | 검증 내용 | 결과 |
| --- | --- | --- |
| 1 | 모임 공간 생성 | PASS |
| 2 | PUBLIC 비참여자: 읽기 가능 / 쓰기·음성 연결 불가 | PASS |
| 3 | PRIVATE 비참여자: 전체 숨김 | PASS |
| 4 | 참여자 권한 부여 | PASS |
| 5 | 참여 취소 권한 회수 | PASS |
| 6 | HOST: `manage_channels=True`, `manage_messages=None` | PASS |
| 7 | 모임 공간 삭제 및 삭제 후 Discord API 404 확인 | PASS |

### 아직 하지 않은 것

현재는 **Discord 기능 단독 검증 단계**입니다.

다음 항목은 모임 프론트엔드/백엔드 구현이 진행된 뒤 연결할 예정입니다.

- PlayMate 모임 생성 API ↔ Discord 공간 생성 연결
- 참여 / 참여 취소 API ↔ Discord 권한 연결
- PostgreSQL 연결
- `members.discord_user_id` 연동
- `recruit_id ↔ Discord resource ID` 영속화
- 실제 DB 기반 라이프사이클 조회
- 서비스 환경의 트랜잭션 / 동시성 처리

따라서 현재 `repository`는 PostgreSQL 구현체가 아니라 **메모리 기반 임시 구현체**입니다.

---

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
│  └─ lifecycle.py
│
├─ handlers/
│  ├─ __init__.py
│  └─ message_handler.py
│
├─ repositories/
│  ├─ __init__.py
│  └─ meeting_repository.py
│
├─ tests/
│  ├─ fixtures/
│  │  └─ original_bot.py
│  ├─ test_refactor.py
│  └─ test_safety.py
│
├─ .env.example
├─ .gitignore
├─ requirements.txt
└─ REFACTORING.md
```

### 파일별 역할

| 파일 | 역할 |
| --- | --- |
| `bot.py` | Discord Client 생성, 의존성 연결, 이벤트 등록, 라이프사이클 Task 시작 |
| `config.py` | 환경변수와 시간 정책 관리 |
| `services/meeting_space.py` | Discord 모임 공간 생성 / 삭제 |
| `services/permissions.py` | 참여자 / 참여 취소 / HOST 권한 처리 |
| `services/lifecycle.py` | 일회성·상시모임 종료 정책과 주기 검사 |
| `handlers/message_handler.py` | Discord 사용자 활동 감지 및 활동 재개 처리 |
| `repositories/meeting_repository.py` | 현재 메모리 저장소. 향후 PostgreSQL 구현으로 교체할 경계 |
| `tests/test_refactor.py` | 리팩터링 전후 동작 비교 회귀 테스트 |
| `tests/test_safety.py` | 운영 설정, 의존성, `.env` 제외 등 안전성 검증 |
| `REFACTORING.md` | 리팩터링 배경과 상세 변경 내역 |

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

현재 HOST에게는 다음 권한을 부여합니다.

```text
manage_channels = True
manage_messages = 미설정(None)
```

`manage_messages=False`가 아닙니다.

`None`은 해당 권한을 이 overwrite에서 명시적으로 허용하거나 거부하지 않고,
상위 Discord 권한 설정을 따르게 한다는 의미입니다.

`manage_channels=True`는 현재 정책이며, 실제 서비스 적용 전에 팀에서 최종 논의할 수 있습니다.

---

## 5. 모임 라이프사이클

### 일회성 모임

```text
모임 end_at 도달
        ↓
24시간 유예
        ↓
Discord 채널 / 카테고리 삭제
        ↓
discord_deleted_at 기록
```

종료 즉시 삭제하지 않고 24시간의 유예시간을 둡니다.

### 상시모임

```text
마지막 활동
    ↓
30일 동안 활동 없음
    ↓
HOST에게 DM 경고
    ↓
7일 유예
    ├─ 활동 발생 → 자동 종료 예약 취소
    │
    └─ 활동 없음 → 삭제 직전 최신 활동 재확인
                          ↓
                    Discord 공간 삭제
```

삭제 직전에도 `last_activity_at`과 `inactivity_warned_at`을 다시 비교하여,
경고 이후 활동이 있었다면 삭제를 취소합니다.

> 현재 메모리 저장소 단계의 방어 로직이며,
> PostgreSQL 연결 시에는 조건부 UPDATE / Transaction 등의 방식으로
> 동시성까지 보강할 예정입니다.

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
```

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
```

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
모임 라이프사이클 검사 시작 (실서비스: 하루 1회)

[모임 라이프사이클 검사] YYYY-MM-DD HH:MM:SS
```

라이프사이클 Task는 시작 직후 한 번 실행되고,
그 이후 설정된 주기마다 다시 실행됩니다.

즉 운영 모드에서도 처음 실행 직후 검사 로그가 한 번 출력되는 것은 정상입니다.

---

## 11. "실행했는데 모임이 자동으로 안 생겨요"

현재는 정상입니다.

지금 `bot.py`는 Discord에 로그인하고 라이프사이클 Task를 실행하지만,
**PlayMate 모임 백엔드 API와 아직 연결되어 있지 않습니다.**

또한 현재 기본 Repository에는 실제 서비스 모임 데이터가 들어있지 않습니다.

따라서:

```text
python bot.py
```

만 실행한다고 새로운 모임 카테고리가 자동 생성되지는 않습니다.

모임 생성 / 참여 / 취소 기능은 향후 PlayMate 백엔드 이벤트에서
각 Discord 서비스 함수를 호출하도록 연결할 예정입니다.

---

## 12. 테스트 실행

### 리팩터링 회귀 테스트

```powershell
python tests/test_refactor.py
```

검증 내용 예시:

- 리팩터링 전후 핵심 함수 실행 로직 비교
- 24시간 / 30일 / 7일 경계값
- PUBLIC / PRIVATE 권한
- 삭제 성공 / 실패
- 활동 재개
- HOST 조회 / DM 오류
- Bot 메시지 / DM / 미등록 채널 무시
- 중복 Task 시작 방지

현재 **45개 동등성 단언을 통과**한 상태입니다.

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

---

## 13. 실제 Discord에서 검증된 내용

리팩터링 후 실제 테스트 서버에서도 다음을 재검증했습니다.

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

## 15. 현재 Repository의 한계

`repositories/meeting_repository.py`는 현재
**InMemoryMeetingRepository**를 사용합니다.

즉:

- 프로세스가 종료되면 데이터가 사라집니다.
- PostgreSQL과 연결되어 있지 않습니다.
- 다중 프로세스 환경의 동시성을 보장하지 않습니다.
- DB Transaction / Lock이 없습니다.

현재 목적은 Discord 기능을 다른 코드와 분리하고,
향후 실제 DB 구현체로 교체할 수 있는 경계를 만드는 것입니다.

---

## 16. 앞으로 연결할 구조

향후 PlayMate 모임 백엔드가 준비되면 다음 흐름으로 연결할 예정입니다.

```text
PlayMate 모임 생성
        ↓
recruit 저장
        ↓
Discord 모임 공간 생성
        ↓
Discord resource ID 저장
```

참여:

```text
PlayMate 참여
    ↓
recruit_members 갱신
    ↓
members.discord_user_id 조회
    ↓
Discord 참여 권한 부여
```

참여 취소:

```text
PlayMate 참여 취소
    ↓
Discord 권한 회수
```

라이프사이클:

```text
PostgreSQL
    ↓
종료 대상 / 비활성 모임 조회
    ↓
Discord Bot
    ↓
DM / 자동 종료 / 삭제
    ↓
DB 상태 갱신
```

실서비스 중복 방지는 **모임 이름이 아니라 `recruit_id`와 Discord resource ID의 연결**을 기준으로 구현할 예정입니다.

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

### 종료된 Discord 공간은 보관하지 않습니다

Discord 서버의 카테고리 수에는 제한이 있으므로,
종료된 모임은 Discord 공간을 계속 쌓아두지 않고 삭제하는 방향입니다.

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

## 19. 관련 문서

더 자세한 리팩터링 내용과 검증 기준은 아래 파일에서 확인할 수 있습니다.

```text
REFACTORING.md
```

이 README는 **팀원이 프로젝트를 이해하고 실행하기 위한 문서**이고,
`REFACTORING.md`는 **왜 코드를 분리했고 어떤 동작을 보존했는지 확인하기 위한 개발 기록**입니다.