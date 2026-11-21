# 모임 DB 통합 (#157) — 042/043

- 최신 backend_latest.zip 및 database_latest.zip 기준으로 작성. 037~041은 수정하지 않음.
- 모임 상세 4개 → recruits.details JSONB, 커리큘럼 → recruit_programs의 2개 컬럼. 기존 5개 이름은 호환 뷰로 유지.
- 최신 recruit.py의 get_reply_target 및 041 스키마 검사 보존. 배포 전 검사에 042/043 필수 컬럼 추가. 기존 모임/댓글 테스트용 스키마를 신규 저장 구조에 맞게 수정.
- 17→12, 전체 78→73은 실제 DB에 대상 물리 테이블이 모두 있는 경우의 예상값.

## 검증 기록
- 최신 코드와 합친 뒤 Python compileall 통과.
- DB 연결만 대체한 SQLite 격리 스모크 통과: 모임 생성/조회/수정, 종류 변경, 커리큘럼 및 충돌, SQL NULL, 최신 답글 대상 조회.
- pytest는 psycopg2 미설치로 conftest 로딩 중단. PostgreSQL 실제 서버 및 권한 테스트 미실행.
- 별도 로컬 검증 ZIP은 선택된 선행 SQL과 037~043을 신규 테스트 DB에서 실행하도록 구성(실행 미검증). 전체 000~043 마이그레이션 및 Aiven 실데이터 복원 검증을 대체하지 않음.

## 배포 전
1. 실제 Aiven/RDS 적용 이력·DB 상태·담당자와 SQL 번호 확인.
2. 복원 DB 백업 및 preflight, 042→043, postcheck, 데이터·권한·기존 코드 호환 검증.
3. 실제 서비스 계정으로 모임/댓글/취업/첨부/XP/Discord 회귀 테스트.
4. 대상 DB에 검증된 SQL을 적용하고 나서 새 백엔드 배포. develop 자동 배포 전 DB 전환 필수.
5. 호환 뷰 제거는 모든 호출부 확인 후 별도 작업. 운영에서 create_all 및 기존 baseline 재실행 금지.
