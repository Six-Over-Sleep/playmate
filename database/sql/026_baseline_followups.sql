-- 기준 스키마(000) 보완: 001 이후 마이그레이션이 만드는 테이블과 관련되어 000에 넣을 수 없는 항목.
-- 출처: 공유 PostgreSQL 카탈로그 읽기 전용 조회(2026-11-15). 공유 DB에는 이미 있으므로 아무것도 바꾸지 않는다.
-- 대상이 있고 같은 이름이 없을 때만 추가하므로 다시 실행해도 안전하다.

BEGIN;

-- 1. posts.board_id → boards (boards는 001에서 생성)
DO $$
BEGIN
    IF to_regclass('public.boards') IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_posts_board') THEN
        ALTER TABLE posts ADD CONSTRAINT fk_posts_board FOREIGN KEY (board_id) REFERENCES boards(board_id);
    END IF;
END $$;

-- 2. 대댓글 부모 댓글 (comments는 001에서 생성, 이 컬럼의 DDL은 저장소에 없었음)
ALTER TABLE comments ADD COLUMN IF NOT EXISTS parent_comment_id BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_comments_parent') THEN
        ALTER TABLE comments ADD CONSTRAINT fk_comments_parent
            FOREIGN KEY (parent_comment_id) REFERENCES comments(comment_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_comments_parent_comment_id ON comments (parent_comment_id);

COMMIT;
