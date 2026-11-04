# Database

커뮤니티 서비스의 데이터베이스 구조 및 DB 관리 코드를 저장하는 폴더임.

ERD와 같은 설계 문서는 `docs/design/`에서 관리함.

실제로 실행되는 SQL 및 DB 관리 코드는 해당 폴더에서 관리함.

## 폴더 구조

| 폴더 | 설명 |
|---|---|
| `sql/` | 테이블 생성 및 초기 데이터 SQL 관리 영역임 |
| `scripts/` | DB 생성, 초기화, 데이터 삽입 코드 관리 영역임 |

```text
database/
├─ sql/
├─ scripts/
└─ README.md
```

## 폴더 설명

### `sql/`

데이터베이스에서 직접 실행하는 SQL 파일을 저장함.

예시는 다음과 같음.

```text
create_tables.sql
drop_tables.sql
seed_categories.sql
seed_branches.sql
```

### `scripts/`

데이터베이스 관리용 Python 스크립트 등을 저장함.

예시는 다음과 같음.

```text
create_db.py
reset_db.py
insert_seed.py
```

## 다른 폴더와의 역할 구분

```text
docs/design/
→ ERD, 테이블 정의서 등 설계 문서 관리

database/sql/
→ 실제 DB에서 실행할 SQL 관리

database/scripts/
→ DB 생성 및 초기화 자동화 코드 관리

backend/app/models/
→ FastAPI에서 사용하는 ORM 모델 관리
```

## 관리 규칙

실제 운영 DB 파일은 GitHub에 업로드하지 않음.

테이블 구조를 수정하는 경우 다음 항목을 함께 확인함.

```text
ERD
SQL
Backend Model
API
```
## Discord Bot 테이블 (`022_discord_bot_tables.sql`)

`notifications`(DM 알림 대기열)와 `recruit_discord_channels`(모임 Discord 채널 상태)를 만드는 SQL임.
공용 DB 적용은 DB 담당자와 협의한 뒤 진행함.

### 새 DB를 만들 때

1. Backend 기본 테이블(`members`, `posts`, `comments`, `recruits`, `recruit_members`)이 먼저 있어야 함. 022는 이 테이블을 만들지 않음.
2. `database/sql/`의 번호 순서대로 적용함. 번호가 같은 파일(012, 013)은 서로 독립이라 순서와 무관하며, 이미 적용된 환경이 있을 수 있어 이름을 바꾸지 않음.
3. `022_discord_bot_tables.sql` 적용. 여러 번 실행해도 안전함.
4. Bot DB 계정에 권한 부여 (022 파일 하단 목록 참고).

### 기존 DB와의 비교 결과 (Issue #95)

개발 중인 PostgreSQL DB를 읽기 전용으로 비교한 결과임.

- 두 테이블 모두 존재하고 컬럼 구조 차이 없음.
- `recruit_discord_channels.recruit_id` PK 이상 없음.
- `discord_text_channel_id` 단독 UNIQUE 인덱스와 `sync_status` CHECK가 이름만 다르게 이미 존재함. 같은 역할이므로 추가 조치 불필요.
- 위 결과는 특정 DB 한 곳 기준이며 다른 환경(공용, 운영)은 따로 확인해야 함.

### 이미 테이블이 있는 DB에 적용할 때 주의사항

- 022는 `CREATE ... IF NOT EXISTS`만 사용하므로 같은 이름의 테이블이 있으면 그 테이블은 건드리지 않음. **기존 테이블과 구조가 같은지는 보장되지 않으므로** 적용 전에 컬럼, 제약조건, 인덱스를 직접 비교해야 함 (`information_schema.columns`, `pg_constraint`, `pg_indexes`).
- 제약조건은 이름이 다를 수 있으므로 이름이 아니라 실제 정의(대상 컬럼, 허용 값)로 비교함.
- 구조가 다른 테이블에 022를 실행하면 인덱스 생성 단계에서 오류가 나며 트랜잭션이 롤백되어 아무것도 바뀌지 않음.
- 구조 차이가 있으면 임의로 `ALTER` 하지 말고 DB 담당자와 변경 방법을 정함.
- 기존 테이블에 `updated_at` trigger가 없으면 022가 `notifications`에만 추가함 (`trg_notifications_set_updated_at`).

### DB 담당자 확인 사항

- 적용 대상 DB에 두 테이블이 이미 있는지, 있다면 컬럼 타입(특히 `timestamp`/`timestamptz`)과 제약조건
- `notifications`: Backend 계정 INSERT, Bot 계정 SELECT·UPDATE 권한
- `recruit_discord_channels`: Bot 계정 SELECT·INSERT·UPDATE 권한
- 예전 구조의 `discord_category_id`, `discord_voice_channel_id`, `recruits.discord_channel_id`, `recruits.discord_channel_status`를 정리할 시점 (이번 SQL에서는 삭제하지 않음)
