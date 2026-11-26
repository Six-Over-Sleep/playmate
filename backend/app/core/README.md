# core | 공통 설정·인증·DB

FastAPI가 공통으로 사용하는 설정·보안·연결 리소스를 관리합니다.

## 주요 파일

| 파일 | 실제 역할 |
|---|---|
| `config.py` | 루트 `.env` 로드, Discord OAuth·DB·프론트 주소 설정 검증 |
| `auth.py` | 세션+DB 기반 활성 회원 확인, 개발 헤더 예외 처리 |
| `database.py` | psycopg 연결, SQLAlchemy `engine`·`SessionLocal`·`Base`·`get_db()` |
| `db_connect.py` | psycopg2 직접 SQL용 제한된 풀, `db_cursor` 컨텍스트 관리자 |
| `uploads.py` | 업로드 경로와 파일 관리 공통 기능 |
| `recruit_config.py` | 신규 모임·예약 처리 기능 설정 |

## 인증 정책

- OAuth 로그인 세션의 `member_id`와 `discord_id`가 DB의 **ACTIVE 회원** 정보와 일치해야 합니다.
- 운영(기본값 및 `APP_ENV=production`)에서는 개발 헤더가 무시됩니다.
- `APP_ENV=development` 또는 `test`에서만 세션이 없는 요청의 `X-Dev-Member-ID`를 허용합니다.
- 로컬 HTTP 인증 개발 시 `.env`에 `APP_ENV=development`를 설정합니다.

## DB 연결 정책

| 연결 경로 | 용도 | 설정 |
|---|---|---|
| `database.py` ORM 풀 | 모임·ORM 모델 | 최대 **1개/프로세스** (`pool_size=1`, overflow 0) |
| `db_connect.py` psycopg2 풀 | 인증·게시판 등 직접 SQL | `DB_POOL_MAX_CONNECTIONS` 기본 **2**, 범위 1~4 |

워커마다 별도 풀이 만들어지며 Discord Bot/수집기도 연결을 소비합니다. Aiven 무료 DB처럼 연결 한도가 작은 환경에서는 전체 프로세스와 워커 수를 먼저 계산합니다. **DB 호출 후 세션/커서를 반드시 반환**하세요.

```python
from backend.app.core.database import get_db
# Router에서 db: Session = Depends(get_db)
```

## 운영 주의사항

- `.env`, 토큰, DB 비밀번호는 GitHub에 커밋하지 않습니다.
- 운영에서 `Base.metadata.create_all()`, `drop_all()`을 임의로 실행하지 않습니다.
- 스키마 변경은 `database/sql/` 마이그레이션으로 관리합니다.
- `/uploads` 제공 시 `nosniff` 헤더는 적용되어 있지만 이미지 공개 범위·EXIF·프록시 크기 제한은 별도 점검합니다.

상세 안내: [Backend README](../../README.md) / [배포 보안](../../../docs/BETA_SECURITY_DEPLOYMENT.md)
