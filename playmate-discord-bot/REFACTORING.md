# PlayMate Discord Bot 리팩터링 결과

## 변경 목적

검증 완료된 단일 bot.py를 책임별로 분리했습니다. Discord 호출 순서, 권한 overwrite, 반환값, 로그와 DM 문구, 자동 종료 조건을 유지했습니다. PostgreSQL 연결은 추가하지 않았습니다.

## 변경 파일과 이유

| 파일 | 변경 이유 |
| --- | --- |
| bot.py | Client 생성, repository 주입, 이벤트 연결, 로그인 및 검사 작업 시작만 담당합니다. 서비스 함수는 기존 이름으로 import하여 접근할 수 있습니다. 직접 실행 시에만 client.run을 호출합니다. |
| config.py | 환경변수 로딩·필수값 검사, KST, 30일 비활성, 7일 유예, 일회성 24시간 유예, 검사주기를 한곳에 모았습니다. |
| services/meeting_space.py | create_meeting_space와 delete_meeting_space를 원본 로직 그대로 이동했습니다. 모임명 중복 판단을 추가하지 않았습니다. |
| services/permissions.py | 참여자 권한 부여·회수와 HOST 권한 부여를 원본 로직 그대로 이동했습니다. |
| services/lifecycle.py | 일회성 및 상시모임 종료 조건, HOST DM, 삭제 직전 활동 안전 확인, 준비 완료 대기와 주기 검사 작업을 담당합니다. |
| handlers/message_handler.py | 사용자 활동 감지, 활동 시각 갱신, 경고·예약 취소를 담당합니다. 메시지 본문을 읽거나 저장하지 않습니다. |
| repositories/meeting_repository.py | MeetingRepository Protocol과 InMemoryMeetingRepository로 저장소 경계를 만들었습니다. 원본의 빈 테스트 데이터를 메모리 구현 안에 두었습니다. |
| 각 __init__.py | 역할별 디렉터리를 Python 패키지로 만듭니다. |
| .env.example | 운영 기본값을 담은 환경변수 입력 형식입니다. 로컬 .env는 공유·배포 ZIP에 포함하지 않습니다. |
| .gitignore | .env, 가상환경, Python 캐시, 임시 작업 파일을 제외합니다. |
| requirements.txt | 검증 환경의 discord.py==2.7.1, python-dotenv==1.2.4로 버전을 고정했습니다. |
| tests/test_refactor.py | 실제 Discord 서버 없이 원본 대비 상태·출력·호출을 비교하는 회귀 검증입니다. |
| tests/fixtures/original_bot.py | 제공된 원본을 수정하지 않고 검증 기준으로 보존했습니다. 이 파일은 직접 실행하지 않습니다. |

## 유지한 동작

- 기본 Discord intents를 유지합니다. Message Content Intent를 새로 활성화하지 않습니다.
- PUBLIC/PRIVATE 권한과 음성 채널 생성 옵션, 하위 채널 → 카테고리 삭제 순서를 유지합니다.
- HOST의 manage_channels=True를 유지합니다.
- 원본의 manage_messages는 명시적 False가 아니라 미설정(None)이었습니다. False로 바꾸면 상속 권한을 명시적으로 거부하는 변경이 되므로, 원본처럼 미설정으로 유지했습니다. HOST에게 이 권한을 새로 부여하지 않습니다.
- 일회성 모임은 end_at + 24시간 이상이면 삭제합니다.
- 상시모임은 30일 이상 비활성이면 경고하고, DM 전송 성공 후 7일 유예를 저장합니다. DM 실패 시 상태를 변경하지 않는 원본 처리도 유지합니다.
- 삭제 예약이 만료되었더라도 last_activity_at > inactivity_warned_at이면 예약을 취소합니다.
- 사용자 활동이 감지되면 마지막 활동 시각을 갱신하고 기존 경고·삭제 예약을 취소합니다.
- 삭제 성공 때만 discord_deleted_at을 기록합니다.
- 원본처럼 메모리 상태는 프로세스 종료 시 사라집니다.
- 실제 서비스의 중복 방지는 향후 recruit_id와 Discord resource ID 연결 기준으로 구현합니다. 이번 변경에 새로운 중복 방지 기능은 없습니다.

## 설정과 실행

기존 프로젝트에 반영할 때 실제 값이 있는 기존 .env를 그대로 사용하세요. 새 환경에서는 .env.example을 .env로 복사하고 실제 값은 로컬에서 입력하세요. .env는 배포 ZIP에서 제외되며 .gitignore에서도 제외됩니다.

```dotenv
DISCORD_BOT_TOKEN=로컬에서만_입력
DISCORD_GUILD_ID=기존_서버_ID
PLAYMATE_TEST_MODE=false
```

- PLAYMATE_TEST_MODE=true: 테스트를 명시적으로 선택하면 60초마다 검사합니다.
- PLAYMATE_TEST_MODE=false 또는 미지정: 일회성·상시모임을 86,400초마다 함께 검사합니다. 실서비스 비활성 검사는 하루 1회입니다. 준비 완료 직후 첫 검사가 실행되는 원본 동작도 유지됩니다.

```powershell
python -m pip install -r requirements.txt
python bot.py
```

## Repository 경계

서비스와 핸들러는 테스트 전역변수에 접근하지 않고 목록 조회·카테고리 ID 조회·저장 메서드를 사용합니다. 테스트 데이터는 다음처럼 외부에서 주입할 수 있습니다.

```python
repository = InMemoryMeetingRepository(
    one_time_meetings=[...],
    ongoing_meetings={category_id: {...}},
)
```

현재 구현은 기존 실행 순서를 유지하려고 동기 메서드와 메모리 객체 참조를 사용합니다. 향후 DB 구현은 이 Protocol의 조회 결과와 save 동작을 구현하면 됩니다. 비동기 DB 드라이버로 변경하면 인터페이스와 호출부의 await 추가가 필요합니다. DB 트랜잭션이나 다중 프로세스 동시성 보장은 이번 작업에서 구현하지 않았습니다.

## 검증 결과

검증 환경: Python 3.13.15 / discord.py 2.7.1.

| 검증 | 결과 |
| --- | --- |
| 전체 모듈 구문 컴파일 | 통과 |
| 모듈 import와 의존성 연결 | 통과 |
| 공간 생성·삭제 및 권한 함수 5개의 실행 AST | docstring을 제외한 실행 로직이 원본과 동일 |
| 원본 대비 동작 비교 45개 단언 | 통과 |
| 실제 메시지 본문 없이 메시지 처리 | 통과 |
| Discord 준비 완료 전 검사 시작 방지 | 통과 |
| on_ready 재호출 시 검사 중복 방지 | 통과 |
| 테스트 검사주기 | 60초 확인 |
| 실서비스 검사주기 | 86,400초 확인 |
| 실행 진입점 Client.run 호출 | 네트워크를 대체한 검증에서 1회 호출 확인 |
| 실제 python bot.py | 실행 시도 완료. 실제 Token 미제공으로 기존과 같은 필수 환경변수 오류에서 중단 |
| 실제 Discord 로그인 및 서버 조작 | 실제 .env가 없어 미검증 |

동작 비교에는 24시간·30일·7일 경계, 이미 삭제된 모임, 활동 재개, 경고 후 활동 안전 조건(크거나 같은 경우 구분), 삭제 실패, DM 및 HOST 조회의 NotFound/Forbidden/HTTPException, Bot 메시지·DM·일반 채널·미등록 모임 무시를 포함했습니다.

회귀 검증 재실행:

```powershell
python tests/test_refactor.py
```

이 검증은 임시 환경변수와 모의 Discord 객체를 사용합니다. 실제 Token을 읽어 출력하거나 실제 Discord 서버를 호출하지 않습니다.

## 운영 전 안전성 수정 (2026-10-12)

- 배포 ZIP에서 .env를 제외했습니다. 로컬 .env는 변경하지 않았고, .gitignore의 .env 제외 설정을 확인했습니다.
- PLAYMATE_TEST_MODE 미지정 시 false, 기본 검사주기 86,400초로 변경했습니다. .env.example도 false를 사용합니다. 기존 .env에서 true를 명시한 경우에는 계속 테스트 모드가 켜집니다.
- permissions.py HOST docstring을 실제 overwrite인 미설정(None)으로 정정했습니다. 권한 코드는 변경하지 않았습니다.
- requirements.txt를 discord.py==2.7.1, python-dotenv==1.2.4로 고정했습니다. 실제 설치 버전과 일치하는 것을 확인했습니다.
- 기존 동등성 테스트 45개 단언을 재실행하여 통과했습니다. docstring만 제외하고 실행 AST를 비교하므로 설명 수정과 기능 변경을 구분합니다.
- 이 환경에서는 Windows 이벤트 루프의 내부 로컬 소켓 생성이 제한되어, 회귀 테스트 실행에만 임시 소켓 없는 이벤트 루프를 사용했습니다. 배포 코드와 배포 테스트의 기본 이벤트 루프는 변경하지 않았습니다. 테스트는 모두 모의 Discord 객체를 사용합니다.
- 전체 구문 컴파일, 테스트 모드 설정 5개 경우, HOST overwrite, 의존성 버전, ZIP 무결성 및 .env 제외 검증을 통과했습니다. 실제 Discord 로그인은 이번 수정에서도 수행하지 않았습니다.

추가 안전성 검증 재실행:

```powershell
python tests/test_safety.py
```

이 검증은 로컬 .env를 읽지 않습니다. 작업 폴더에 배포 ZIP이 있으면 ZIP 구성도 검사하며, ZIP을 풀어 실행하는 환경에서는 설정·버전·권한 설명을 검사합니다.
