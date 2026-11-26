-- 046: 삭제된 원댓글도 답글이 있으면 조회하므로 활성 댓글 부분 인덱스와 별도로 필요.
-- 배포 전 045까지 적용. 기존 데이터/정책을 변경하지 않는다. 재실행 가능.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';
CREATE INDEX IF NOT EXISTS idx_comments_post_id ON public.comments (post_id);
-- 최신순/오래된순 페이지에서 전체 게시글을 집계하기 전에 범위를 좁힌다.
CREATE INDEX IF NOT EXISTS idx_board_posts_page ON public.posts (board_id, created_at DESC, post_id DESC)
WHERE deleted_at IS NULL AND COALESCE(post_status, 'PUBLISHED') = 'PUBLISHED';
COMMIT;
