-- PLAYMATE 이용 통계: 설치 후부터 수집합니다.
-- 기존 members/posts 테이블은 수정하지 않습니다.
BEGIN;

-- 회원별 마지막 수집 시간: 다중 탭에서 같은 시간을 중복 집계하지 않도록 사용
CREATE TABLE IF NOT EXISTS member_activity_tracker (
    member_id BIGINT PRIMARY KEY REFERENCES members(member_id) ON DELETE CASCADE,
    last_ping_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 하루 단위 실제 활동 시간(초): 날짜는 한국 시간 기준
CREATE TABLE IF NOT EXISTS member_daily_activity (
    member_id BIGINT NOT NULL REFERENCES members(member_id) ON DELETE CASCADE,
    activity_date DATE NOT NULL,
    active_seconds INTEGER NOT NULL DEFAULT 0 CHECK (active_seconds >= 0),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (member_id, activity_date)
);

CREATE INDEX IF NOT EXISTS idx_member_daily_activity_date
    ON member_daily_activity (activity_date);

COMMIT;
