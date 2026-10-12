# PlayMate Discord Bot 설계 정리

> ****보안 주의****

>

> 현재 대화에 Discord Bot Token이 노출되었으므로 ****기존 Token은 폐기하고 Discord Developer Portal에서 즉시 재발급하는 것을 권장****합니다.

> 문서에는 실제 Token을 기록하지 않습니다.

>

> ```env

> DISCORD_BOT_TOKEN=\<REDACTED>

> DISCORD_GUILD_ID=1558398924660801556

> ```

---

## 1. 목표

PlayMate의 ****모임 기능과 Discord를 자동 연동하는 Bot****을 만든다.

핵심 목표:

- PlayMate에서 모임이 생성되면 Discord에 모임 공간 자동 생성

- PUBLIC / PRIVATE에 따라 권한 자동 설정

- 모임 참여 시 Discord 채널 권한 자동 부여

- 참여 취소 시 권한 자동 회수

- 모임 종료 시 Discord 채널 자동 정리

- 이후 음성채널 생성 여부 선택 기능으로 확장

> ****핵심 정의:**** PlayMate의 모임 상태와 Discord의 채널·사용자 권한을 자동으로 동기화하는 Bot

---

## 2. Discord 서버 구조

### 최종 방향

모임 하나당 Discord 카테고리 하나를 만들고, 그 안에 채팅/음성 채널을 둔다.

```text

PlayMate 공식 Discord 서버

📁 알고리즘 스터디

├─ # 채팅

└─ 🔊 음성

📁 LOL 내전

├─ # 채팅

└─ 🔊 음성

📁 점심 마라탕

├─ # 채팅

└─ 🔊 음성

```

### 이 구조를 선택한 이유

![alt text]\(image.png)  

처음에는 하나의 `모임` 카테고리 아래에 모든 텍스트/음성 채널을 만들었지만, Discord에서 채널 종류별로 묶여 보여 같은 모임의 채팅과 음성이 붙어 보이지 않았다.

모임별 카테고리 구조의 장점:

- 모임별 공간이 명확함

- 채팅/음성을 한눈에 찾기 쉬움

- PUBLIC / PRIVATE 권한을 카테고리 단위로 관리하기 쉬움

- 종료 시 모임 단위로 정리하기 쉬움

---

## 3. 모임 생성 시 Bot 동작

```text

PlayMate 모임 생성

        ↓

Discord Bot 호출

        ↓

모임 이름으로 카테고리 생성

        ↓

# 채팅 생성

        ↓

🔊 음성 생성

        ↓

PUBLIC / PRIVATE 권한 적용

```

예:

```text

PlayMate 모임명 = 알고리즘 스터디

Discord

📁 알고리즘 스터디

├─ # 채팅

└─ 🔊 음성

```

---

## 4. PUBLIC / PRIVATE 권한 정책

### PUBLIC 모임

PUBLIC은 누구나 활동할 수 있다는 뜻이 아니라, ****참여 전에도 모임의 활동성과 분위기를 확인할 수 있게 하는 것****이 목적이다.

| 상태 | PUBLIC 텍스트 | PUBLIC 음성 |

|---|---|---|

| 비참여자 | 보기 O / 쓰기 X | 보기 O / 접속 X |

| 참여자 | 보기 O / 쓰기 O | 보기 O / 접속 O |

| 모임장 | 관리 가능 | 관리 가능 |

PUBLIC 비참여자에게 음성 채널이 보이면서 자물쇠가 표시되는 것은 정상이다. 채널 존재는 보이지만 입장은 불가능하다.

### PRIVATE 모임

| 상태 | PRIVATE 텍스트 | PRIVATE 음성 |

|---|---|---|

| 비참여자 | 안 보임 | 안 보임 |

| 참여자 | 보기 O / 쓰기 O | 보기 O / 접속 O |

| 모임장 | 관리 가능 | 관리 가능 |

### 최종 권한표

| 상태 | PUBLIC 텍스트 | PUBLIC 음성 | PRIVATE 텍스트 | PRIVATE 음성 |

|---|---|---|---|---|

| 비참여자 | 보기 O / 쓰기 X | 보기 O / 접속 X | 안 보임 | 안 보임 |

| 참여자 | 보기/쓰기 O | 보기/접속 O | 보기/쓰기 O | 보기/접속 O |

| 모임장 | 관리 가능 | 관리 가능 | 관리 가능 | 관리 가능 |

### HOST(모임장) 권한

현재 테스트 단계에서는 HOST에게 일반 참여자 권한에 더해 채널 관리 권한을 부여한다.

| 기능 | HOST |

|---|---|

| 채널 보기 | O |

| 메시지 읽기 | O |

| 메시지 작성 | O |

| 음성 채널 접속 | O |

| 음성 발언 | O |

| 채널 관리 (`manage_channels`) | O |

| 메시지 관리 (`manage_messages`) | X |

현재 테스트 코드:

```python

host_overwrite = discord.PermissionOverwrite(

    view_channel=True,

    read_message_history=True,

    send_messages=True,

    connect=True,

    speak=True,

    manage_channels=True,

)

```

`manage_messages=True`는 현재 적용하지 않는다.

HOST 권한 테스트 결과 다음 기능이 정상 동작함을 확인했다.

- PUBLIC 모임 접근 가능

- PRIVATE 모임 접근 가능

- 텍스트 채널 사용 가능

- 음성 채널 사용 가능

- 채널명 변경 가능

- 추가 채널 생성 가능

---

## 5. 모임 참여 / 취소 흐름

### 참여

```text

PlayMate

[참여하기]

      ↓

recruit_members

status = JOINED

      ↓

Bot

      ↓

members.discord_user_id 조회

      ↓

텍스트 작성 권한 부여

음성 접속 권한 부여

```

PUBLIC:

- 참여 전: 읽기만 가능 / 음성 접속 불가

- 참여 후: 채팅 작성 및 음성 접속 가능

PRIVATE:

- 참여 전: 카테고리 자체가 안 보임

- 참여 후: 카테고리와 채널 접근 가능

### 참여 취소

```text

PlayMate

[참여 취소]

      ↓

recruit_members

JOINED → CANCELED

      ↓

Bot

```

PUBLIC:

- 채팅 쓰기 권한 제거

- 음성 접속 권한 제거

- 읽기 권한은 유지

PRIVATE:

- 카테고리 및 채널 접근권한 제거

---

## 6. 모임 종료 시 처리

### 종료 트리거

모임 종료는 사용자가 직접 종료하는 경우뿐 아니라, 모임 유형에 따라 시스템이 자동으로 판단할 수 있어야 한다.

현재 방향은 다음 세 가지 종료 경로를 사용한다.

| 종료 경로 | 기준 | 처리 |
|---|---|---|
| HOST 직접 종료 | PlayMate에서 `모임 종료` 실행 | 즉시 Discord 공간 삭제 |
| 일회성 모임 자동 종료 | 모임 종료시각(`end_at`) + 24시간 | Discord 공간 자동 삭제 |
| 상시 모임 비활성 종료 | 장기간 활동 없음 → HOST 경고 → 유예기간 동안 활동 없음 | Discord 공간 자동 삭제 |

> 모집 마감과 모임 종료는 다른 상태로 취급한다. 모집이 마감되어도 실제 모임 활동이 계속될 수 있으므로 `RECRUITMENT_CLOSED`와 `MEETING_CLOSED`를 동일하게 처리하지 않는다.

### 일회성 모임 자동 종료

실제 테스트 결과:

- `end_at = 현재 시각 - 25시간`으로 테스트 데이터를 설정
- `end_at + 24시간`이 현재 시각보다 과거인지 주기 검사에서 확인
- 자동 종료 대상으로 정상 판별
- 텍스트 채널 삭제 성공
- 음성 채널 삭제 성공
- 모임 카테고리 삭제 성공

따라서 **일회성 모임의 종료시각 + 24시간 이후 Discord 공간 자동 삭제 흐름을 실제 테스트 서버에서 검증 완료**했다.


일회성 모임은 설정된 종료시각에 즉시 Discord 공간을 삭제하지 않고 **24시간의 유예시간**을 둔다.

예:

```text
모임 일정
2026-10-17 12:00 ~ 14:00

14:00
→ 모임 일정 종료

다음 날 14:00
→ Discord 공간 자동 삭제
```

최종 삭제 기준:

```text
delete_at = end_at + 24시간
```

이렇게 하면 모임 종료 직후 마지막 인사, 사진 공유, 간단한 정리 시간을 보장하면서도 종료된 카테고리가 장기간 서버에 남는 것을 방지할 수 있다.

### 상시 모임 비활성 종료

상시 모임은 명시적인 `end_at`이 없으므로 Discord 활동을 기준으로 비활성 상태를 판단하는 방향을 검토한다.

현재 제안 정책:

```text
30일 동안 Discord 활동 없음
        ↓
HOST에게 비활성 경고 DM
        ↓
7일 유예
        ↓
활동 발생
→ 자동 종료 예약 취소

계속 활동 없음
→ 모임 자동 종료
→ Discord 공간 삭제
```

비활성 기간(30일)과 유예기간(7일)은 운영 정책에 따라 변경할 수 있도록 설정값으로 관리한다.

비활성 검사 주기는 다음과 같이 운영한다.

- 테스트 단계: 1분마다 검사하여 동작을 빠르게 검증
- 실서비스: 하루 1회 검사

비활성 기준이 30일이고 경고 후 유예기간이 7일이므로 실서비스에서 분/시간 단위 정밀도는 필요하지 않다. 하루 1회 검사로 불필요한 반복 호출과 로그를 줄인다.

### Discord 공간 삭제

Discord 서버의 카테고리 수 제한을 고려하여 **종료된 모임의 Discord 공간은 별도로 보관하지 않고 삭제**한다.

```text
모임 종료 확정
        ↓
recruits 상태 종료 처리
        ↓
Discord Bot 호출
        ↓
텍스트/음성 등 하위 채널 삭제
        ↓
모임 카테고리 삭제
        ↓
recruit_discord_channels.discord_deleted_at 기록
```

실서비스 구현에서는 카테고리 삭제 동작에 하위 채널 정리를 의존하지 않고, 하위 채널을 먼저 명시적으로 삭제한 뒤 카테고리를 삭제한다.

### Discord 메시지 보관 정책

Discord 채팅 메시지 본문은 PlayMate DB에 별도로 저장하지 않는다.

Discord 메시지 전체를 저장하면 다음과 같은 추가 문제가 발생한다.

- 메시지 저장량 증가
- 개인정보 및 메시지 보관 정책 필요
- Discord에서 수정/삭제된 메시지와의 동기화 필요
- Discord와 PlayMate 간 메시지 상태 관리 복잡도 증가

현재 PlayMate의 핵심 목적은 Discord 채팅 아카이브가 아니므로 MVP에서는 메시지 자체를 저장하지 않는다.

대신 DB에는 다음과 같은 **Discord 연동 메타데이터와 삭제 이력**만 보존한다.

- 어떤 PlayMate 모임과 연결되었는지
- 생성된 Discord 카테고리/채널 ID
- 공개 범위
- 연동 성공/실패 상태
- 마지막 Discord 활동 시각
- 비활성 경고 시각
- 자동 종료 예정 시각
- Discord 공간이 실제 삭제된 시각

향후 모임 활동을 서비스 내부에 남길 필요가 생기면 Discord 메시지 전체를 복제하기보다 PlayMate 내부의 후기/활동 기록 기능으로 확장하는 방향을 우선 검토한다.

---

## 7. 음성채널 생성 옵션

1차 구현:

```text

모임 생성

→ 텍스트 채널 O

→ 음성 채널 O

```

안정되면:

```text

☑ 음성채널 사용

```

옵션 추가를 고려한다.

DB 제안:

```text

voice_enabled BOOLEAN DEFAULT TRUE

```

---

## 8. ERD / DB 추가사항

### 8-1. `members`에 Discord 사용자 ID 추가

```text

members

────────────────────────────

member_id              PK

...

discord_user_id        VARCHAR(...) UNIQUE NULL

discord_linked_at      TIMESTAMP NULL

```

### `discord_user_id`

PlayMate 회원과 Discord 계정을 연결하는 핵심 값.

```text

PlayMate

member_id = 15

Discord

discord_user_id = 123456789012345678

```

OAuth 로그인 성공 시 로그인 담당 파트에서 저장:

```text

Discord 로그인

      ↓

Discord 사용자 ID 획득

      ↓

members.discord_user_id 저장

```

Bot은 이 값을 읽어 실제 Discord 사용자에게 권한을 부여한다.

---

### 8-2. `recruit_discord_channels` 신규 1:1 테이블 제안

```text

recruit_discord_channels

──────────────────────────────────

recruit_id                  PK / FK

discord_category_id         VARCHAR

discord_text_channel_id     VARCHAR

discord_voice_channel_id    VARCHAR NULL

visibility                  VARCHAR

voice_enabled               BOOLEAN

sync_status                 VARCHAR

sync_error                  TEXT NULL

synced_at                   TIMESTAMP NULL

created_at                  TIMESTAMP

updated_at                  TIMESTAMP

```

관계:

```text

recruits

   │

   │ 1 : 0..1

   ▼

recruit_discord_channels

```

### 별도 테이블로 분리하는 이유

`recruits`는 PlayMate 핵심 모임 데이터:

```text

모집 인원

일정

장소

상태

카테고리

...

```

`recruit_discord_channels`는 외부 Discord 연동 상태:

```text

discord_category_id

discord_text_channel_id

discord_voice_channel_id

sync_status

sync_error

...

```

따라서 핵심 도메인과 외부 플랫폼 연동 상태를 분리해 관리하는 것이 깔끔하다.

---

## 9. 컬럼 설명

### `recruit_id`

어떤 PlayMate 모임과 연결된 Discord 공간인지 식별한다. PK/FK로 두면 한 모임당 Discord 연동 레코드를 하나만 관리할 수 있다.

### `discord_category_id`

모임 전용 Discord 카테고리 ID. 현재 구조에서는 필수.

### `discord_text_channel_id`

`#채팅` 채널 ID.

### `discord_voice_channel_id`

음성 채널 ID. 향후 `voice_enabled = FALSE`를 지원할 수 있으므로 NULL 허용 권장.

### `visibility`

```text

PUBLIC

PRIVATE

```

### `voice_enabled`

```text

TRUE

FALSE

```

### `sync_status`

```text

PENDING

SUCCESS

FAILED

```

Discord API 연동 실패를 추적하기 위해 필요.

### `sync_error`

실패 원인 기록.

예:

```text

Missing Permissions

Unknown Member

Discord API timeout

```

### `synced_at`

마지막 정상 동기화 시각.

### `last_activity_at`

해당 모임 Discord 공간에서 마지막 활동이 발생한 시각.

상시 모임의 장기 비활성 여부를 판단할 때 사용한다. Discord 메시지 본문 전체를 저장하지 않고 마지막 활동 시각만 갱신한다.

### `inactivity_warned_at`

장기 비활성 상태가 감지되어 HOST에게 자동 종료 경고를 보낸 시각.

경고 전에는 `NULL`, 경고 전송 후에는 해당 시각을 저장한다.

### `scheduled_delete_at`

자동 종료가 예정된 시각.

일회성 모임의 경우 기본적으로:

```text
scheduled_delete_at = end_at + 24시간
```

상시 모임의 경우 비활성 경고 후 유예기간이 끝나는 시각을 저장한다.

활동이 다시 발생해 자동 종료가 취소되면 `NULL`로 되돌린다.

### `discord_deleted_at`

모임 종료에 따라 Discord 카테고리와 채널이 실제로 삭제된 시각.

```text
NULL
→ Discord 공간이 아직 존재함

timestamp 존재
→ Discord 공간 삭제 완료
```

Discord 리소스가 삭제된 이후에도 기존 Discord ID는 연동 이력 확인을 위해 DB에 남겨둘 수 있다.

모임 자체의 종료 시각은 `recruits`에서 관리하고, `discord_deleted_at`은 **외부 Discord 리소스가 실제 삭제된 시각**만 기록한다.

---

## 10. 기존 `recruit_members` 재사용

새 참여자 테이블은 만들 필요가 없다.

```text

recruit_id | member_id | role   | status

-----------+-----------+--------+---------

37         | 15        | HOST   | JOINED

37         | 27        | MEMBER | JOINED

37         | 31        | MEMBER | CANCELED

```

Bot은 `JOINED`인 사용자의 `members.discord_user_id`를 조회해 Discord 권한을 부여한다.

전체 관계:

```text

recruits

   │

   ├── recruit_members

   │         │

   │         └── members

   │                │

   │                └── discord_user_id

   │

   └── recruit_discord_channels

             │

             ├── discord_category_id

             ├── discord_text_channel_id

             └── discord_voice_channel_id

```

---

## 11. 모임장 역할과 Discord 권한 연결

모임장 여부는 별도 Discord 전용 컬럼을 추가하지 않고 기존 `recruit_members.role`을 활용한다.

```text

HOST

→ 해당 모임의 Discord HOST 권한 부여

MEMBER

→ 일반 참여자 권한 부여

```

따라서 `discord_host_id` 같은 별도 컬럼은 만들지 않는다.

---

## 12. 화면 수정 필요사항

### 모임 생성 화면

```text

Discord 공개 범위

○ 공개 모임

  참여 전에도 Discord 활동 내용을 볼 수 있습니다.

○ 비공개 모임

  참여자만 Discord 채널을 볼 수 있습니다.

```

이 값은 `visibility`와 연결한다.

### 음성채널 옵션

1차에서는 기본 생성.

향후:

```text

☑ 음성채널 사용

```

옵션 추가를 고려한다.

### 참여 / 취소

별도의 Discord 입력은 필요 없음.

```text

[참여하기]

[참여 취소]

```

기존 UI 이벤트가 Discord 권한 변경으로 이어지면 된다.

---

## 13. `contact_method` 처리

10/7 회의에서:

```text

연락 방법 입력 삭제

→ Discord 채널로 대체

```

하기로 했으므로 현재 `recruits.contact_method`는 제거 후보.

단 공용 DB에서 바로 삭제하지 않고:

```text

사용 여부 확인

→ migration 작성

→ 제거

```

순서로 진행한다.

---

## 14. 모임명 중복 처리 원칙

모임명 중복은 ****Discord Bot이 아니라 PlayMate에서 검증****한다.

```text

PlayMate 모임 생성

      ↓

모임명 중복 검사

      ↓

통과

      ↓

Bot 호출

```

Bot은 전달받은 모임명을 정규화해서 기존 모임과 동일한지 판단하지 않는다.

예:

```text

알고리즘 스터디

!!알고리즘!! 스터디

```

를 Bot이 임의로 동일한 이름으로 취급하면 안 된다.

실서비스 중복 생성 방지는 ****이름이 아니라 `recruit_id` 기준****으로 처리한다.

```text

recruit_id

       ↕

discord_category_id

discord_text_channel_id

discord_voice_channel_id

```

이미 해당 `recruit_id`에 Discord 리소스가 연결되어 있으면 새로 생성하지 않는다.

---

## 15. 테스트 단계와 실서비스 단계 구분

### 현재 독립 테스트

- 실제 DB 연결 X

- 실제 PlayMate 서버 연결 X

- 테스트 데이터를 코드에 직접 입력

- Discord 테스트 서버에서 기능 검증

- 현재 테스트용 생성 코드는 실서비스 연동 시 제거 예정

### 실제 서비스 연동

```text

PlayMate 모임 생성

      ↓

DB recruit 생성

      ↓

recruit_id 기준 Discord 연동 상태 확인

      ↓

Bot 호출

      ↓

Discord 공간 생성

      ↓

Discord ID들을 DB에 저장

```

실서비스에서는 `recruit_id` 기반 idempotency로 중복 생성을 방지한다.

---

## 16. 현재 구현 상태

- [x] 상시 모임 활동 재개 시 `last_activity_at` 갱신 및 자동 종료 예약 취소 검증

- [x] Discord Bot 생성

- [x] Bot 로그인

- [x] 테스트 Guild 연결

- [x] 모임별 카테고리 자동 생성

- [x] 카테고리 안에 `#채팅` 자동 생성

- [x] 카테고리 안에 `🔊음성` 자동 생성

- [x] PUBLIC 권한 코드 작성

- [x] PRIVATE 권한 코드 작성

- [x] PUBLIC 비참여자 권한 검증

- [x] PRIVATE 비참여자 권한 검증

- [x] 참여자 권한 부여 검증

- [x] 참여 취소 시 권한 회수 검증

- [x] HOST 권한 부여 검증

- [x] HOST의 채널 생성/수정 권한 동작 확인

- [ ] HOST의 `manage_channels` 실서비스 적용 여부 팀 결정

- [ ] HOST의 `manage_messages` 적용 여부 팀 결정

- [ ] 모임 수정 Discord 동기화

- [ ] 모임 종료 시 Discord 채널/카테고리 즉시 삭제 처리

- [ ] 실제 DB/API 연동

---


### 상시모임 활동 재개 시 자동 종료 예약 취소 검증

비활성 경고 및 7일 후 자동삭제 예약이 생성된 상시모임에서 실제 메시지를 작성하여 활동 재개 흐름을 검증했다.

검증 결과:

- `on_message` 이벤트에서 해당 모임 카테고리의 사용자 메시지 감지 성공
- `last_activity_at`을 현재 시각으로 갱신
- `inactivity_warned_at` 초기화
- `scheduled_delete_at` 초기화
- 터미널에서 `자동 종료 예약 취소` 로그 확인

따라서 현재까지 상시모임 자동정리 흐름은 다음 단계까지 실제 검증됐다.

```text
활동 감지
→ 30일 비활성 판별
→ HOST DM 경고
→ 7일 후 자동삭제 예약
→ 활동 재개
→ 자동삭제 예약 취소
```

다음 검증 단계는 **7일 유예기간이 실제로 지난 상태를 재현하여 `delete_meeting_space()`가 호출되고 Discord 공간이 자동 삭제되는지 확인**하는 것이다.


## 17. 현재 문제 / 리스크

### 17-1. Discord 카테고리 수 제한

현재 구조는:

```text
모임 1개 = Discord 카테고리 1개
```

Discord 공식 문서 기준 서버당 카테고리는 최대 50개까지 생성할 수 있다.

따라서 모임 카테고리를 종료 후에도 계속 보관하면, 공용/관리용 카테고리를 제외한 실제 동시 활성 모임 수가 빠르게 제한될 수 있다.

### 대응 방향

종료된 모임의 Discord 카테고리와 채널을 **즉시 삭제**하여 사용 가능한 카테고리 수를 회수한다.

```text
활성 모임
→ Discord 공간 유지

종료 모임
→ Discord 공간 즉시 삭제
→ DB에는 연동 메타데이터와 삭제 이력만 유지
```

Discord 채팅 메시지 전체를 PlayMate DB에 저장하는 방식은 MVP 범위에서는 적용하지 않는다.

서비스 규모가 커져 종료 공간 즉시 삭제만으로도 한계가 발생할 경우 Discord 채널 구조 변경 또는 서버 분리를 추가 검토한다.

### 17-2. 모임 이름 중복

PlayMate 생성 단계에서 활성 모임명의 중복을 차단해야 한다.

### 17-3. Discord 연동 실패

모임 DB 저장은 성공했지만 Discord 생성은 실패할 수 있으므로 `sync_status`, `sync_error`가 필요하다.

### 17-4. HOST 권한 범위

HOST에게 `manage_channels=True`를 부여하면 채널 생성뿐 아니라 기존 채널의 이름 변경, 설정 변경, 삭제까지 가능하다.

따라서 PlayMate의 모임 정보와 Discord의 실제 채널 구조가 달라질 수 있으며, 해당 권한을 실서비스에서도 유지할지는 팀 논의가 필요하다.

---

## 18. 팀장님께 공유할 핵심 요약

> Discord Bot은 PlayMate의 모임 상태와 Discord 권한을 자동으로 동기화하는 방식으로 구현하고 있습니다.

>

> 모임마다 Discord 서버를 새로 만드는 것이 아니라 PlayMate 공식 서버 하나 안에 ****모임별 카테고리 1개를 생성하고, 그 안에 `#채팅`과 `음성` 채널을 생성****하는 구조입니다.

>

> PUBLIC 모임은 비참여자도 채팅 내용을 읽고 음성방 존재를 확인할 수 있지만 채팅 작성과 음성 접속은 참여자만 가능하게 합니다. PRIVATE 모임은 참여자에게만 카테고리 자체가 보이도록 합니다.

>

> 이를 위해 ERD/DB에는 `members.discord_user_id`와 모임-Discord 연결용 `recruit_discord_channels` 1:1 테이블이 필요합니다. 현재 구조에서는 `discord_category_id`, `discord_text_channel_id`, `discord_voice_channel_id`, `visibility`, `voice_enabled`, `sync_status`, `discord_deleted_at` 등의 값을 관리해야 합니다.

>

> 참여자 권한은 기존 `recruit_members`의 `JOINED/CANCELED`, `HOST/MEMBER` 정보를 활용할 예정입니다.

>

> 모임명 중복 검증은 PlayMate에서 처리하고 Bot은 이름으로 중복 여부를 판단하지 않습니다. 실제 서비스에서는 `recruit_id`와 Discord 리소스 ID를 매핑해 중복 생성을 방지할 예정입니다.

>

> 현재 테스트 서버에서는 Bot 로그인, 모임별 카테고리 생성, 채팅/음성 채널 생성, PUBLIC/PRIVATE 권한 설정을 구현했습니다.

>

> 또한 일반 사용자 계정을 이용해 PUBLIC/PRIVATE 비참여자 권한, 참여자 권한 부여, 참여 취소 시 권한 회수, HOST 권한 부여까지 실제 동작을 검증했습니다.

>

> Discord 카테고리 최대 개수 제한을 고려하여 종료된 모임의 Discord 채널과 카테고리는 삭제하는 방향으로 정리했습니다. 일회성 모임은 `end_at + 24시간` 후 자동 삭제하고, 상시 모임은 장기 비활성 감지 후 HOST 경고 및 유예기간을 거쳐 자동 종료하는 구조를 검토하고 있습니다. Discord 메시지 본문 전체는 PlayMate DB에 복제하지 않고 마지막 활동 시각과 연동/삭제 이력 등 필요한 메타데이터만 보존할 예정입니다.
>
> 상시 모임 비활성 관리는 마지막 활동 시각을 기준으로 30일 비활성 시 HOST에게 경고하고, 7일 유예 후에도 활동이 없으면 자동 종료하는 방향입니다. 테스트에서는 1분 주기로 검증하지만 실서비스에서는 하루 1회 검사하도록 운영할 예정입니다.
>
> HOST에게 `manage_channels=True`를 부여했을 때 채널 생성 및 채널명 변경이 가능한 것도 확인했으며, 해당 권한을 실서비스에서 어느 수준까지 허용할지는 다음 팀 회의에서 결정할 예정입니다.

---

## 19. 팀에서 추가로 결정해야 할 사항

1\. Discord 카테고리 수 제한을 고려했을 때 예상 동시 활성 모임 수가 적절한지

2\. 모임 종료 후 카테고리/채널 보관 기간

3\. 모임장에게 `manage_channels` / `manage_messages` 중 어떤 권한까지 허용할지

4\. 음성채널 생성 여부를 사용자 선택으로 제공할지

5\. Discord 미연동 회원의 모임 참여 처리

6\. 모임명 중복을 어느 범위에서 금지할지

7\. `contact_method`를 실제 DB에서 언제 제거할지

8\. Discord 연동 실패 시 사용자 화면에 어떤 상태를 보여줄지

### HOST Discord 관리 권한 범위

현재 HOST 테스트에서는 `manage_channels=True`를 적용했다.

이 권한을 부여하면 HOST는 다음 작업을 수행할 수 있다.

- 채널 생성

- 채널명 변경

- 채널 설정 변경

- 채널 삭제

Discord 권한 구조상 현재 `manage_channels`를

- 채널 생성만 허용

- 기존 채널명 변경 금지

와 같이 세부적으로 분리하여 부여하기 어렵다.

따라서 다음 회의에서 아래 정책을 결정할 필요가 있다.

1\. HOST에게 `manage_channels=True`를 그대로 부여할 것인지

2\. HOST가 직접 채널을 관리하지 않고 PlayMate/Bot을 통해 필요한 채널을 추가하도록 할 것인지

3\. HOST에게 `manage_messages=True`까지 부여할 것인지

현재 임시 정책:

- `manage_channels=True` 적용

- `manage_messages=True` 미적용

`manage_channels=True`를 유지하는 경우 HOST가 Discord에서 기존 채널명 또는 구조를 변경하면서 PlayMate의 데이터와 Discord 상태가 달라질 가능성이 있으므로 운영 정책 결정이 필요하다.
