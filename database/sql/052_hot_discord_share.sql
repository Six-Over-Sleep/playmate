-- HOT 게시글 Discord 자동 공유 (Issue #165): HOT 공유 이력 + 최초 BASELINE 완료 표시
-- 적용 전 검토용. **052는 잠정 번호다.** DB 담당자가 번호를 확정하기 전에는 공용/운영 DB에 적용하지 않는다.
-- 선행 작업: 045_post_reactions.sql (HOT 판정이 post_reactions LIKE를 쓴다), 030_board_access_scope.sql (boards.scope_type)
-- 기존 career_discord_announcements(013/048)와 섞지 않는 별도 테이블이다. 취업 공유(#163)의 상태 전이·복구 쿼리에 영향이 없다.
-- 여러 번 실행해도 안전하다 (IF NOT EXISTS). 시각 컬럼은 career_discord_announcements와 같은 UTC 기준(naive)이다.
--
-- hot_discord_shares : HOT 게시글 1건 = 1행 (post_id PRIMARY KEY). 행이 한 번 생기면 상태와 관계없이 다시 "신규 HOT"으로
--                      선점하지 않는다. 그래서 HOT에서 빠졌다가 재진입해도 재공유되지 않는다.
--   status    BASELINE : 최초 baseline 실행 때 이미 HOT이던 글. 공유하지 않는다
--             PENDING  : DB Lambda가 선점함 (발송 큐 게시 여부 불명)
--             SENT     : Discord 게시 확인 (discord_message_id 기록)
--             FAILED   : 미전송이 확실함. next_retry_at이 있고 attempt_count < 한도이며 **그때도 HOT·공개 게시판이면** 재선점
--             UNKNOWN  : 전송되었을 수도 있음. 자동 재발송하지 않고 메시지 마커로 확인한다
--             SKIPPED  : 운영자가 수동으로 "공유하지 않음"으로 정리한 행 (코드는 만들지 않는다)
--   claim_token / claimed_at / claim_expires_at : 선점 소유권과 시각. 결과는 claim_token이 같을 때만 반영된다
--   next_retry_at, attempt_count             : FAILED 재시도 시각과 횟수 한도
--   verify_count / last_verified_at / absent_count / last_absent_job_id : UNKNOWN 정착 대기와 "미전송 증명" 횟수 (#163과 같은 규칙)
--   discord_channel_id / discord_message_id / sent_at : 게시 위치. 후속 Issue(게시 후 삭제 동기화)가 메시지를 지울 때 필요하다
--   error_message, created_at, updated_at   : 운영 확인용. updated_at은 확인 주기 계산에도 쓴다
--
-- post_id에 posts FK를 두지 않는다: ON DELETE CASCADE면 글이 물리 삭제될 때 discord_message_id까지 사라져 이미 게시된 메시지를
-- 찾을 수 없고, RESTRICT면 다른 기능의 글 물리 삭제를 막는다. 행은 baseline/선점 SQL이 posts에서 고른 post_id로만 만들어진다.
-- 인덱스를 따로 두지 않는다: HOT 글만 들어가는 작은 표이고 조회는 PK(LEFT JOIN) 또는 전체 소량 스캔이다.
--
-- hot_discord_share_state : 1행만 존재 (singleton). baseline이 끝나면 같은 트랜잭션에서 기록한다.
--                           이 행이 없으면 relay는 아무것도 선점하지 않는다 (과거 HOT 글 대량 공유 방지).

BEGIN;

SET LOCAL lock_timeout = '10s';

CREATE TABLE IF NOT EXISTS hot_discord_shares (
    post_id BIGINT PRIMARY KEY,
    status VARCHAR(12) NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    claim_token VARCHAR(40),
    claimed_at TIMESTAMP,
    claim_expires_at TIMESTAMP,
    next_retry_at TIMESTAMP,
    verify_count INTEGER NOT NULL DEFAULT 0,
    last_verified_at TIMESTAMP,
    absent_count INTEGER NOT NULL DEFAULT 0,
    last_absent_job_id VARCHAR(160),
    discord_channel_id VARCHAR(32),
    discord_message_id VARCHAR(32),
    error_message VARCHAR(500),
    sent_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),
    updated_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),

    CONSTRAINT ck_hot_discord_shares_status
        CHECK (status IN ('BASELINE', 'PENDING', 'SENT', 'FAILED', 'UNKNOWN', 'SKIPPED')),
    CONSTRAINT ck_hot_discord_shares_counts
        CHECK (attempt_count >= 0 AND verify_count >= 0 AND absent_count >= 0)
);

CREATE TABLE IF NOT EXISTS hot_discord_share_state (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE,
    baseline_completed_at TIMESTAMP NOT NULL,
    CONSTRAINT ck_hot_discord_share_state_singleton CHECK (singleton)
);

COMMIT;

-- DB Lambda(VPC 안) 계정 필요 권한 (#163 권한에 추가)
--   SELECT: posts, boards, post_reactions, recruits
--   SELECT, INSERT, UPDATE: hot_discord_shares, hot_discord_share_state
--
-- 운영 활성화 순서: playmate-discord-bot/hot_share/DEPLOY.md 참고.
--   1) 이 SQL 적용  2) DB Lambda {"action":"hot_baseline"} 1회 실행  3) 그 다음에 5분 Scheduler(hot_relay)를 켠다.
--   baseline 전에 Scheduler가 먼저 켜져도 relay는 {"skipped":"baseline_required"}로 끝난다.
--
-- 사람이 UNKNOWN을 확인한 뒤
--   Discord 채널에 게시되지 않았음을 확인: UPDATE hot_discord_shares SET status = 'FAILED',
--       next_retry_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC' WHERE post_id = <post_id> AND status = 'UNKNOWN';
--       (재선점은 그 시점에도 HOT·공개 게시판·미삭제일 때만 일어난다)
--   이미 게시된 것을 확인: UPDATE hot_discord_shares SET status = 'SENT', discord_message_id = '<message_id>',
--       sent_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC' WHERE post_id = <post_id> AND status = 'UNKNOWN';
--   공유하지 않기로 함: UPDATE hot_discord_shares SET status = 'SKIPPED' WHERE post_id = <post_id> AND status IN ('UNKNOWN', 'FAILED');
--
-- 되돌리기 (이 기능의 이력만 지운다. 다시 켜려면 baseline부터 다시 해야 한다)
--   DROP TABLE IF EXISTS hot_discord_shares, hot_discord_share_state;
