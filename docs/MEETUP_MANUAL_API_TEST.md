# 모임 API 직접 테스트하기

이 안내는 **가상 회원·메모리 SQLite를 사용하는 별도 테스트 서버** 기준입니다.
실제 로그인, 공유 PostgreSQL, XP 지급, 마이페이지, 스토리지, 디스코드는 테스트하지 않습니다.
기존 `app.main:app` 서버는 그대로 두고, 별도 **8001번 포트**를 사용합니다.

## 1. 서버 실행

프로젝트 루트에서 실행합니다. 브랜치는 `feature/33-meetup-backend-function-fix`입니다.

```powershell
cd C:\dev\project\playmate
& .\.venv\Scripts\python.exe -m backend.tests.recruit.manual_api --port 8001
```

`Application startup complete`가 나오면 브라우저에서 아래 주소를 엽니다.

http://127.0.0.1:8001/docs

8001이 이미 사용 중이면 다른 프로그램을 종료하지 말고 `--port 8002`로 실행해 주소도 8002로 바꿉니다. 테스트 서버를 종료하면 가상 데이터가 사라지고, 다시 실행하면 처음 상태입니다. 개인 `.env`는 수정하지 않습니다.

## 2. Swagger에서 누르는 순서

각 API를 클릭 → **Try it out** → 값을 입력 → **Execute** 순서입니다.
정상 여부는 아래 `Code`와 `Response body`로 확인합니다.

먼저 **0. 테스트 안내 → GET /__test__/guide**를 실행합니다.

- project_id: 미리 만들어 둔 프로젝트 번호입니다.
- study_id: 미리 만들어 둔 스터디 번호입니다.
- now: 현재 가상 시각입니다.
- project_join_example: 프로젝트 신청창에 복사할 내용입니다.
- project_create_example: 새 프로젝트 생성 예시입니다. 예시의 ID는 실제 기술 ID가 아닙니다.

가상 회원 1은 두 샘플 모임의 개설자입니다. 회원 2~8은 다른 회원, 9는 관리자입니다.
**X-Test-Member-ID**는 ‘이 요청을 어느 가상 회원으로 보낼지’입니다. 실제 로그인이나 개발용 인증이 정상 작동한다는 뜻은 아닙니다.

## 3. 프로젝트 신청

**POST /api/recruits/{recruit_id}/join**을 엽니다.

- recruit_id: guide의 project_id
- X-Test-Member-ID: **2**
- Request body: 아래 내용

```json
{
  "skill_ids": [102],
  "career_item_ids": [],
  "leader_volunteer": false,
  "direct_input": {
    "skills": [],
    "education": null,
    "certificates": null,
    "experience": "React 학습 경험이 있습니다.",
    "awards": null,
    "portfolio_url": null
  }
}
```

**200**, application_status **ACCEPTED**면 성공입니다.
같은 회원으로 다시 신청하면 **409 중복 신청**이 정상입니다.

GET `/api/recruits/{recruit_id}`에서 같은 모임을 조회합니다.
확정 인원 2명, missing_skill_ids 빈 배열, lifecycle_status READY를 확인합니다.
**READY는 시작 준비 상태이며 아직 진행 중은 아닙니다.**

## 4. 스터디 대기와 승격

같은 join API에서 모임 번호를 **study_id**로 바꾸고 Request body는 `{}`로 넣습니다.

1. X-Test-Member-ID **2**로 신청 → ACCEPTED.
2. X-Test-Member-ID **3**으로 신청 → WAITING.
3. DELETE `/api/recruits/{recruit_id}/join`을 회원 **2**로 실행 → 취소.
4. GET 상세를 회원 **3**으로 실행 → my_application.application_status가 ACCEPTED.

샘플 스터디 정원은 개설자 포함 2명입니다. 빈자리가 나면 이미 신청한 회원 3이 먼저 승격되어야 합니다.
이 과정이 실제 회원 데이터에 기록되거나 디스코드에 전송되지는 않습니다.

## 5. 마감과 시작 — 실제로 며칠 기다릴 필요 없음

테스트를 처음 실행하면 모임 시작은 가상 시각 기준 4일 뒤입니다.

**POST /__test__/advance**에 아래 값을 보냅니다.

```json
{"hours": 72}
```

가상 시계가 3일 전진해 시작 24시간 전이 됩니다. 실제 PC 시각은 변하지 않습니다.

- 프로젝트 팀장이 선정됩니다.
- 새 신청과 대기자 승격이 마감됩니다.
- 스터디 확정자가 1명뿐이면 CANCELED입니다.

이후 같은 API에 `{"hours":24}`를 보내면 시작 시각입니다. 조건을 충족한 모임은 IN_PROGRESS, 미달 프로젝트에서 연장/예외 결정을 하지 않았으면 CANCELED입니다.
**advance는 요청할 때마다 누적됩니다.** 처음부터 다시 하려면 서버를 종료하고 다시 실행합니다.

## 6. 연장만 따로 테스트

서버를 다시 실행해 처음 상태로 시작하고, **프로젝트에 회원 2를 신청시키지 않습니다.**
advance 72시간 → 프로젝트 상세 조회 → 팀장 회원 1, can_extend true를 확인합니다.

POST `/api/recruits/{recruit_id}/extension`에 아래 필드를 보냅니다.

```json
{
  "starts_at": "상세의 기존 starts_at보다 2일 뒤, 시간대 포함 시각",
  "ends_at": "새 시작보다 뒤인 종료 시각",
  "schedule_version": 1,
  "request_key": "manual-extension-1"
}
```

따옴표 안 안내 문장은 실제 날짜가 아닙니다. GET 상세나 guide의 날짜를 기준으로 수정합니다.
예: `2026-11-10T19:00:00+09:00` 형식입니다.

- 정상 연장 → extension_count 1, schedule_version 2.
- 같은 키와 같은 내용 재요청 → 횟수 추가 없이 같은 결과.
- 같은 키로 다른 날짜 요청 → 409.
- 일반 PATCH로 마감 이후 일정을 변경하려는 요청 → 409.
- 연장한 뒤에는 새 마감 시각에 도달해야 다음 연장을 선택할 수 있습니다.

## 7. 지금 검증하지 못하는 것

- 실제 로그인 쿠키·Discord OAuth.
- PostgreSQL 실제 행 잠금·동시 요청·마이그레이션 적용.
- 프론트 화면 연결과 기존 종류의 실제 운영 경로.
- 공통 XP 지급/회수, 커리어 불러오기, 파일 업로드, 디스코드 채널 생성.

모두 이 격리 서버의 성공과 구분해야 합니다. 운영 main.py의 새 라우터 등록과 공유 DB 적용은 개발 프롬프트에 정한 보류 조건에 따라 아직 실행하지 않았습니다.
