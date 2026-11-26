-- 취업게시판 신규 글 Discord 자동 공지 이력 (Issue #61)
-- 적용 전 검토용: 공용 DB 적용은 DB 담당자와 협의 후 진행
-- 선행 작업: 004_career_posts.sql
--
-- Discord Bot이 매일 18:00(KST) 취준 도감(reviews)·커리어 연구소(lab) 신규 글을 공지하고 결과를 기록한다.
-- 이 테이블이 없으면 Bot은 자동 공지를 하지 않는다 (중복 방지 수단이 없으므로).
--
-- status
--   BASELINE : 이 파일을 적용할 때 이미 있던 글. 공지하지 않음 (최초 실행 대량 공지 방지)
--   PENDING  : Bot이 공지를 선점함. 전송 결과가 저장되지 않은 채 남으면 자동 재시도하지 않음 (중복 방지, 사람이 확인)
--   SENT     : 공지 완료 (discord_message_id 기록)
--   FAILED   : 전송 실패. 다음 실행에서 재시도 (attempt_count가 Bot 설정 한도 미만일 때)
-- 시각 컬럼은 posts와 같은 UTC 기준이다.

BEGIN;

CREATE TABLE IF NOT EXISTS career_discord_announcements (
    post_id BIGINT PRIMARY KEY
        REFERENCES posts(post_id) ON DELETE CASCADE,
    category_code VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL,

    -- 공지를 선점한 날짜 (Asia/Seoul). 하루 최대 공지 수 계산에 사용
    announce_date DATE,
    attempt_count INTEGER NOT NULL DEFAULT 0,

    discord_channel_id VARCHAR(32),
    discord_message_id VARCHAR(32),
    error_message VARCHAR(500),

    claimed_at TIMESTAMP,
    sent_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
    updated_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),

    CONSTRAINT ck_career_discord_announcements_status
        CHECK (status IN ('BASELINE', 'PENDING', 'SENT', 'FAILED')),
    CONSTRAINT ck_career_discord_announcements_category
        CHECK (category_code IN ('reviews', 'lab')),
    CONSTRAINT ck_career_discord_announcements_attempt
        CHECK (attempt_count >= 0)
);

-- 하루 공지 수 집계용
CREATE INDEX IF NOT EXISTS idx_career_discord_announcements_daily
    ON career_discord_announcements (announce_date, status);

-- 기준점: 적용 시점의 기존 취준 도감·커리어 연구소 글은 공지하지 않는다.
INSERT INTO career_discord_announcements (post_id, category_code, status)
SELECT p.post_id, cp.category_code, 'BASELINE'
FROM posts AS p
JOIN career_posts AS cp ON cp.post_id = p.post_id
WHERE cp.category_code IN ('reviews', 'lab')
ON CONFLICT (post_id) DO NOTHING;

COMMIT;

-- Bot DB 계정 필요 권한
--   SELECT: posts, career_posts
--   SELECT, INSERT, UPDATE: career_discord_announcements
--
-- 결과가 남지 않은 PENDING을 확인 후 다시 공지하려면 (Discord 채널에 실제 게시되지 않았음을 확인한 뒤)
-- UPDATE career_discord_announcements SET status = 'FAILED' WHERE post_id = <post_id> AND status = 'PENDING';
--
-- 되돌리기
-- DROP TABLE IF EXISTS career_discord_announcements;
