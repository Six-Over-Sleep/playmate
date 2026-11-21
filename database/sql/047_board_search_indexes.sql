-- 047: ILIKE '%검색어%'의 의미를 그대로 유지하는 선택적 성능 인덱스.
-- 전제: pg_trgm 설치 권한(관리자가 먼저 설치해도 됨), 인덱스 디스크 여유.
-- 짧거나 흔한 검색어는 planner가 순차/게시판 인덱스를 선택할 수 있다.
-- 큰 운영 테이블에서는 별도 점검 시간 또는 관리자의 CONCURRENTLY 적용 계획 필요.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '300s';
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX IF NOT EXISTS idx_board_post_title_trgm ON public.posts USING gin (title gin_trgm_ops)
WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_board_post_body_trgm ON public.posts USING gin (body gin_trgm_ops)
WHERE deleted_at IS NULL;
COMMIT;
