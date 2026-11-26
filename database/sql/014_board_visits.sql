-- PLAYMATE 게시판별 방문 횟수 집계 (한국 시간 기준)
-- 개인별 게시판 방문 경로나 게시글 열람 기록은 저장하지 않습니다.
-- 이 SQL은 여러 번 실행해도 기존 집계가 유지됩니다.
BEGIN;

CREATE TABLE IF NOT EXISTS board_daily_visits (
    board_key VARCHAR(40) NOT NULL,
    visit_date DATE NOT NULL,
    visit_count BIGINT NOT NULL DEFAULT 0 CHECK (visit_count >= 0),
    PRIMARY KEY (board_key, visit_date)
);

CREATE INDEX IF NOT EXISTS idx_board_daily_visits_date
    ON board_daily_visits (visit_date);

COMMIT;
