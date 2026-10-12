# core | 공통 DB 연결

## 파일
- `database.py`: 루트 `.env` 읽기, SQLAlchemy `engine`/`SessionLocal`/`Base`/`get_db()` 제공함.
- `test_database.py`: 작성한 경우 개발용 DB 연결 점검에 사용함.

## 점검
```powershell
uv run python -m backend.app.core.test_database
```
위 명령은 해당 테스트 파일이 존재할 때만 사용함. DB 접속 정보는 `.env`에 저장하고 커밋하지 않음.

## 주의
운영 중 `Base.metadata.create_all()` 또는 테이블 삭제 명령을 임의 실행하지 않음. DB 구조 변경은 팀과 조율함.
