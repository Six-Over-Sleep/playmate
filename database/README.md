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