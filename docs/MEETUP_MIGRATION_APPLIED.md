# 모임 확장 테이블 공유 DB 적용 기록

2026-10-26, 사용자 승인 후 적용.

- 대상: 현재 개인 설정이 가리키는 `defaultdb` / `public`.
- SQL: `database/sql/20261026_recruit_programs.sql`.
- SHA-256: `bcf3584537787f06194658f32736c91e21e0370b5fd689d310a54d8e1f73e6a2`.
- 적용 전 신규 테이블이 없음을 재확인하고, 트랜잭션과 마이그레이션 잠금으로 적용.
- 신규 테이블 9개 생성 완료. 기존 테이블 ALTER나 기존 데이터 INSERT/UPDATE/DELETE는 수행하지 않음.
- 커밋 후 별도 읽기 전용 연결로 9개 테이블 존재·모든 신규 테이블 0건·활성 신청 중복 방지 인덱스를 확인.

생성 테이블:

1. recruit_programs
2. recruit_applications
3. recruit_eligibility
4. recruit_withdrawals
5. recruit_curricula
6. recruit_activities
7. recruit_recognitions
8. recruit_outbox
9. recruit_program_commands

**이 SQL 파일은 이제 적용된 이력입니다. 같은 DB에 재실행하거나 원본을 바꿔 재적용하지 않습니다.** 이후 구조 변경은 별도 후속 마이그레이션으로 작성합니다.

개인 .env의 내용은 문서에 저장하지 않았으며, API 활성화 설정/공통 기술 사전 연결/실제 로그인 검증/예약 실행 연결은 이 DDL 적용과 별도입니다. 커밋·푸시·PR은 실행하지 않았습니다.
