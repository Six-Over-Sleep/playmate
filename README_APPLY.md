# PlayMate Issue #101 — 전국 부트캠프 가입/게시판 정책 일괄 변경

- **Python 3.13 / FastAPI (프로젝트 설치 버전) / PostgreSQL 18 / React + Vite**
- 관리자 승인 없이 Discord OAuth + 교육기관/과정/기수 선택만으로 가입
- 수료/졸업 후에도 `ACTIVE`, `COMPLETED` 소속이면 접근 가능
- 기존 36기 게시판 ID 8은 031 마이그레이션 실행 전까지 LEGACY 유지
- **`032`는 먼저 적용해야 새 가입 API가 동작합니다. `031`은 가장 마지막에 적용하세요.**

## 적용

1. `docs/101-db-design`에서 변경 사항 확인하고 Git 작업을 보존하세요.
2. ZIP에 담긴 경로를 프로젝트 루트에 그대로 덮어쓰세요. 기존 로컬 변경 사항과 충돌하면 병합하세요.
3. 공유 DB의 백업을 확보하고, `032_self_registration_policy.sql`을 DBeaver ROLLBACK 검증 후 원본 실행하세요.
4. `python -m pytest backend/tests/test_self_registration_101.py backend/tests/test_member_dm_default.py backend/tests/test_board_scope_permissions_101.py -q`
5. `python -m pytest backend/tests/test_auth_flow.py backend/tests/test_account_withdrawal_85.py backend/tests/test_course_board_permissions.py -q`
6. `python -m pytest backend/tests -q` (구형 Mock 기반 테스트의 추가 SQL 조회 응답은 기존 격리 fixture로 처리)
7. `cd frontend; npm run build`
8. 신규 가입 API 및 교육과정 목록 API를 로컬에서 수동 확인한 뒤 배포하세요.
9. `031_board_scope_migration.sql`은 백엔드/프론트 배포 및 기존 회원 회귀 테스트 완료 후 마지막에 실행하세요.

## API
- `GET /auth/education-options` (Discord 인증 세션 필요): `{"cohorts":[...]}`
- `POST /auth/signup`: `{"nickname":"예시", "cohort_id":2}`

## 유의 사항
- 소속은 사용자가 직접 선택하므로 재학/재직 증명이 아닙니다. 민감한 관리자 역할은 별도 통제해야 합니다.
- `ALL_VERIFIED`라는 기존 정책 이름은 유지했지만 실질적으로 ACTIVE/COMPLETED 소속을 허용합니다.
- 새 기관 및 프로그램/기수는 `institutions`, `programs`, `cohorts`에 **관리자가 사전 등록한 항목**만 가입 목록에 표시됩니다.
- 실제 회원 데이터 이관 이후 선택 가능한 기수는 현재 PlayData Family AI 36기 하나입니다. 전국 기관 데이터는 별도 등록이 필요합니다.
- 새 기수 게시판의 자동 생성은 가입 시 동기화하며 기존 36기 게시판은 그대로 유지합니다.
- `032` 데이터 변경 및 구형 `031` 파일의 불일치가 없도록 이번 제공본을 사용하세요.
