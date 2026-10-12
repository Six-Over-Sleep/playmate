# Playmate | 부트캠프 커뮤니티

## 프로젝트 개요
Discord 기반 부트캠프 커뮤니티 프로젝트임. 게시판·모임·정보공유·분실물·자격증·취업 메뉴를 제공하는 것을 목표로 함.

## 기술 구성
- Backend: Python / FastAPI / SQLAlchemy / Pydantic
- Database: Aiven PostgreSQL, psycopg2, DBeaver
- Frontend: React (별도 담당 팀 개발)
- 패키지 관리: uv (`pyproject.toml`, `uv.lock`)
- 협업 브랜치: `feature/meetup` 등 기능별 브랜치

## 폴더 안내
| 폴더 | 목적 |
|---|---|
| `backend/` | FastAPI 서버 및 API 비즈니스 로직 |
| `database/` | DB 생성/관리 스크립트 및 SQL |
| `frontend/` | React 화면 및 API 호출 코드 |
| `ai/` | ML/DL/LLM 관련 코드 |
| `crawler/` | 뉴스·취업·맛집 정보 수집 |
| `docs/` | 설계·QA·산출물 문서 |

## 로컬 실행
```powershell
uv sync
uv run uvicorn backend.app.main:app --reload
```
Swagger: `http://127.0.0.1:8000/docs` · 모임 목록: `http://127.0.0.1:8000/api/recruits`

## 환경 설정
프로젝트 최상위 `.env`에 `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`을 설정함. `.env`는 GitHub에 올리지 않음. `.env.example`에는 실제 비밀번호를 넣지 않음.

## 모임 1주 차 구현 현황
목록/상세/생성/수정/논리삭제, 참여/취소/참여자/인원 조회, 운동·게임·스터디·공동구매 상세 저장/조회 기본 테스트 완료함. Discord 인증 및 권한 검사, 동시성 제어, 고급 필터/검색은 미구현임.

자세한 구현 내용은 `backend/README.md`와 인수인계 워드 문서를 참고함.
