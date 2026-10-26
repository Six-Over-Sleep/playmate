
-- 댓글 및 대댓글 익명 작성 기능 추가
-- 기존 댓글은 닉네임 공개 상태 유지

BEGIN;

ALTER TABLE comments
ADD COLUMN IF NOT EXISTS is_anonymous
BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN comments.is_anonymous IS
'TRUE: 익명 작성 / FALSE: 닉네임 공개';

COMMIT;
