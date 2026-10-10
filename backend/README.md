# Backend

## 역할
FastAPI가 React의 HTTP 요청을 받고, SQLAlchemy로 PostgreSQL 데이터를 읽고 저장하는 서버임.

## 구조
```text
backend/app/
├── main.py                 # FastAPI 앱 실행 및 라우터 연결
├── core/database.py        # Aiven 연결, SQLAlchemy 세션
├── models/                 # DB 테이블 ↔ Python 클래스
├── schemas/                # 요청 데이터 형식·검증
├── routers/                # API 주소/HTTP 메서드
└── services/               # 실제 DB 저장 등 처리
```

## 실행
```powershell
uv sync
uv run uvicorn backend.app.main:app --reload
```
- 문서 확인: `http://127.0.0.1:8000/docs`
- 목록 API: `GET /api/recruits`

## 작업 흐름
React → `routers/recruit.py` → `services/recruit.py` 또는 ORM 조회 → `core/database.py` → PostgreSQL 순서로 처리함.

## 모임 API
| HTTP | URL | 역할 |
|---|---|---|
| GET | `/api/recruits` | 삭제되지 않은 모임 목록 |
| GET | `/api/recruits/{recruit_id}` | 모임 상세 + `detail` |
| POST | `/api/recruits` | 모임 생성 |
| PATCH | `/api/recruits/{recruit_id}` | 공통 정보 수정 |
| DELETE | `/api/recruits/{recruit_id}` | 논리 삭제 |
| POST | `/api/recruits/{recruit_id}/join` | 테스트 사용자 참여 |
| DELETE | `/api/recruits/{recruit_id}/join` | 참여 취소 |
| GET | `/api/recruits/{recruit_id}/members` | JOINED 참여자 목록 |
| GET | `/api/recruits/{recruit_id}/count` | 현재 인원/정원/잔여석 |

## 제약사항
- 개발용 회원 ID `-1`을 사용 중임. 실제 로그인과 권한 검사는 아직 없음.
- 모임 생성에서는 카테고리 상세를 저장하지만 PATCH는 상세 항목 변경을 지원하지 않음.
- 동시 참여 시 정원 초과 방지용 잠금은 아직 없음.
- 응답 스키마 통일/오류 규격/CORS/자동 테스트는 후속 작업임.
- 공통 `members`, `posts` 테이블 변경 시 다른 팀과 협의해야 함.
