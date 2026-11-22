-- 댓글·대댓글 Discord DM 전송 이력·공동 선점 (Issue #171)
-- 적용 전 검토용. **053은 잠정 번호다** (052 HOT 공유도 잠정). DB 담당자가 번호를 확정하기 전에는 공용/운영 DB에 적용하지 않는다.
-- 선행 작업: 022_discord_bot_tables.sql (notifications)
-- notifications 테이블과 백엔드 모델(CHECK 포함)은 바꾸지 않는다. 최종 상태(SENT/SKIPPED/FAILED)와 실패 횟수(retry_count)는
-- 계속 notifications가 가진다. 이 테이블은 "지금 누가 보내는 중인가"(선점)와 결과 불명 확인 정보만 가진다.
--
-- 공동 선점: Gateway Bot과 DM Lambda가 **보내기 전에** 같은 notification_id로 이 표에 행을 만든다 (PRIMARY KEY).
--   INSERT ... ON CONFLICT DO UPDATE ... WHERE status = 'FAILED' AND next_retry_at <= now 로 "행이 없거나 재시도 가능한 FAILED"일
--   때만 선점에 성공한다. 그래서 두 경로가 동시에 켜져 있어도 같은 알림은 한 곳만 보낸다.
--
-- sender  GATEWAY : 기존 Gateway Bot(텍스트 DM). 결과가 불명확하거나 선점 후 만료되면 재발송하지 않고 FAILED로 마감한다
--         LAMBDA  : DM Lambda(embed DM + footer 마커 ref:dm-<id>). 결과 불명은 마커로 확인한다
-- status  PENDING : 선점됨 (전송 중이거나 결과 대기)
--         SENT    : 전송 확인
--         FAILED  : 이번 시도는 실패. next_retry_at이 있으면 그 시각 이후 (notifications가 아직 PENDING일 때) 재선점 가능,
--                   NULL이면 자동 재시도 없음 (영구 실패·불명 마감·건너뜀)
--         UNKNOWN : (LAMBDA만) 전송되었을 수도 있음. 미전송이 증명되기 전에는 재발송하지 않는다
-- claim_token / claimed_at / claim_expires_at : 선점 소유권. 결과는 claim_token이 같을 때만 반영된다 (재선점 때 새 토큰)
-- recipient_discord_id : (LAMBDA) 선점 시점의 받는 사람. 결과 불명 확인 때 DM 채널을 다시 열기 위해 필요하다.
--                        탈퇴하면 notifications 행이 삭제되고 CASCADE로 이 값도 함께 지워진다
-- verify_count / last_verified_at / absent_count / last_absent_job_id : (LAMBDA) UNKNOWN 정착 대기와 "미전송 증명" 횟수
-- discord_message_id : 전송 확인된 메시지 (마커로 확인했거나 응답으로 받은 값)
-- error_message, updated_at : 운영 확인용. updated_at은 확인 주기 계산에도 쓴다
--
-- notification_id FK는 ON DELETE CASCADE다: 백엔드 withdraw_member가 탈퇴 회원의 notifications를 직접 DELETE하므로
-- RESTRICT면 탈퇴가 실패한다. 시각 컬럼은 UTC 기준(naive)이다 (notifications의 시각 컬럼과는 별개).
-- 인덱스를 따로 두지 않는다: 조회는 PK(LEFT JOIN) 또는 진행 중 행의 소량 스캔이다.

BEGIN;

SET LOCAL lock_timeout = '10s';

CREATE TABLE IF NOT EXISTS notification_dm_deliveries (
    notification_id BIGINT PRIMARY KEY
        REFERENCES notifications(notification_id) ON DELETE CASCADE,
    sender VARCHAR(8) NOT NULL,
    status VARCHAR(8) NOT NULL,
    claim_token VARCHAR(40) NOT NULL,
    claimed_at TIMESTAMP NOT NULL,
    claim_expires_at TIMESTAMP NOT NULL,
    next_retry_at TIMESTAMP,
    recipient_discord_id VARCHAR(32),
    verify_count INTEGER NOT NULL DEFAULT 0,
    last_verified_at TIMESTAMP,
    absent_count INTEGER NOT NULL DEFAULT 0,
    last_absent_job_id VARCHAR(160),
    discord_message_id VARCHAR(32),
    error_message VARCHAR(500),
    updated_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),

    CONSTRAINT ck_notification_dm_deliveries_sender CHECK (sender IN ('GATEWAY', 'LAMBDA')),
    CONSTRAINT ck_notification_dm_deliveries_status CHECK (status IN ('PENDING', 'SENT', 'FAILED', 'UNKNOWN')),
    CONSTRAINT ck_notification_dm_deliveries_unknown CHECK (status <> 'UNKNOWN' OR sender = 'LAMBDA'),
    CONSTRAINT ck_notification_dm_deliveries_counts CHECK (verify_count >= 0 AND absent_count >= 0)
);

COMMIT;

-- 필요한 DB 권한 (Gateway Bot 계정과 DM DB Lambda 계정 모두)
--   SELECT: notifications, members, posts, recruits, career_posts, comments   (기존 Gateway 권한과 같음)
--   UPDATE: notifications (status, sent_at, error_message, retry_count, last_attempt_at)   (기존과 같음. 선점 시 FOR UPDATE에도 필요)
--   SELECT, INSERT, UPDATE: notification_dm_deliveries
--
-- 전환·롤백 순서: playmate-discord-bot/dm_share/DEPLOY.md. **이 표가 생긴 뒤에는 공동 선점을 모르는 구버전 Gateway를 실행하지 않는다.**
--
-- 되돌리기: DM Lambda와 Gateway를 모두 멈춘 뒤에만
--   DROP TABLE IF EXISTS notification_dm_deliveries;
--   (진행 중이던 알림은 notifications에 PENDING으로 남아 Gateway 기존 방식으로 다시 처리된다 = 중복 가능. 진행 중 행이 없을 때 지운다)
