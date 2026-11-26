-- PLAYMATE XP 정책: 커리어 연구소에 가이드 글 유형(GUIDE) 추가
-- 적용 시점: feature/62 작업 이후, 다른 XP 변경과 별도 관리
-- 이 마이그레이션은 글 유형만 허용합니다. XP 지급은 별도 서비스 연동 전까지 발생하지 않습니다.
-- 사전 조건: database/sql/008_career_labs.sql 적용 완료

BEGIN;

-- 기존 DDL에서 이름을 지정하지 않은 CHECK 제약조건의 PostgreSQL 자동 이름.
-- 기존 QUESTION / DISCUSSION과 신규 GUIDE만 허용하도록 갱신합니다.
ALTER TABLE career_labs
    DROP CONSTRAINT IF EXISTS career_labs_post_type_check;

ALTER TABLE career_labs
    ADD CONSTRAINT career_labs_post_type_check
    CHECK (post_type IN ('QUESTION', 'DISCUSSION', 'GUIDE'));

-- 기존 ck_career_labs_resolved 제약조건은 그대로 두므로
-- GUIDE 글에 is_resolved=TRUE를 설정할 수 없습니다.

COMMIT;

-- 실행 후 확인용 조회 (기존 질문/토론 글은 수정되지 않습니다)
SELECT conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'career_labs'::regclass
  AND conname = 'career_labs_post_type_check';
