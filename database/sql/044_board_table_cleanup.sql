-- 044: 게시판 테이블 정리 (Issue #159)
--
-- 1. board_notice_posts 제거
--    019가 과정 게시판 안내 공지를 한 번씩만 만들려고 쓴 대응표. 앱 코드는 사용하지 않는다.
--    019는 이제 공지사항 게시판의 안내글 제목으로 중복을 확인한다.
-- 2. post_images 호환 뷰 제거
--    037에서 게시판 이미지는 post_attachments(attachment_scope = 'BOARD')로 옮겨졌고,
--    뷰를 쓰던 게시판 코드는 post_attachments를 직접 사용한다.
--    INSTEAD OF 트리거는 뷰와 함께 삭제된다. 트리거 함수(playmate_attachment_compat_write)는
--    career_talk_attachments 호환 뷰가 계속 사용하므로 남긴다.
-- 3. 회원별 게시판 방문 횟수(member_board_visits)를 방문 기록(member_board_visit_events)으로 통합
--    방문 기록에 board_id·visited_at을 더하고, 회원별 횟수는 기록을 집계해 구한다.
--    기존 횟수는 같은 수의 기록으로 옮긴 뒤(방문 시각은 알 수 없어 이관 시각) 테이블을 삭제한다.
--    board_id가 NULL인 기록은 044 이전 중복 방지 기록 또는 개인 정렬 제외 게시판(공지사항 등) 방문이다.
--
-- 전제: 024, 037 적용. 백업 후 실행. 한 트랜잭션, 재실행 가능.
BEGIN;
SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';
SET LOCAL search_path = public, pg_catalog;

DO $$
BEGIN
    IF to_regclass('public.post_attachments') IS NULL THEN
        RAISE EXCEPTION 'post_attachments가 없습니다. 037_career_board_consolidation.sql을 먼저 적용하세요.';
    END IF;
    IF to_regclass('public.member_board_visit_events') IS NULL THEN
        RAISE EXCEPTION 'member_board_visit_events가 없습니다. 024_member_board_visits.sql을 먼저 적용하세요.';
    END IF;
    -- post_images가 뷰가 아니라 테이블이면 037 이전 DB다. 이미지 데이터를 잃지 않도록 중단한다.
    IF EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname = 'post_images' AND c.relkind <> 'v'
    ) THEN
        RAISE EXCEPTION 'post_images가 테이블입니다. 037_career_board_consolidation.sql을 먼저 적용하세요.';
    END IF;
END $$;

-- 1. 공지 대응표
DROP TABLE IF EXISTS board_notice_posts;

-- 2. 게시판 이미지 호환 뷰 (트리거 trg_post_images_compat 포함)
DROP VIEW IF EXISTS post_images;

-- 3. 방문 기록에 게시판·시각 추가
ALTER TABLE member_board_visit_events
    ADD COLUMN IF NOT EXISTS board_id BIGINT REFERENCES boards(board_id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS visited_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_member_board_visit_events_member_board
    ON member_board_visit_events (member_id, board_id)
    WHERE board_id IS NOT NULL;

DO $$
DECLARE
    expected BIGINT;
    moved BIGINT;
BEGIN
    IF to_regclass('public.member_board_visits') IS NULL THEN
        RETURN;  -- 이미 통합됨
    END IF;

    SELECT COALESCE(SUM(visit_count), 0) INTO expected FROM member_board_visits;

    INSERT INTO member_board_visit_events (member_id, visit_id, board_id, visited_at)
    SELECT v.member_id, gen_random_uuid(), v.board_id, now()
    FROM member_board_visits AS v
    CROSS JOIN LATERAL generate_series(1, v.visit_count);

    GET DIAGNOSTICS moved = ROW_COUNT;
    IF moved <> expected THEN
        RAISE EXCEPTION '방문 횟수 이관 불일치: 기대 %, 이관 %', expected, moved;
    END IF;

    -- 회원·게시판별 횟수가 그대로인지 확인
    IF EXISTS (
        SELECT 1
        FROM member_board_visits AS v
        LEFT JOIN (
            SELECT member_id, board_id, COUNT(*) AS visit_count
            FROM member_board_visit_events
            WHERE board_id IS NOT NULL
            GROUP BY member_id, board_id
        ) AS e USING (member_id, board_id)
        WHERE e.visit_count IS DISTINCT FROM v.visit_count
    ) THEN
        RAISE EXCEPTION '회원별 방문 횟수가 이관 전후로 다릅니다.';
    END IF;

    DROP TABLE member_board_visits;
END $$;

COMMIT;

-- 확인 (별도 실행 가능)
-- SELECT to_regclass('board_notice_posts'), to_regclass('post_images'), to_regclass('member_board_visits');  -- 모두 NULL
-- SELECT member_id, board_id, COUNT(*) FROM member_board_visit_events WHERE board_id IS NOT NULL GROUP BY 1, 2;
