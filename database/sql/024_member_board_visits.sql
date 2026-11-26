BEGIN;

CREATE TABLE IF NOT EXISTS member_board_visits (
    member_id BIGINT REFERENCES members(member_id) ON DELETE CASCADE,
    board_id BIGINT REFERENCES boards(board_id) ON DELETE CASCADE,
    visit_count BIGINT NOT NULL CHECK (visit_count > 0),
    PRIMARY KEY (member_id, board_id)
);

CREATE TABLE IF NOT EXISTS member_board_visit_events (
    member_id BIGINT REFERENCES members(member_id) ON DELETE CASCADE,
    visit_id UUID,
    PRIMARY KEY (member_id, visit_id)
);

COMMIT;
