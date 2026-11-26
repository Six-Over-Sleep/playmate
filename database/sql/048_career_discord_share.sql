-- 취업 게시글 Discord 자동 공유 (Issue #163): career_discord_announcements 확장 + 묶음 배치 테이블
-- 적용 전 검토용: 공용 DB 적용은 DB 담당자와 협의 후 진행한다. 013을 수정하지 않는 증분 마이그레이션이다.
-- 선행 작업: 013_career_discord_announcements.sql, 040_career_table_cutover.sql (public.career 사용)
-- 여러 번 실행해도 안전하도록 IF NOT EXISTS / IF EXISTS를 쓴다. 시각 컬럼은 posts와 같은 UTC 기준(naive)이다.
--
-- 한 글(post_id)은 이 테이블에 한 행만 있다 (기존 18:00 공지 행 포함). 그래서 같은 글이 즉시 공유/묶음 공유/기존 공지로
-- 두 번 나가지 않는다.
--
-- share_kind  LEGACY    : 기존 18:00 Gateway Bot 공지가 만든 행 (이 기능은 건드리지 않는다)
--             IMMEDIATE : 후기 즉시 공유 (reviews INTERVIEW/SUCCESS/FINAL), 메시지 1건 = 글 1건
--             DIGEST    : 연구소 20:00 묶음 공유 (lab JOB_STRATEGY/CERTIFICATION/JOB_COMPARISON), 메시지 1건 = 글 최대 5건
-- status      기존 BASELINE / PENDING / SENT / FAILED 에 아래 둘을 추가한다.
--   UNKNOWN : 전송되었을 수도 있어 결과를 확정하지 못함. **자동 재발송하지 않고** 메시지 마커로 확인한다.
--   SKIPPED : 운영자가 수동으로 "공유하지 않음"으로 정리한 행 (자동으로는 만들지 않는다).
-- claim_token / claim_expires_at : 선점 소유권. 결과는 claim_token이 같을 때만 반영된다.
-- next_retry_at : FAILED 행을 다시 선점할 수 있는 시각. NULL이면 자동 재시도하지 않는다 (영구 오류, 기존 LEGACY 행).
-- batch_id      : 묶음 공유의 'digest-YYYY-MM-DD'. 즉시 공유는 NULL.
-- last_verified_at : UNKNOWN으로 바뀐 시각(정착 대기 기준점)이자 마지막 확인 시각. 첫 확인은 이 시각 + 정착 대기 이후에만 한다.
-- absent_count / last_absent_job_id : "마커 없음(미전송 증명)" 결과를 서로 다른 확인 작업에서 몇 번 받았는지. 한도에 이르러야 FAILED.
-- announce_date : **기존 18:00 공지만 채운다** (이 기능은 항상 NULL). 값이 있는 신규 행은 기존 공지가 선점한 것이므로
--                 이 기능은 그 행의 상태를 바꾸지 않는다 (소유권 보호).

BEGIN;

SET LOCAL lock_timeout = '10s';

ALTER TABLE career_discord_announcements
    ADD COLUMN IF NOT EXISTS share_kind VARCHAR(12) NOT NULL DEFAULT 'LEGACY',
    ADD COLUMN IF NOT EXISTS batch_id VARCHAR(40),
    ADD COLUMN IF NOT EXISTS claim_token VARCHAR(40),
    ADD COLUMN IF NOT EXISTS claim_expires_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS verify_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS absent_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_absent_job_id VARCHAR(160);

ALTER TABLE career_discord_announcements
    DROP CONSTRAINT IF EXISTS ck_career_discord_announcements_status;
ALTER TABLE career_discord_announcements
    ADD CONSTRAINT ck_career_discord_announcements_status
        CHECK (status IN ('BASELINE', 'PENDING', 'SENT', 'FAILED', 'UNKNOWN', 'SKIPPED'));

ALTER TABLE career_discord_announcements
    DROP CONSTRAINT IF EXISTS ck_career_discord_announcements_share_kind;
ALTER TABLE career_discord_announcements
    ADD CONSTRAINT ck_career_discord_announcements_share_kind
        CHECK (share_kind IN ('LEGACY', 'IMMEDIATE', 'DIGEST'));

ALTER TABLE career_discord_announcements
    DROP CONSTRAINT IF EXISTS ck_career_discord_announcements_verify;
ALTER TABLE career_discord_announcements
    ADD CONSTRAINT ck_career_discord_announcements_verify CHECK (verify_count >= 0);

-- 오래된 PENDING / 확인 대기 UNKNOWN 복구, 재시도 대상 조회
CREATE INDEX IF NOT EXISTS idx_career_share_recovery
    ON career_discord_announcements (status, claim_expires_at)
    WHERE share_kind <> 'LEGACY' AND status IN ('PENDING', 'UNKNOWN');
CREATE INDEX IF NOT EXISTS idx_career_share_retry
    ON career_discord_announcements (next_retry_at)
    WHERE share_kind <> 'LEGACY' AND status = 'FAILED';
CREATE INDEX IF NOT EXISTS idx_career_share_batch
    ON career_discord_announcements (batch_id) WHERE batch_id IS NOT NULL;

-- 묶음 공유는 날짜당 1건만 만들 수 있다 (batch_date PRIMARY KEY). 같은 날짜의 두 번째 실행은 아무것도 선점하지 못한다.
-- 글 선점(announcements 갱신)과 이 행의 INSERT는 한 트랜잭션이라 함께 반영되거나 함께 롤백된다.
-- 글별 상태(SENT/FAILED/UNKNOWN)와 Discord message_id는 career_discord_announcements가 가진다. 이 표에는 날짜 이력만 둔다.
-- announcements.post_id는 posts 삭제 시 CASCADE로 사라지지만 이 표는 FK가 없어 날짜 이력이 남는다.
CREATE TABLE IF NOT EXISTS career_discord_share_batches (
    batch_date DATE PRIMARY KEY,
    created_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
);

COMMIT;

-- DB Lambda(VPC 안) 계정 필요 권한
--   SELECT: posts, career
--   SELECT, INSERT, UPDATE: career_discord_announcements
--   SELECT, INSERT, UPDATE: career_discord_share_batches
--
-- 적용 순서 (컷오버): docs 의 career_share/DEPLOY.md "컷오버 절차" 참고. 기존 18:00 공지를 끈 뒤 이 기능을 켠다.
--   이 기능의 FAILED 행(attempt_count < 3)을 기존 18:00 공지가 다시 집어 갈 수 있으므로 둘을 동시에 켜지 않는다.
--
-- 사람이 UNKNOWN을 확인한 뒤 (Discord 채널에 실제로 게시되지 않았음을 확인했을 때만) 재발송하려면
--   UPDATE career_discord_announcements SET status = 'FAILED', next_retry_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
--    WHERE post_id = <post_id> AND status = 'UNKNOWN';
-- 이미 게시된 것을 확인했다면
--   UPDATE career_discord_announcements SET status = 'SENT', discord_message_id = '<message_id>', sent_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
--    WHERE post_id = <post_id> AND status = 'UNKNOWN';
--
-- 되돌리기 (데이터 손실 주의: 이 기능의 이력만 지운다)
--   DELETE FROM career_discord_announcements WHERE share_kind <> 'LEGACY';
--   DROP TABLE IF EXISTS career_discord_share_batches;
--   (추가한 컬럼과 CHECK는 LEGACY 행이 영향받지 않으므로 그대로 두어도 된다.
--    status CHECK를 013 상태로 되돌리려면 UNKNOWN/SKIPPED 행이 없는 것을 확인한 뒤 제약을 다시 만든다.)
