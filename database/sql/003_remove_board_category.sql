-- 기존 DB에서 게시판 분류 컬럼만 제거합니다.
-- 모임(recruits) 카테고리 컬럼은 변경하지 않습니다.
BEGIN;
ALTER TABLE IF EXISTS boards DROP COLUMN IF EXISTS category;
COMMIT;
